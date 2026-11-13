"""Endless runs in either village, and "Stop when storages are full"."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import cv2
import numpy as np

from app.config import Config
from app.core import village_state
from app.core.bot import _IDLE_RECHECK_SECONDS
from app.core.village_state import storages_full
from tests.helpers import QtTestCase, bare_bot

try:
    from PySide6.QtWidgets import QApplication
    from app.ui.qt.pages.run import RunPage
except ImportError:  # no PySide6: the page tests are skipped
    QApplication = None

FIXTURES = Path(__file__).parent / 'fixtures'


def make_bot():
    bot = bare_bot(np.zeros((767, 1227, 3), np.uint8))
    bot.vision = Mock()
    bot.vision.find_template.return_value = (None, None)
    bot.config = SimpleNamespace(aspect_key='16_10', width=1227, height=767, get_point=lambda k: (640, 750),
                                 scale_point=lambda p, size=None: (p[0] * 0.48, p[1] * 0.48))
    bot._update_config_size = Mock()
    bot._recover_safely = Mock()
    bot._maybe_auto_upgrade = Mock()
    bot._bb_live_status = Mock()
    bot._bb_collect_elixir_cart_after_attack = Mock()
    bot.finish_reason = None
    return bot


def builder_base_home():
    """The Builder Base home at 1227x767: its HUD (651 626 gold, 1 356 974 elixir) and its
    Build button, pasted back where they were taken."""
    frame = np.zeros((767, 1227, 3), np.uint8)
    frame[383:767] = cv2.imread(str(FIXTURES / 'gpg767_builder_base_home_bottom.jpg'))
    hud = cv2.imread(str(FIXTURES / 'gpg767_hud_bb_home.png'))
    frame[:hud.shape[0], 900:900 + hud.shape[1]] = hud
    Config().set_target_size_from_frame(frame)
    return frame


class BuilderBaseBarsTests(unittest.TestCase):
    def test_the_builder_base_bars_are_read_where_the_home_village_ones_are(self):
        self.assertEqual(storages_full(builder_base_home()), (False, False))

    def test_the_builder_base_violet_elixir_is_a_fill(self):
        # Both bars filled to their left end with their own colours, row by row: the gold of
        # the Builder Base is the Home Village's, its elixir violet (H 132-135), not magenta.
        frame = builder_base_home()
        (h, w) = frame.shape[:2]
        (x0, x1) = (int(w - 0.33 * h), int(w - 0.06 * h))  # the bars, short of their icons
        for (ya, yb) in (village_state._GOLD_BAR_Y, village_state._ELIXIR_BAR_Y):
            (y0, y1) = (int(ya * h), int(yb * h))
            band = frame[y0:y1, x0:x1]
            filled = (cv2.cvtColor(band, cv2.COLOR_BGR2HSV)[..., 1] >= 80).mean(axis=0) > 0.6
            fill = np.median(band[:, filled], axis=1).astype(np.uint8)
            frame[y0:y1, x0:x1] = fill[:, None, :]
        self.assertEqual(storages_full(frame), (True, True))


class FullStorageStopTests(unittest.TestCase):
    @patch('app.core.bot.storages_full', side_effect=[(True, True), (True, False)])
    def test_full_takes_two_frames_in_a_row(self, _full):
        self.assertFalse(make_bot()._storages_full_now())

    @patch('app.core.bot.storages_full', side_effect=[(True, True), (True, True)])
    def test_two_full_frames_are_full(self, _full):
        self.assertTrue(make_bot()._storages_full_now())

    def test_nothing_is_read_with_the_option_off(self):
        bot = make_bot()
        bot._storages_full_now = Mock(return_value=True)
        self.assertFalse(bot._stop_if_storages_full())
        bot._storages_full_now.assert_not_called()

    def test_a_multi_run_moves_on_to_the_next_account(self):
        bot = make_bot()
        bot._stop_when_full = bot._multi_run = True
        bot._storages_full_now = Mock(return_value=True)
        self.assertTrue(bot._stop_if_storages_full())  # this account's session ends
        self.assertIsNone(bot.finish_reason)  # not the run

    def test_between_raids_clan_walls_upgrades_idle_then_full_storages(self):
        bot = make_bot()
        order = Mock()
        (bot._maybe_clan_assist, bot._maybe_upgrade_walls, bot._maybe_auto_upgrade) = (order.clan, order.walls, order.upgrade)
        (bot._maybe_idle, bot._stop_if_storages_full) = (order.idle, order.full)
        order.full.side_effect = [False, True]  # before the first raid, then after it
        bot._return_home = Mock()
        bot._find_match_and_attack = Mock(return_value=None)  # a raid played
        self.assertIsNone(bot._run_loop(1, 0, upgrade_walls=True))
        self.assertEqual(order.mock_calls, [call.clan(), call.walls(True), call.upgrade(), call.idle(None), call.full()] * 2)

    def test_a_failing_errand_never_ends_the_farm_loop(self):
        bot = make_bot()
        order = Mock()
        (bot._maybe_upgrade_walls, bot._maybe_idle, bot._stop_if_storages_full) = (order.walls, order.idle, order.full)
        bot._maybe_clan_assist = Mock(side_effect=RuntimeError('HUD read failed'))  # before its own try
        bot._maybe_auto_upgrade = Mock(side_effect=RuntimeError('boom'))
        order.full.return_value = False
        with self.assertLogs('BotCore', 'ERROR'):
            self.assertFalse(bot._between_raids(True, None))
        self.assertEqual(order.mock_calls, [call.walls(True), call.idle(None), call.full()])

    def test_a_status_callback_that_fails_is_only_logged(self):
        bot = make_bot()
        bot._status_callback = Mock(side_effect=RuntimeError('UI gone'))
        bot._status('Upgrades: nothing free')  # does not raise
        bot._status_callback.assert_called_once_with('Upgrades: nothing free')

    def test_a_home_village_run_stops_once_full_after_the_spending(self):
        bot = make_bot()
        bot._stop_when_full = True
        for hook in ('_maybe_clan_assist', '_maybe_upgrade_walls', '_return_home'):
            setattr(bot, hook, Mock())
        order = Mock()
        bot._maybe_idle = order.idle  # Maxer and Rusher's spend burst
        bot._storages_full_now = order.full
        order.full.side_effect = [False, True]  # before the first raid, then after it
        bot._find_match_and_attack = Mock(return_value=None)  # a raid played
        self.assertIsNone(bot._run_loop(1, 0))
        self.assertEqual(bot._find_match_and_attack.call_count, 1)
        self.assertEqual([c[0] for c in order.mock_calls], ['idle', 'full', 'idle', 'full'])
        self.assertEqual(bot.finish_reason, 'storages full')

    def test_a_builder_base_run_stops_once_full(self):
        bot = make_bot()
        bot._stop_when_full = True
        bot._bb_attack_once = Mock(return_value=True)
        bot._storages_full_now = Mock(side_effect=[False, False, True])
        self.assertIsNone(bot._run_builder_base_loop(0))
        self.assertEqual(bot._bb_attack_once.call_count, 2)
        self.assertEqual(bot.finish_reason, 'storages full')

    @patch('app.core.bot.read_village_state')
    def test_the_idle_gate_leaves_full_storages_to_the_stop(self, state):
        bot = make_bot()
        bot._auto_upgrade_mode = 'maxer'
        bot._stop_when_full = True
        bot._emit_village_state = Mock()
        bot._reserve_builders = 0
        bot._gold_pinned = bot._elixir_pinned = True
        full = SimpleNamespace(storages_full=True, free_builders=0, builders=(0, 6), lab_idle=False,
                               gold_full=True, elixir_full=True, summary=lambda: 'full')
        state.return_value = full
        bot._maybe_auto_upgrade = Mock(return_value=None)
        bot._read_state_stable = Mock(return_value=full)
        bot._maybe_idle(None)
        bot._maybe_auto_upgrade.assert_called_with(force=True)  # the spend burst still goes first
        bot.stop_event.wait.assert_not_called()  # but no idling: the run ends instead

    @patch('app.core.bot.read_village_state')
    def test_the_spend_burst_goes_on_while_passes_start_something(self, state):
        full = SimpleNamespace(storages_full=True, free_builders=2, builders=(2, 6), lab_idle=False,
                               gold_full=True, elixir_full=True, summary=lambda: 'full')
        state.return_value = full
        for (started, passes) in (([True, True, False], 3), ([True] * 6, 5), ([False], 1)):
            with self.subTest(started=started):
                bot = make_bot()
                bot._auto_upgrade_mode = 'maxer'
                bot._stop_when_full = True
                bot._emit_village_state = Mock()
                bot._reserve_builders = 0
                bot._maybe_auto_upgrade = Mock(side_effect=started)
                bot._read_state_stable = Mock(return_value=full)
                bot._maybe_idle(None)
                self.assertEqual(bot._maybe_auto_upgrade.call_count, passes)


class EndlessTests(unittest.TestCase):
    def test_an_endless_builder_base_run_backs_off_instead_of_stopping(self):
        bot = make_bot()
        bot._bb_attack_once = Mock(side_effect=[False] * 4 + [InterruptedError('Stop')])
        with self.assertRaises(InterruptedError):
            bot._run_builder_base_loop(0)
        self.assertEqual(bot._bb_attack_once.call_count, 5)  # a fifth cycle after the back-off
        self.assertIn(call(_IDLE_RECHECK_SECONDS), bot.stop_event.wait.call_args_list)

    def test_endless_reaches_the_builder_base_but_not_a_multi_run(self):
        bot = make_bot()
        bot.window.find_window.return_value = True
        for name in ('_reset_loot_session', '_emit_loot_update', '_ensure_correct_village', '_run_builder_base_loop',
                     '_run_loop', '_multi_run_builder_base_after_session', '_switch_account_and_load_home'):
            setattr(bot, name, Mock())
        bot.start(5, 0, builder_base=True, stop_when_full=True)
        self.assertEqual(bot._run_builder_base_loop.call_args.args[0], 0)  # no time limit
        self.assertTrue(bot._stop_when_full)
        bot.start(1, 0, multi_run_players=[SimpleNamespace(name='a', enabled=True)])
        self.assertEqual(bot._run_loop.call_args.args[1], 60)  # a duration for each account


@unittest.skipIf(QApplication is None, 'needs PySide6')
class RunPageTests(QtTestCase):
    def setUp(self):
        super().setUp()
        self.controller = Mock()
        self.controller.is_running.return_value = False
        self.settings = self.temp_settings()

    def make_page(self):
        with patch('app.ui.qt.pages.run.QSettings', return_value=self.settings):
            return RunPage(self.controller, lambda name: None)

    @patch('app.ui.qt.pages.run.check_game_window_aspect_for_start', return_value=True)
    def test_endless_and_the_stop_in_the_builder_base(self, _aspect):
        page = self.make_page()
        page._village_group.button(1).click()  # Builder Base
        page._endless.setChecked(True)
        page._stop_when_full.setChecked(True)
        self.assertFalse(page._endless.isHidden())  # no longer Home Village only
        self.assertFalse(page._minutes_spin.isEnabled())
        page.start_bot()
        kw = self.controller.start.call_args.kwargs
        self.assertEqual((kw['minutes'], kw['builder_base'], kw['stop_when_full']), (0, True, True))
        page = self.make_page()  # the choices come back after a restart
        self.assertTrue(page._endless.isChecked() and page._stop_when_full.isChecked())

    def test_a_home_village_multi_run_keeps_its_duration(self):
        page = self.make_page()
        page._endless.setChecked(True)
        self.assertFalse(page._minutes_spin.isEnabled())
        page._multi_run.setChecked(True)
        self.assertTrue(page._minutes_spin.isEnabled())  # a duration for each account
        page._village_group.button(1).click()  # the Builder Base has no Multi-run
        self.assertFalse(page._minutes_spin.isEnabled())


if __name__ == '__main__':
    unittest.main()
