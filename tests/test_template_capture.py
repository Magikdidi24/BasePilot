import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

try:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.qt.template_capture import TemplateCaptureDialog
except ImportError:  # the CI test job installs no Qt
    QApplication = None


@unittest.skipIf(QApplication is None, 'needs PySide6')
class CaptureNamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def save_as(self, typed=None, pick=None):
        out = Path(tempfile.mkdtemp())
        dlg = TemplateCaptureDialog()
        dlg._frame = np.zeros((731, 1299, 3), dtype=np.uint8)
        dlg._aspect_key = '16_9'
        dlg._selected_crop = lambda: np.full((20, 40, 3), 200, dtype=np.uint8)
        if pick:
            dlg._name.setCurrentIndex(dlg._name.findData(pick))
        if typed is not None:
            dlg._name.setEditText(typed)
        with patch('app.ui.qt.template_capture.get_user_app_data_dir', return_value=out):
            dlg._on_save()
        return sorted(p.name for p in (out / 'templates' / '16_9').glob('*.png')) if (out / 'templates').exists() else []

    def test_core_templates_can_be_picked(self):
        self.assertEqual(self.save_as(pick='multiupgrade.png'), ['multiupgrade.png'])

    def test_typed_name_does_not_overwrite_the_selected_entry(self):
        self.assertEqual(self.save_as(typed='returnhome'), ['returnhome.png'])

    def test_typed_path_cannot_leave_the_templates_folder(self):
        self.assertEqual(self.save_as(typed='../../evil.png'), ['evil.png'])


if __name__ == '__main__':
    unittest.main()
