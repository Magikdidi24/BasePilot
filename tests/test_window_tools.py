"""Settings -> Game window, Test and Info: a sub-window list that cannot be read still leaves the
surface's size on screen and the info dialog open, and Test reports the first subWin (the
decompiled handlers kept everything inside their try and lost the loop's break)."""
import importlib.util
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.window import WindowCandidate
from tests.helpers import QtTestCase

HAVE_QT = importlib.util.find_spec('PySide6') is not None  # the CI test job installs no Qt
GAME = WindowCandidate(top_hwnd=1, title='Clash of Clans', top_class='CROSVM_1', child_hwnd=11, child_class='CROSVM_1')


@unittest.skipUnless(HAVE_QT, 'needs PySide6')
class WindowToolTests(QtTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        super().setUpClass()
        from PySide6.QtWidgets import QLabel, QWidget
        from app.ui.qt.pages import settings
        (cls.settings, cls.QLabel, cls.QWidget) = (settings, QLabel, QWidget)

    def page(self):
        page = self.settings.SettingsPage.__new__(self.settings.SettingsPage)
        self.QWidget.__init__(page)  # the widget alone: no profile, window list or display read
        page._window_status = self.QLabel()
        page._selected_candidate = lambda: GAME
        return page

    def service(self, **behaviour):
        return patch.object(self.settings, 'WindowService', return_value=Mock(**behaviour))

    def test_the_first_sub_window_is_reported(self):
        subwins = [SimpleNamespace(cls='subWin', width=1920, height=1200),
                   SimpleNamespace(cls='subWin', width=1280, height=720)]
        page = self.page()
        with self.service(**{'window_pixel_size.return_value': (1920, 1200), 'enumerate_descendants.return_value': subwins}) as service:
            page._on_test_window()
        self.assertIn('Inner subWin: 1920x1200 (16:10)', page._window_status.text())
        service.return_value.enumerate_descendants.assert_called_once_with(GAME.top_hwnd)  # walked once

    def test_the_surface_size_shows_when_sub_windows_cannot_be_listed(self):
        page = self.page()
        with (self.service(**{'window_pixel_size.return_value': (1920, 1200), 'enumerate_descendants.side_effect': OSError('denied')}),
              self.assertLogs('SettingsPage', 'WARNING')):
            page._on_test_window()
        self.assertEqual(page._window_status.text(), 'Capture target CROSVM_1: 1920x1200 (16:10)\nSurface OK to use.')

    def test_the_info_dialog_opens_when_sub_windows_cannot_be_listed(self):
        page = self.page()
        with (self.service(**{'enumerate_descendants.side_effect': OSError('denied')}),
              patch.object(self.settings, 'WindowInfoDialog') as dialog, self.assertLogs('SettingsPage', 'WARNING')):
            page._on_window_info()
        dialog.assert_called_once_with(page, GAME, [])
        dialog.return_value.exec.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
