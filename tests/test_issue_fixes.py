"""Regression tests for the October 2026 UI fixes (efebolukbasi/BasePilot#6-#9)."""
import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from app.core.bot import Bot
from app.core.upgrader import UpgradeAdvisor
from app.services.window import WindowService, bgra_dib_to_bgr

FRAME = np.zeros((731, 1299, 3), dtype=np.uint8)


def make_bot():
    bot = Bot.__new__(Bot)
    bot.stop_event = Mock()
    bot.stop_event.is_set.return_value = False
    bot.stop_event.wait.return_value = False
    bot.window = Mock()
    bot.window.screenshot.return_value = FRAME
    bot.input = Mock()
    bot.vision = Mock()
    bot.vision.find_template.return_value = (None, None)
    bot.vision.find_control.return_value = (None, None)
    bot.config = SimpleNamespace(aspect_key='16_9', width=1299, height=731, get_point=lambda k: (685, 715))
    bot._update_config_size = Mock()
    bot._battle_rewards = Mock()
    bot._battle_rewards.handle.return_value = False
    return bot


class AttackCycleTests(unittest.TestCase):
    def test_home_button_never_found_is_a_failed_cycle(self):
        bot = make_bot()
        bot._find_template_once = Mock(return_value=(None, None))
        bot._wait_for_attack_with_nudge = Mock(return_value=(None, None))
        self.assertEqual(bot._find_match_and_attack(1), 'no_attack')

    def test_battle_screen_never_loaded_skips_the_strategy(self):
        bot = make_bot()
        bot._find_template_once = Mock(return_value=(400, 600))  # battle-selection screen already open
        bot._wait_for_image = Mock(return_value=(900, 650))      # attack2
        bot._wait_for_any_image = Mock(return_value=(None, None))
        bot._get_strategy = Mock()
        self.assertEqual(bot._find_match_and_attack(1), 'no_attack')
        bot._get_strategy.assert_not_called()

    def test_battle_that_ended_by_itself_is_not_waited_on(self):
        bot = make_bot()
        bot._wait_for_any_image = Mock(return_value=(640, 650))  # results screen
        bot._search_region_for_template = Mock(return_value=None)
        bot._wait_for_battle_end(False)
        bot.input.click.assert_not_called()
        self.assertEqual(bot._wait_for_any_image.call_args.args[0], ('endbattle.png', 'returnhome.png', 'chestclaim.png'))


class LiveBattleTests(unittest.TestCase):
    def test_attack_wait_never_nudges_on_a_battle_showing_end_battle(self):
        bot = make_bot()
        bot.vision.find_template.side_effect = lambda f, name, **kw: (90, 600) if name == 'endbattle.png' else (None, None)
        bot._dismiss_okay_or_exit_on_frame = Mock(return_value=False)
        bot._nudge_view_to_reveal_attack = Mock()
        self.assertEqual(bot._wait_for_attack_with_nudge(), (None, None))
        bot._nudge_view_to_reveal_attack.assert_not_called()


class WallTests(unittest.TestCase):
    def test_cleanup_never_clicks_okay(self):
        bot = make_bot()
        bot.vision.find_template.side_effect = lambda f, name, **kw: (50, 50) if name == 'okay.png' else (None, None)
        with patch('app.core.bot.get_template_path') as path:
            path.return_value.exists.return_value = False
            bot._deselect_wall_ui()
        self.assertNotIn('okay.png', [c.args[1] for c in bot.vision.find_template.call_args_list])
        self.assertEqual(bot.input.click.call_count, 1)  # only the empty-ground tap

    def test_failed_pass_backs_off(self):
        bot = make_bot()
        bot._should_upgrade_walls = Mock(return_value=True)
        bot._loot_snapshot_before_attack = Mock()
        bot._upgrade_walls = Mock(return_value=None)
        bot._deselect_wall_ui = Mock()
        bot._maybe_upgrade_walls(True)
        self.assertEqual(bot._upgrade_walls.call_count, 1)  # no second pass after a failure
        bot._maybe_upgrade_walls(True)
        self.assertEqual(bot._should_upgrade_walls.call_count, 1)  # backed off: not even re-checked

    def test_wall_card_is_read_in_the_build_panel(self):
        bot = make_bot()
        bot.vision.find_words_ocr.return_value = [SimpleNamespace(text='Wall', top=500, height=20, center=(1050, 510))]
        (_frame, pt) = bot._find_wall_row_once()
        self.assertEqual(pt, (1050, 510))
        region = bot.vision.find_words_ocr.call_args.args[1]
        self.assertGreaterEqual(region[0], int(1299 * 0.7))  # right-hand panel, not the old top-center popup


