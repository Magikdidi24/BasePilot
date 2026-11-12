"""Helpers shared by the tests: live crops of the game (no player name or gem count in them),
pasted back on a black frame where they were taken."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from app.config import Config
from app.utils.common import read_image

FIXTURES = Path(__file__).parent / 'fixtures'
GPG = (1227, 767)  # (w, h): the default Google Play Games window, 16:10
WAYDROID = (1920, 1200)  # (w, h): where the October 2026 UI was first measured


def canvas(*crops, size=GPG):
    """A black frame of ``size`` (w, h) with each crop pasted back where it was taken: crops
    are ``(file in tests/fixtures, x, y)``, x and y of the crop's top-left corner. The Config
    is sized for the frame, as for a live capture."""
    (w, h) = size
    frame = np.zeros((h, w, 3), np.uint8)
    for (name, x, y) in crops:
        img = read_image(FIXTURES / name)
        if img is None:
            raise FileNotFoundError(FIXTURES / name)
        frame[y:y + img.shape[0], x:x + img.shape[1]] = img
    Config().set_target_size_from_frame(frame)
    return frame


def bare_bot(frame=None):
    """A Bot without __init__: a stop event that never fires, a window (its screenshot is
    ``frame`` when one is given) and a mocked input."""
    from app.core.bot import Bot  # lazy: the frame helpers need no bot
    bot = Bot.__new__(Bot)
    bot.stop_event = Mock(**{'is_set.return_value': False, 'wait.return_value': False})
    bot.window = Mock() if frame is None else Mock(**{'screenshot.return_value': frame})
    bot.input = Mock()
    return bot


class QtTestCase(unittest.TestCase):
    """A QApplication for the class and, for each test, a temporary data dir (LOCALAPPDATA on
    Windows, HOME on the Linux CI): what a page reads or writes there is never the user's.
    Qt's native settings store (the registry on Windows) is not redirected: patch the page's
    QSettings with :meth:`temp_settings`."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from PySide6.QtWidgets import QApplication  # lazy: the Linux CI has no Qt
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data_dir = folder.name
        env = patch.dict(os.environ, {'LOCALAPPDATA': folder.name, 'HOME': folder.name})
        env.start()
        self.addCleanup(env.stop)

    def temp_settings(self, name='ui.ini'):
        """A QSettings on an ini file of the temporary data dir, synced before the dir goes:
        Qt writes pending changes out when it drops the object, after the cleanup otherwise."""
        from PySide6.QtCore import QSettings
        settings = QSettings(os.path.join(self.data_dir, name), QSettings.Format.IniFormat)
        self.addCleanup(settings.sync)
        return settings
