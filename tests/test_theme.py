import os
import unittest

try:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QSpinBox
    from app.ui.qt.theme import apply_theme
except ImportError:  # the CI test job installs no Qt
    QApplication = None
from tests.helpers import QtTestCase


@unittest.skipIf(QApplication is None, 'needs PySide6')
class DurationBoxTests(QtTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        apply_theme(cls.app)

    def test_the_duration_shows_its_minutes(self):
        # built like the Run page's duration box: styled, no buttons, 56 px wide
        spin = QSpinBox()
        spin.setObjectName('DurationSpin')
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        spin.setRange(1, 999)
        spin.setValue(999)
        spin.setFixedSize(56, 28)
        spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spin.show()
        self.app.processEvents()
        editor = spin.lineEdit()
        self.assertGreaterEqual(editor.width(), editor.fontMetrics().horizontalAdvance('999'))
        spin.close()


if __name__ == '__main__':
    unittest.main()