class IdleGateTests(unittest.TestCase):
    @patch('app.core.bot.read_village_state')
    def test_full_storages_idle_until_a_builder_frees_up(self, state):
        bot = make_bot()
        bot._auto_upgrade_mode = 'maxer'
        bot._emit_village_state = Mock()
        bot._maybe_auto_upgrade = Mock(return_value=None)
        bot._home_screen_recovery = Mock()
        bot._maybe_clan_assist = Mock()
        bot._maybe_upgrade_walls = Mock()
        bot._walls_enabled = True
        bot._reserve_builders = 0
        bot._gold_pinned = bot._elixir_pinned = True
        full = SimpleNamespace(storages_full=True, free_builders=0, builders=(0, 6), lab_idle=False,
                               gold_full=True, elixir_full=True, summary=lambda: 'full')
        freed = SimpleNamespace(storages_full=True, free_builders=1, builders=(1, 6), lab_idle=False,
                                gold_full=True, elixir_full=True, summary=lambda: 'a builder free')
        state.return_value = full
        bot._read_state_stable = Mock(side_effect=[full, freed])
        bot._maybe_idle(None)
        self.assertEqual(bot._read_state_stable.call_count, 2)  # idled one wake, then left on the free builder
        bot._maybe_auto_upgrade.assert_called_with(force=True)  # the wake spends on it right away
        bot._maybe_upgrade_walls.assert_called_with(True)  # and tries the walls, the reserved builder's job
        self.assertEqual(bot._auto_upgrade_last_scan, 0)


class AutoUpgradeGateTests(unittest.TestCase):
    def test_scan_refuses_the_october_build_panel(self):
        advisor = UpgradeAdvisor(Mock(), Mock(), Mock(), Mock(), Mock())
        advisor._frame = Mock(return_value=FRAME)
        advisor.vision.find_control.return_value = (100, 650)  # Battle
        advisor.vision.find_template.side_effect = lambda f, name, **kw: (1200, 650) if name == 'build.png' else (None, None)
        self.assertIsNone(advisor.scan())
        self.assertFalse(advisor._open_builder_popup())
        advisor.input.click.assert_not_called()


class CoarseToFineTests(unittest.TestCase):
    def test_same_spot_and_score_as_a_full_match(self):
        import cv2
        from app.services.vision import VisionService
        frame = cv2.resize(cv2.imread('docs/basepilot-screenshot.png'), (1920, 1080), interpolation=cv2.INTER_CUBIC)
        for name in ('returnhome.png', 'attack2.png', 'builder.png', 'savedrecipes.png'):
            tpl = cv2.imread(f'templates/16_9/{name}')
            tpl = cv2.resize(tpl, (round(tpl.shape[1] * .75), round(tpl.shape[0] * .75)), interpolation=cv2.INTER_AREA)
            frame[700:700 + tpl.shape[0], 900:900 + tpl.shape[1]] = tpl
            (_, exact, _, loc) = cv2.minMaxLoc(cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED))
            (score, at) = VisionService._match_best(frame, tpl)
            with self.subTest(name=name):
                self.assertEqual(at, loc)
                self.assertAlmostEqual(score, exact, places=3)
                self.assertEqual(at, (900, 700))


class CaptureConversionTests(unittest.TestCase):
    def test_one_copy_conversion_matches_the_old_pil_path(self):
        import cv2
        from PIL import Image
        (w, h) = (37, 23)
        raw = (ctypes.c_ubyte * (w * h * 4))(*np.random.default_rng(1).integers(0, 256, w * h * 4).tolist())
        old = cv2.cvtColor(np.array(Image.frombuffer('RGBA', (w, h), bytes(raw), 'raw', 'BGRA', 0, 1)), cv2.COLOR_RGBA2BGR)
        self.assertTrue(np.array_equal(bgra_dib_to_bgr(raw, w, h), old))


class WindowTests(unittest.TestCase):
    def dead_window(self):
        ws = WindowService.__new__(WindowService)
        ws.hwnd = 1234
        ws.user32 = Mock()
        ws.user32.IsWindow.return_value = False
        ws.find_window = Mock(return_value=False)
        ws._resolve_hwnd = Mock(return_value=0)
        return ws

    @patch('app.services.window.load_window_selection', return_value=SimpleNamespace(is_set=lambda: False))
    def test_dead_handle_is_re_resolved_but_not_on_every_frame(self, _sel):
        ws = self.dead_window()
        self.assertFalse(ws._ensure_hwnd())
        self.assertFalse(ws._ensure_hwnd())
        ws.find_window.assert_called_once()
        ws.user32.IsWindow.return_value = True
        self.assertTrue(ws._ensure_hwnd())

    @patch('app.services.window.load_window_selection', return_value=SimpleNamespace(is_set=lambda: True))
    def test_pinned_window_never_falls_back_to_another_client(self, _sel):
        ws = self.dead_window()
        self.assertFalse(ws._ensure_hwnd())
        ws._resolve_hwnd.assert_called_once()
        ws.find_window.assert_not_called()  # find_window would auto-detect any Clash window



class LoggerTests(unittest.TestCase):
    def test_module_loggers_share_one_rotating_file_handler(self):
        import logging
        import tempfile
        from logging.handlers import RotatingFileHandler
        from app.utils.logger import setup_logger
        path = tempfile.mkstemp(suffix='.log')[1]
        a = setup_logger('ShareTestA', log_file=path)
        b = setup_logger('ShareTestB', log_file=path)
        fa = [h for h in a.handlers if isinstance(h, RotatingFileHandler)]
        fb = [h for h in b.handlers if isinstance(h, RotatingFileHandler)]
        self.assertEqual(len(fa), 1)
        self.assertIs(fa[0], fb[0])  # one open file: rollover can rename it on Windows

if __name__ == '__main__':
    unittest.main()
