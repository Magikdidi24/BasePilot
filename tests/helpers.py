"""Helpers shared by the tests: live crops of the game (no player name or gem count in them),
pasted back on a black frame where they were taken."""
import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# The test run reads and writes a throwaway data dir (LOCALAPPDATA on Windows, HOME on Linux),
# never the user's: templates the app captured there would win over the bundled ones, and
# debug frames would land in it. Set before this module imports app; a test module that
# imported app before this one keeps the real log for the loggers it set up then.
_RUN_DATA_DIR = tempfile.mkdtemp(prefix='basepilot-tests-')


def _remove_run_data_dir():
    from app.utils import logger as log_setup  # a logger set up after the redirect opened its file there
    for (path, handlers) in list(log_setup._shared_handlers.items()):
        if str(path).startswith(_RUN_DATA_DIR):
            for handler in handlers:
                handler.close()
    shutil.rmtree(_RUN_DATA_DIR, ignore_errors=True)


atexit.register(_remove_run_data_dir)
os.environ['LOCALAPPDATA'] = _RUN_DATA_DIR
os.environ['HOME'] = _RUN_DATA_DIR

import numpy as np  # after the redirect, as app below

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
    """A Bot without __init__: a stop event that never fires, a window that is not minimized
    (its screenshot is ``frame`` when one is given) and a mocked input."""
    from app.core.bot import Bot  # lazy: the frame helpers need no bot
    bot = Bot.__new__(Bot)
    bot.stop_event = Mock(**{'is_set.return_value': False, 'wait.return_value': False})
    bot.window = Mock(**{'is_minimized.return_value': False})  # a bare Mock answers truthy: "minimized"
    if frame is not None:
        bot.window.screenshot.return_value = frame
    bot.input = Mock()
    return bot


class DataDirTestCase(unittest.TestCase):
    """For each test, a fresh temporary data dir (LOCALAPPDATA on Windows, HOME on the Linux
    CI): what the code reads or writes there is never the user's, nor another test's."""

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data_dir = folder.name
        env = patch.dict(os.environ, {'LOCALAPPDATA': folder.name, 'HOME': folder.name})
        env.start()
        self.addCleanup(env.stop)


class QtTestCase(DataDirTestCase):
    """A QApplication for the class, and a temporary data dir for each test. Qt's native
    settings store (the registry on Windows) is not redirected: patch the page's QSettings
    with :meth:`temp_settings`."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')  # no window on the desktop
        from PySide6.QtWidgets import QApplication  # lazy: the Linux CI has no Qt
        cls.app = QApplication.instance() or QApplication([])

    def temp_settings(self, name='ui.ini'):
        """A QSettings on an ini file of the temporary data dir, synced before the dir goes:
        Qt writes pending changes out when it drops the object, after the cleanup otherwise."""
        from PySide6.QtCore import QSettings
        settings = QSettings(os.path.join(self.data_dir, name), QSettings.Format.IniFormat)
        self.addCleanup(settings.sync)
        return settings
