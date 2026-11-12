"""The capture preview of the point picker and the template capture dialogs: the frame scaled
into each dialog's own box, the "Capture WxH (aspect)" line under it, and the message when
there is no capture (the game window mocked)."""
import unittest
from unittest.mock import patch

import numpy as np

try:
    from PySide6.QtWidgets import QApplication

    from app.ui.qt.point_picker import PointPickerDialog
    from app.ui.qt.template_capture import TemplateCaptureDialog
except ImportError:
    QApplication = None

NO_CAPTURE = 'Could not capture the game window. Open Clash of Clans (and check Settings → Game window), then press Refresh.'


@unittest.skipIf(QApplication is None, 'needs PySide6')
class CapturePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def open(self, frame):
        '''Both dialogs on the same capture: ``(picker, capture)``.'''
        with (patch('app.ui.qt.point_picker.WindowService') as picker_window,
              patch('app.ui.qt.template_capture.WindowService') as capture_window):
            picker_window.return_value.screenshot.return_value = frame
            capture_window.return_value.screenshot.return_value = frame
            return (PointPickerDialog(None, 'Pick', 'Click it'), TemplateCaptureDialog())

    def preview(self, dialog):
        pixmap = dialog._image.pixmap()
        return (pixmap.width(), pixmap.height(), dialog._status.text())

    def test_a_16_10_capture_is_scaled_into_each_box(self):
        (picker, capture) = self.open(np.full((767, 1227, 3), 90, np.uint8))
        self.assertEqual(self.preview(picker), (895, 560, 'Capture 1227x767 (16:10). Click the button in the image.'))
        self.assertEqual(self.preview(capture), (895, 560, 'Capture 1227x767 (16:10). Drag a box around a button.'))
        self.assertEqual((capture._image.width(), capture._image.height()), (895, 560))  # fixed to the pixmap
        self.assertEqual((picker._aspect_key, capture._aspect_key), ('16_10', '16_10'))

    def test_a_wide_capture_names_its_aspect_unsupported(self):
        (picker, capture) = self.open(np.full((400, 1600, 3), 90, np.uint8))
        self.assertEqual(self.preview(picker), (960, 240, 'Capture 1600x400 (unsupported aspect). Click the button in the image.'))
        self.assertEqual(self.preview(capture), (1000, 250, 'Capture 1600x400 (unsupported aspect). Drag a box around a button.'))
        self.assertEqual((picker._aspect_key, capture._aspect_key), (None, None))

    def test_no_capture_says_so(self):
        for frame in (None, np.zeros((0, 0, 3), np.uint8)):
            (picker, capture) = self.open(frame)
            with self.subTest(frame=None if frame is None else 'empty'):
                self.assertEqual(self.preview(picker), (0, 0, NO_CAPTURE))
                self.assertEqual(self.preview(capture), (0, 0, NO_CAPTURE))


if __name__ == '__main__':
    unittest.main()
