"""Hide game: the game window off the desktop, still restored, so the bot keeps seeing and
tapping it while the PC is used for something else; and a run that waits for a minimized
game instead of failing cycles blind."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import numpy as np

from app.core.bot import _IDLE_RECHECK_SECONDS, _MINIMIZED_POLL_SECONDS
from app.services.window import HWND_BOTTOM, WindowService, off_desktop
from app.utils import window_settings_store
from app.utils.window_settings_store import forget_hidden_home, is_game_hidden, load_hidden_home, load_hidden_window, save_hidden_home
from tests.helpers import DataDirTestCase, QtTestCase, bare_bot

try:
    from PySide6.QtWidgets import QApplication
    from app.ui.qt.pages.run import RunPage
except ImportError:  # no PySide6: the page tests are skipped
    QApplication = None

HOME = (267, 164, 1574, 976)  # the game window as measured live on a 1920x1200 desktop
PARKED = (-32000, -32000, -31840, -31972)  # where Windows keeps a minimized window
GAME = 'HwndWrapper[DefaultDomain;;game]'


class FakeUser32:
    """One Google Play Games window (10, around the game surface 11; 20 is one of its
    dialogs) on a 1920x1200 desktop, and what Windows does with it. Placements count from
    ``origin``, the work area's corner (a taskbar on the left moves it); the rest in screen
    coordinates."""
    DESKTOP = (0, 0, 1920, 1200)

    def __init__(self, iconic=False, show_cmd=1, flags=0, rect=HOME, normal=HOME, origin=(0, 0)):
        (self.iconic, self.show_cmd, self.flags, self.origin) = (iconic, show_cmd, flags, origin)
        (self.rect, self.normal) = (PARKED if iconic else rect, normal)  # normal: screen coordinates
        self.alive = {10, 11, 20}
        self.foreground = 0
        self.placements = []  # the places SetWindowPlacement was given, on the screen
        self.z = None
        self.resize_off_desktop = False  # a screen of another scale past the edge

    def IsWindow(self, hwnd):
        return hwnd in self.alive

    def GetClassNameW(self, hwnd, buf, size):
        buf.value = GAME if hwnd == 10 else 'Other'
        return len(buf.value)

    def GetAncestor(self, hwnd, flag):
        return 10 if hwnd in (10, 11, 20) else hwnd  # the dialog's root owner is the game too

    def GetParent(self, hwnd):
        return 10 if hwnd == 11 else 0

    def GetSystemMetrics(self, index):
        return {76: 0, 77: 0, 78: 1920, 79: 1200}[index]

    def SystemParametersInfoW(self, action, param, ref, flags):
        r = ref._obj
        (r.left, r.top, r.right, r.bottom) = (self.origin[0], self.origin[1], 1920, 1200 - 48)
        return True

    def IsIconic(self, hwnd):
        return self.iconic

    def GetForegroundWindow(self):
        return self.foreground

    def SetForegroundWindow(self, hwnd):
        self.foreground = hwnd
        return True

    def GetWindowRect(self, hwnd, ref):
        r = ref._obj
        (r.left, r.top, r.right, r.bottom) = self.rect
        return True

    def GetWindowPlacement(self, hwnd, ref):
        wp = ref._obj
        (wp.showCmd, wp.flags) = (2 if self.iconic else self.show_cmd, self.flags)
        n = wp.rcNormalPosition
        (ox, oy) = self.origin
        (n.left, n.top, n.right, n.bottom) = (self.normal[0] - ox, self.normal[1] - oy, self.normal[2] - ox, self.normal[3] - oy)
        return True

    def SetWindowPlacement(self, hwnd, ref):
        wp = ref._obj
        n = wp.rcNormalPosition
        (ox, oy) = self.origin
        place = (n.left + ox, n.top + oy, n.right + ox, n.bottom + oy)
        self.placements.append(place)
        if off_desktop(place, self.DESKTOP):  # Windows pulls a place no screen shows onto the desktop
            place = (0, 0, place[2] - place[0], place[3] - place[1])
        self.normal = place
        self.iconic = wp.showCmd in (2, 6, 7)
        if not self.iconic:
            (self.rect, self.show_cmd) = (place, 1)
        return True

    def SetWindowPos(self, hwnd, after, x, y, cx, cy, flags):
        (w, h) = (self.rect[2] - self.rect[0], self.rect[3] - self.rect[1])
        if self.resize_off_desktop and x >= self.DESKTOP[2]:
            (w, h) = (w * 3 // 2, h * 3 // 2)
        self.rect = self.normal = (x, y, x + w, y + h)
        self.z = after
        return True

    def minimize(self):  # Show desktop: the window's restore place stays where it was
        (self.normal, self.rect, self.iconic) = (self.rect, PARKED, True)


def service(**state):
    user32 = FakeUser32(**state)
    window = WindowService.__new__(WindowService)  # no __init__: it looks for the real game
    (window.user32, window.hwnd, window.window_name) = (user32, 11, 'Clash of Clans')
    return (window, user32)


def size(rect):
    return (rect[2] - rect[0], rect[3] - rect[1])


class HideGameTests(DataDirTestCase):
    def setUp(self):
        super().setUp()
        quiet = patch('app.services.window.logger')  # the real log is the user's: no fake hides in it
        quiet.start()
        self.addCleanup(quiet.stop)

    def test_hidden_off_the_desktop_then_shown_where_it_was(self):
        (window, user32) = service()
        self.assertEqual(window.hide_game(), '')
        self.assertTrue(off_desktop(user32.rect, user32.DESKTOP))
        self.assertEqual(size(user32.rect), size(HOME))  # the capture keeps its size
        self.assertFalse(window.is_minimized())  # so the bot keeps seeing it
        self.assertEqual(user32.z, HWND_BOTTOM)  # the last window Windows activates
        self.assertEqual((load_hidden_home(), load_hidden_window()), (HOME, (10, GAME)))
        self.assertTrue(window.show_game())
        self.assertEqual(user32.rect, HOME)
        self.assertFalse(is_game_hidden())

    def test_a_minimized_game_is_hidden_without_coming_onto_the_desktop(self):
        (window, user32) = service(iconic=True)
        self.assertEqual(window.hide_game(), '')
        self.assertEqual(user32.placements[0][0], 1920 - 8)  # restored with a sliver on screen only
        self.assertTrue(off_desktop(user32.rect, user32.DESKTOP))
        self.assertFalse(user32.iconic)
        self.assertEqual(load_hidden_home(), HOME)

    def test_with_a_taskbar_on_the_left_the_sliver_is_still_on_the_screen(self):
        (window, user32) = service(iconic=True, origin=(48, 0))
        self.assertEqual(window.hide_game(), '')
        self.assertEqual(user32.placements[0][0], 1920 - 8)  # on the screen: placements count from the work area
        self.assertTrue(off_desktop(user32.rect, user32.DESKTOP))
        window.show_game()
        self.assertEqual(user32.rect, HOME)

    def test_brought_forward_it_comes_back(self):
        for (foreground, owned) in ((10, False), (20, False), (10, True)):  # its taskbar button or Alt+Tab, one of its dialogs
            with self.subTest(foreground=foreground, owned=owned):
                (window, user32) = service()
                window.hide_game()
                if owned:  # the game window itself has an owner
                    user32.GetAncestor = lambda hwnd, flag: 99 if flag == 3 else 10
                user32.foreground = foreground
                self.assertEqual(window.keep_hidden(), '')
                self.assertEqual(user32.rect, HOME)
                self.assertFalse(is_game_hidden())

    def test_minimized_while_hidden_it_hides_again_and_keeps_its_place(self):
        (window, user32) = service()
        window.hide_game()
        user32.minimize()
        self.assertEqual(window.keep_hidden(), '')
        self.assertFalse(user32.iconic)
        self.assertTrue(off_desktop(user32.rect, user32.DESKTOP))
        self.assertEqual(load_hidden_home(), HOME)  # not the place off the desktop

    def test_minimized_to_come_back_maximized_it_stays_as_the_user_left_it(self):
        (window, user32) = service()
        window.hide_game()
        user32.minimize()
        user32.flags = 2  # WPF_RESTORETOMAXIMIZED
        self.assertIn('maximized', window.keep_hidden())
        self.assertTrue(user32.iconic)
        self.assertFalse(is_game_hidden())  # given up, once

    def test_back_on_the_desktop_some_other_way_it_is_no_longer_hidden(self):
        (window, user32) = service()
        window.hide_game()
        user32.rect = user32.normal = (0, 0, 1307, 812)  # moved back by hand
        window.keep_hidden()
        self.assertFalse(is_game_hidden())

    def test_nothing_is_done_while_nothing_is_hidden(self):
        (window, user32) = service()
        user32.foreground = 10
        window.keep_hidden()
        self.assertEqual((user32.rect, user32.placements), (HOME, []))

    def test_closed_while_hidden_it_is_waited_for_then_followed(self):
        (window, user32) = service()
        window.hide_game()
        user32.alive = set()  # the game closed
        window._resolve_hwnd = Mock(return_value=0)
        self.assertEqual(window.keep_hidden(), '')
        self.assertTrue(is_game_hidden())  # the way back is kept
        self.assertFalse(window.show_game())  # nothing to show yet: still kept
        self.assertTrue(is_game_hidden())
        looked = window._resolve_hwnd.call_count
        window.keep_hidden()
        self.assertEqual(window._resolve_hwnd.call_count, looked)  # looked for at most every 10 s: all windows are walked
        # Play Games opens it again where it was last, off the desktop, as window 30
        user32.alive = {30}
        window._resolve_hwnd.return_value = 30
        window._next_hidden_find = 0  # 10 s later
        user32.GetAncestor = lambda hwnd, flag: hwnd
        user32.GetClassNameW = lambda hwnd, buf, n: setattr(buf, 'value', GAME) or 1
        window.keep_hidden()
        self.assertEqual(load_hidden_window()[0], 30)
        self.assertTrue(window.show_game())
        self.assertEqual(user32.rect, HOME)

    def test_a_game_off_the_desktop_with_nothing_saved_gets_a_way_back(self):
        (window, user32) = service(rect=(2120, 164, 3427, 976), normal=(2120, 164, 3427, 976))
        self.assertEqual(window.hide_game(), '')  # hidden already, by a BasePilot that crashed
        self.assertTrue(is_game_hidden())
        self.assertTrue(window.show_game())
        self.assertFalse(off_desktop(user32.rect, user32.DESKTOP))

    def test_a_maximized_game_is_left_alone(self):
        (window, user32) = service(show_cmd=3)
        self.assertIn('maximized', window.hide_game())
        self.assertEqual(user32.rect, HOME)
        self.assertFalse(is_game_hidden())

    def test_a_snapped_game_is_left_alone(self):
        (window, user32) = service(rect=(0, 0, 960, 600))  # its restore place is still HOME
        self.assertIn('snapped', window.hide_game())
        self.assertEqual((user32.rect, user32.z), ((0, 0, 960, 600), None))
        self.assertFalse(is_game_hidden())

    def test_a_game_resized_off_the_desktop_comes_back(self):
        (window, user32) = service()
        user32.resize_off_desktop = True
        self.assertIn('right-most screen', window.hide_game())
        self.assertEqual(user32.rect, HOME)
        self.assertFalse(is_game_hidden())

    def test_without_its_saved_place_it_still_comes_onto_the_desktop(self):
        (window, user32) = service()
        window.hide_game()
        window_settings_store._hidden_window_path().write_text('{', encoding='utf-8')  # cut off mid-write
        self.assertIsNone(load_hidden_home())
        self.assertTrue(is_game_hidden())
        window.show_game()
        self.assertFalse(off_desktop(user32.rect, user32.DESKTOP))
        self.assertFalse(is_game_hidden())


class MinimizedRunTests(unittest.TestCase):
    def minimized_once(self, bot):
        """The game window is minimized until the run's first wait for it."""
        state = {'minimized': True}
        bot.window.is_minimized.side_effect = lambda: state['minimized']
        bot.stop_event.wait.side_effect = lambda s: state.update(minimized=state['minimized'] and s != _MINIMIZED_POLL_SECONDS) or False
        return state

    def test_a_minimized_game_is_waited_for(self):
        bot = bare_bot()
        bot.window.is_minimized.side_effect = [True, True, True, False]
        bot._status_callback = Mock()
        with self.assertLogs('BotCore', 'WARNING') as logs:
            bot._wait_while_minimized()
        self.assertEqual(bot.stop_event.wait.call_args_list, [call(_MINIMIZED_POLL_SECONDS)] * 2)
        self.assertIn('Hide game', logs.output[0])
        self.assertIn('Hide game', bot._status_callback.call_args_list[0].args[0])

    def test_stop_ends_the_wait(self):
        bot = bare_bot()
        bot.window.is_minimized.return_value = True
        bot.stop_event.wait.return_value = bot.stop_event.is_set.return_value = True
        with self.assertRaises(InterruptedError), self.assertLogs('BotCore', 'WARNING'):
            bot._wait_while_minimized()

    def test_the_end_of_a_timed_run_ends_the_wait(self):
        bot = bare_bot()
        bot.window.is_minimized.return_value = True
        with self.assertLogs('BotCore', 'WARNING'):
            bot._wait_while_minimized(deadline=time.time() - 1)
        bot.stop_event.wait.assert_not_called()

    def test_a_builder_base_run_never_attacks_a_minimized_game(self):
        bot = bare_bot(np.zeros((767, 1227, 3), np.uint8))
        for name in ('_update_config_size', '_scroll_point', '_recover_safely', '_maybe_auto_upgrade', '_bb_live_status',
                     '_bb_collect_elixir_cart_after_attack', '_bb_maybe_upgrade_walls', '_stop_if_storages_full'):
            setattr(bot, name, Mock(return_value=False))
        bot._scroll_point.return_value = (600, 380)
        state = self.minimized_once(bot)
        seen = []

        def attack():  # blind, a cycle fails: four of them back the run off for 5 min
            seen.append(state['minimized'])
            if len(seen) == 5:
                raise InterruptedError('Stop')
            return not state['minimized']
        bot._bb_attack_once = Mock(side_effect=attack)
        with self.assertRaises(InterruptedError), self.assertLogs('BotCore', 'WARNING'):
            bot._run_builder_base_loop(0)
        self.assertEqual(seen, [False] * 5)
        self.assertNotIn(call(_IDLE_RECHECK_SECONDS), bot.stop_event.wait.call_args_list)

    def test_a_home_village_run_never_attacks_a_minimized_game(self):
        bot = bare_bot(np.zeros((767, 1227, 3), np.uint8))
        bot.config = SimpleNamespace(get_point=lambda key: (640, 750))
        for name in ('_update_config_size', '_scroll_point', '_recover_safely', '_between_raids', '_return_home',
                     '_multi_run_collect_home_village_resources'):
            setattr(bot, name, Mock(return_value=False))
        bot._scroll_point.return_value = (600, 380)
        state = self.minimized_once(bot)
        seen = []

        def attack(method):
            seen.append(state['minimized'])
            if len(seen) == 3:
                raise InterruptedError('Stop')
            return 'no_attack' if state['minimized'] else None
        bot._find_match_and_attack = Mock(side_effect=attack)
        with self.assertRaises(InterruptedError), self.assertLogs('BotCore', 'WARNING'):
            bot._run_loop(1, 0)
        self.assertEqual(seen, [False] * 3)

    def test_a_run_starts_once_the_game_is_back(self):
        bot = bare_bot()
        bot.window.find_window.return_value = True
        order = Mock()
        state = self.minimized_once(bot)
        order.village.side_effect = lambda **kw: order.minimized(state['minimized'])
        for name in ('_reset_loot_session', '_emit_loot_update', '_run_builder_base_loop'):
            setattr(bot, name, Mock())
        bot._ensure_correct_village = order.village
        with self.assertLogs('BotCore', 'WARNING'):
            bot.start(5, 0, builder_base=True)
        order.minimized.assert_called_once_with(False)  # the village check taps on what it sees


