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

    @patch('app.core.bot.VisionService.upgrade_cost_redness_by_resource_icons')
    def test_confirm_waits_for_the_late_okay_and_reports_success(self, costs):
        bot = make_bot()
        slot = SimpleNamespace(redness=0.0, cost_roi_xywh=(1, 2, 3, 4), center=(500, 600))
        costs.return_value = SimpleNamespace(elixir=slot, gold=SimpleNamespace(redness=1.0, cost_roi_xywh=None, center=None))
        bot._wall_batch_state = Mock(return_value=(FRAME, object()))
        okay = iter([(None, None), (700, 500)])
        bot.vision.find_template.side_effect = lambda f, name, **kw: next(okay) if name == 'okay.png' else (None, None)
        self.assertTrue(bot._upgrade_walls_pick_resource_and_okay())
        self.assertEqual([c.args[:2] for c in bot.input.click.call_args_list], [(500, 600), (700, 500)])

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

    def test_add_remove_band_sits_above_the_price_cards(self):
        bot = make_bot()
        frame = np.zeros((900, 1600, 3), dtype=np.uint8)
        cost = lambda x: SimpleNamespace(cost_roi_xywh=(x, 728, 100, 22))
        (x, y, w, h) = bot._wall_button_strip_roi(frame, SimpleNamespace(gold=cost(440), elixir=cost(615)))
        self.assertEqual(y + h, 728)            # never the price row (a hit there is a purchase click)
        self.assertGreater(y, 540)              # nor the 'Wall (Lv N) xK' title above the buttons
        self.assertTrue(x <= 430 and x + w >= 735)  # both buttons of the live October frame

    def test_wall_card_is_read_in_the_build_panel(self):
        bot = make_bot()
        bot.vision.find_words_ocr.return_value = [SimpleNamespace(text='Wall', top=500, height=20, center=(1050, 510))]
        (_frame, pt) = bot._find_wall_row_once()
        self.assertEqual(pt, (1050, 510))
        region = bot.vision.find_words_ocr.call_args.args[1]
        self.assertGreaterEqual(region[0], int(1299 * 0.7))  # right-hand panel, not the old top-center popup


class IdleGateTests(unittest.TestCase):
    @patch('app.core.bot.read_village_state')
    def test_no_idling_on_the_october_hud(self, state):
        bot = make_bot()
        bot._auto_upgrade_mode = 'maxer'
        bot._emit_village_state = Mock()
        state.return_value = SimpleNamespace(storages_full=True, free_builders=None, gold_full=True, elixir_full=True)
        bot.vision.find_template.side_effect = lambda f, name, **kw: (1200, 650) if name == 'build.png' else (None, None)
        self.assertIsNone(bot._maybe_idle(None))
        bot.stop_event.wait.assert_not_called()  # returned at once instead of idling


class AutoUpgradeGateTests(unittest.TestCase):
    def test_scan_refuses_the_october_build_panel(self):
        advisor = UpgradeAdvisor(Mock(), Mock(), Mock(), Mock(), Mock())
        advisor._frame = Mock(return_value=FRAME)
        advisor.vision.find_control.return_value = (100, 650)  # Battle
        advisor.vision.find_template.side_effect = lambda f, name, **kw: (1200, 650) if name == 'build.png' else (None, None)
        self.assertIsNone(advisor.scan())
        self.assertFalse(advisor._open_builder_popup())
        advisor.input.click.assert_not_called()


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


if __name__ == '__main__':
    unittest.main()
