"""Start-button checks: the game-window probe in app/config.py and the window pin it reads."""
import io
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from app.config import check_game_window_aspect_for_start
from app.services.window import WindowService
from app.utils.window_settings_store import WindowSelection, get_window_selection_path, load_window_selection


def window_of_size(size):
    """WindowService without a real window: it reports this outer size (None = not found)."""
    service = Mock()
    service.return_value.get_outer_pixel_size.return_value = size
    return patch('app.services.window.WindowService', service)


@contextmanager
def qt_message_box(error=None):
    """A stand-in PySide6.QtWidgets (the CI installs no Qt); yields its QMessageBox, which raises ``error``."""
    widgets = types.ModuleType('PySide6.QtWidgets')
    widgets.QMessageBox = Mock(side_effect=error, **{'critical.side_effect': error})
    with patch.dict(sys.modules, {'PySide6.QtWidgets': widgets}):
        yield widgets.QMessageBox


class StartCheckTests(unittest.TestCase):
    def test_a_failing_probe_is_logged_and_start_goes_ahead(self):
        for (case, service) in (('constructor', Mock(side_effect=OSError('user32 unavailable'))),
                                ('size probe', Mock(**{'return_value.get_outer_pixel_size.side_effect': OSError('user32 unavailable')}))):
            with self.subTest(case):
                with patch('app.services.window.WindowService', service), self.assertLogs('Config', 'WARNING') as logs:
                    self.assertTrue(check_game_window_aspect_for_start())
                self.assertIn('user32 unavailable', logs.output[0])

    def test_unsupported_aspect_is_refused_with_an_error_dialog(self):
        with window_of_size((1000, 1000)), qt_message_box() as box:
            self.assertFalse(check_game_window_aspect_for_start(parent='main window'))
        box.critical.assert_called_once()
        self.assertEqual(box.critical.call_args.args[0], 'main window')

    def test_unsupported_aspect_without_a_dialog_goes_to_the_log_and_stderr(self):
        with (window_of_size((1000, 1000)), qt_message_box(RuntimeError('no display')),
              patch('sys.stderr', new_callable=io.StringIO) as err, self.assertLogs('Config', 'ERROR') as logs):
            self.assertFalse(check_game_window_aspect_for_start())
        self.assertIn('Could not show dialog: no display', logs.output[0])  # the decompiled handler logged None
        self.assertIn('Aspect ratio not supported', err.getvalue())

    def test_supported_aspect_starts(self):
        for size in ((2560, 1440), (1920, 1200)):  # 16:9, 16:10
            with self.subTest(size=size), window_of_size(size), qt_message_box() as box:
                self.assertTrue(check_game_window_aspect_for_start())
                box.critical.assert_not_called()

    def test_missing_window_is_refused_and_a_dialog_failure_is_logged(self):
        with window_of_size(None), qt_message_box(RuntimeError('no display')), self.assertLogs('Config', 'ERROR') as logs:
            self.assertFalse(check_game_window_aspect_for_start())
        self.assertIn('window-not-found dialog: no display', logs.output[0])  # the decompiled handler logged None


class WindowPinTests(unittest.TestCase):
    def test_corrupt_window_json_is_no_manual_pick(self):
        for (case, payload) in (('truncated', b'{"title": "Clash of Clans", "top_cl'),
                                ('not UTF-8', b'{"title": "Clash of Clans \xe9"}')):
            # LOCALAPPDATA holds the data dir on Windows, HOME (~/.local/share) on the Linux CI.
            with (self.subTest(case), tempfile.TemporaryDirectory() as tmp,
                  patch.dict(os.environ, {'LOCALAPPDATA': tmp, 'HOME': tmp})):
                path = get_window_selection_path()
                path.write_bytes(payload)
                ws = WindowService.__new__(WindowService)  # no real window: only auto-detect is stubbed
                ws.window_name = 'Clash of Clans'
                ws._auto_detect_child = Mock(return_value=4242)
                with self.assertLogs('WindowSettings', 'WARNING') as logs:
                    self.assertTrue(ws.find_window())  # raised on the file, so Start failed with no message
                    self.assertEqual(load_window_selection(), WindowSelection())
                self.assertEqual(len(logs.output), 1)  # one warning, though the pin is re-read every 30 s
                self.assertIn(str(path), logs.output[0])
                self.assertTrue(path.is_file())  # the user's file is left alone
                ws._auto_detect_child.assert_called_once()


if __name__ == '__main__':
    unittest.main()