@unittest.skipIf(QApplication is None, 'needs PySide6')
class HideButtonTests(QtTestCase):
    def make_page(self):
        with patch('app.ui.qt.pages.run.QSettings', return_value=self.temp_settings()):
            page = RunPage(Mock(**{'is_running.return_value': False}), lambda name: None)
        page._game_window_service = Mock()
        return page

    def test_the_button_hides_then_shows_the_game(self):
        page = self.make_page()
        game = page._game_window_service
        game.hide_game.side_effect = lambda: save_hidden_home(HOME) or ''
        game.show_game.side_effect = lambda activate=False: forget_hidden_home() or True
        self.assertEqual(page._btn_hide.text(), 'Hide game')
        self.assertFalse(page._hide_timer is not None and page._hide_timer.isActive())  # nothing to check
        page._btn_hide.click()
        self.assertEqual(page._btn_hide.text(), 'Show game')
        self.assertTrue(page._hide_timer is None or page._hide_timer.isActive())
        page._btn_hide.click()
        game.show_game.assert_called_once_with(activate=True)  # in front: the user asked for it
        self.assertEqual(page._btn_hide.text(), 'Hide game')
        self.assertFalse(page._hide_timer is not None and page._hide_timer.isActive())

    def test_a_refused_hide_says_why(self):
        page = self.make_page()
        page._game_window_service.hide_game.return_value = 'Game window not found.'
        with patch('app.ui.qt.pages.run.show_error') as error:
            page._btn_hide.click()
        self.assertEqual(error.call_args.args[1:], ('Hide game', 'Game window not found.'))
        self.assertEqual(page._btn_hide.text(), 'Hide game')

    def test_a_game_that_cannot_come_back_says_so_and_stays_hidden(self):
        page = self.make_page()
        save_hidden_home(HOME)
        page._game_window_service.show_game.return_value = False
        with patch('app.ui.qt.pages.run.show_error') as error:
            page._btn_hide.click()
        self.assertEqual(error.call_args.args[1], 'Show game')
        self.assertEqual(page._btn_hide.text(), 'Show game')

    def test_a_failing_check_is_logged_once(self):
        page = self.make_page()
        save_hidden_home(HOME)
        page._game_window_service.keep_hidden.side_effect = OSError('denied')
        with self.assertLogs('HideGame', 'WARNING') as logs:
            page._keep_game_hidden()
            page._keep_game_hidden()
        self.assertEqual(len(logs.output), 1)

    def test_closing_brings_a_hidden_game_back_behind_the_other_windows(self):
        page = self.make_page()
        page.show_hidden_game()
        page._game_window_service.show_game.assert_not_called()  # nothing hidden
        save_hidden_home(HOME)
        page.show_hidden_game()
        page._game_window_service.show_game.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
