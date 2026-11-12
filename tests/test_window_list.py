"""The pinned window: one rule (WindowSelection.matches) for resolving the pin and for the
Settings window list's preselection. The decompiled list check never compared the class, so of
two same-title windows the last one was preselected, not the one the pin resolves to."""
import importlib.util
import os
import unittest

from app.services.window import WindowCandidate, WindowService
from app.utils.window_settings_store import WindowSelection

HAVE_QT = importlib.util.find_spec('PySide6') is not None  # the CI test job installs no Qt
GAME = WindowCandidate(top_hwnd=1, title='Clash of Clans', top_class='CROSVM_1', child_hwnd=11)
GAME2 = WindowCandidate(top_hwnd=4, title='Clash of Clans', top_class='CROSVM_2', child_hwnd=41)  # a second client
CHROME = WindowCandidate(top_hwnd=2, title='Clash of Clans', top_class='Chrome_WidgetWin_1')
NOTEPAD = WindowCandidate(top_hwnd=3, title='Notepad', top_class='Notepad')


class PinRuleTests(unittest.TestCase):
    def test_the_title_matches_case_and_outer_spaces_aside(self):
        self.assertTrue(WindowSelection(title=' clash of CLANS ').matches(GAME))
        self.assertFalse(WindowSelection(title='Clash').matches(GAME))

    def test_the_class_counts_only_when_one_was_saved(self):
        self.assertTrue(WindowSelection(title='Clash of Clans').matches(CHROME))
        self.assertFalse(WindowSelection(title='Clash of Clans', top_class='CROSVM_1').matches(CHROME))

    def test_no_saved_title_matches_any_title(self):
        self.assertTrue(WindowSelection(top_class='Notepad', child_class='X').matches(NOTEPAD))

    def test_nothing_matches_a_selection_that_is_not_set(self):
        self.assertFalse(WindowSelection().matches(GAME))


class ResolveHwndTests(unittest.TestCase):
    """WindowService._resolve_hwnd with the Win32 calls stubbed."""
    def service(self, windows):
        ws = WindowService.__new__(WindowService)
        ws.enumerate_windows = lambda: windows
        ws._resolve_surface = lambda hwnd, cls, preferred='': (hwnd * 10, 'CROSVM_1') if cls.startswith('CROSVM') else (0, '')
        return ws

    def test_the_pin_resolves_to_the_surface_of_its_class(self):
        ws = self.service([GAME, GAME2, CHROME])
        self.assertEqual(ws._resolve_hwnd(WindowSelection(title='Clash of Clans', top_class='CROSVM_2', child_class='CROSVM_1')), 40)

    def test_two_matching_game_windows_use_the_first_and_say_so(self):
        ws = self.service([GAME, GAME2, CHROME])
        with self.assertLogs('WindowService', 'WARNING'):
            self.assertEqual(ws._resolve_hwnd(WindowSelection(title='Clash of Clans', child_class='CROSVM_1')), 10)

    def test_a_pin_with_no_game_surface_resolves_to_nothing(self):
        self.assertEqual(self.service([CHROME, NOTEPAD])._resolve_hwnd(WindowSelection(title='Clash of Clans')), 0)


@unittest.skipUnless(HAVE_QT, 'needs PySide6')
class PinnedRowTests(unittest.TestCase):
    def pinned_row(self, saved):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from app.ui.qt.pages.settings import _pinned_row
        return _pinned_row([GAME, GAME2, CHROME, NOTEPAD], saved)  # game windows first, as listed

    def test_the_saved_class_picks_between_same_titles(self):
        self.assertEqual(self.pinned_row(WindowSelection(title='Clash of Clans', top_class='CROSVM_2')), 1)

    def test_without_a_saved_class_the_game_window_is_preselected(self):
        self.assertEqual(self.pinned_row(WindowSelection(title='Clash of Clans')), 0)

    def test_a_pin_matching_no_game_window_preselects_nothing(self):
        self.assertEqual(self.pinned_row(WindowSelection(title='Clash of Clans', top_class='Other')), -1)
        self.assertEqual(self.pinned_row(WindowSelection(title='Notepad')), -1)  # no game surface

    def test_nothing_pinned_preselects_nothing(self):
        self.assertEqual(self.pinned_row(WindowSelection()), -1)


if __name__ == '__main__':
    unittest.main()
