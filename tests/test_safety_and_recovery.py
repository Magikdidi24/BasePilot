"""Fixes from a read of the whole code: halls, full storages, reconnect dialogs, gem-safe
popups, failed-start cooldown, and error guards that keep a run going."""
import ast
import inspect
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.config import Config
from app.core import build_panel as bp
from app.core.bot import Bot, reconnect_button
from app.core.upgrade_menu import UpgradeRow, is_town_hall_row
from app.core.village_state import storages_full
from app.services.vision import VisionService
from tests.helpers import FIXTURES, WAYDROID, canvas


def make_bot():
    bot = Bot.__new__(Bot)
    bot.stop_event = Mock()
    bot.stop_event.is_set.return_value = False
    bot.stop_event.wait.return_value = False
    bot.window = Mock()
    bot.window.screenshot.return_value = np.zeros((1200, 1920, 3), np.uint8)
    bot.input = Mock()
    bot.vision = Mock()
    bot.vision.find_template.return_value = (None, None)
    bot.config = SimpleNamespace(aspect_key='16_10', width=1920, height=1200, scale_scalar=lambda v: int(v * 0.75),
                                 get_point=lambda k: (1012, 1177), scale_point=lambda p, size=None: (p[0] * 0.75, p[1] * 0.75))
    bot._update_config_size = Mock()
    return bot


class HallTests(unittest.TestCase):
    def test_halls_and_their_short_reads(self):
        for label in ('Town Hall', 'Town', 'Towm', 'TownMall x2', 'Builder Hall', 'Buider Hall', 'Builder'):
            self.assertTrue(is_town_hall_row(SimpleNamespace(label=label)), label)
        for label in ('Tower', 'Tornado Trap', 'Archer Tower', 'Hero Hall', 'Builder Barracks', "Builder's Hut", 'Gold Mine'):
            self.assertFalse(is_town_hall_row(SimpleNamespace(label=label)), label)


class StorageTests(unittest.TestCase):
    def test_full_means_the_left_end_of_the_bar_is_coloured(self):
        chips = ('chips_hv_goblins.jpg', 1640, 860)  # brings the Build button: the October home screen
        self.assertEqual(storages_full(canvas(('hud_gold_full.jpg', 1480, 0), chips, size=WAYDROID)), (True, False))  # 14.0M gold, 12.7M elixir
        self.assertEqual(storages_full(canvas(('hud_not_full.jpg', 1480, 0), chips, size=WAYDROID)), (False, False))  # 10.9M, 12.5M
        # no Build button (a panel or a dialog is up): unknown, never "full"
        self.assertEqual(storages_full(canvas(('hud_gold_full.jpg', 1480, 0), size=WAYDROID)), (False, False))

    def test_grass_behind_an_empty_bar_end_is_not_gold(self):
        frame = canvas(('hud_not_full.jpg', 1480, 0), ('chips_hv_goblins.jpg', 1640, 860), size=WAYDROID)
        grass = cv2.cvtColor(np.full((1, 1, 3), (35, 120, 160), np.uint8), cv2.COLOR_HSV2BGR)[0, 0]
        frame[40:64, 1524:1548] = grass  # the translucent empty end of the gold bar, over the village
        self.assertEqual(storages_full(frame), (False, False))


class SixteenByNineTests(unittest.TestCase):
    def test_chips_at_16_9(self):
        # the 16:10 chips crop shrunk by 0.9 (the HUD scales with the height) at 1920x1080, right-aligned
        crop = cv2.imread(str(FIXTURES / 'chips_hv_goblins.jpg'))
        small = cv2.resize(crop, None, fx=0.9, fy=0.9, interpolation=cv2.INTER_AREA)
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[1080 - small.shape[0]:, 1920 - small.shape[1]:] = small
        Config().set_target_size_from_frame(frame)
        (builders, lab) = bp.read_chips(VisionService, Config(), frame)
        self.assertEqual((builders.free, builders.total, builders.goblin), (1, 6, True))
        self.assertEqual((lab.free, lab.total), (1, 2))


class WallResourceTests(unittest.TestCase):
    def test_walls_pay_only_with_the_resource_that_triggered_the_pass(self):
        from app.core.upgrade_menu import RESOURCE_ELIXIR, RESOURCE_GOLD
        frame = canvas(('wall_grid_bb.jpg', 380, 680), size=WAYDROID)
        self.assertEqual(bp.wall_upgrade_button(VisionService, frame, (RESOURCE_GOLD,))[1], RESOURCE_GOLD)
        self.assertEqual(bp.wall_upgrade_button(VisionService, frame)[1], RESOURCE_ELIXIR)
        self.assertIsNone(bp.wall_upgrade_button(VisionService, frame, ()))

    @patch('app.core.bot.storages_full', return_value=(True, False))
    def test_the_trigger_names_its_resources(self, _full):
        from app.core.upgrade_menu import RESOURCE_ELIXIR, RESOURCE_GOLD
        bot = make_bot()
        bot._wall_upgrade_threshold = 0
        self.assertEqual(bot._should_upgrade_walls(), {RESOURCE_GOLD})  # gold full: never elixir
        bot._wall_upgrade_threshold = 3000000
        bot._read_hud_triplet_stable = Mock(return_value=(2000000, 9000000, 0))
        self.assertEqual(bot._should_upgrade_walls(), {RESOURCE_ELIXIR})


class ReconnectTests(unittest.TestCase):
    @patch('app.core.bot.time.monotonic', side_effect=[1000.0, 1200.0] + [1300.0] * 50)
    @patch('app.core.bot.reconnect_button', side_effect=[(639, 622), (639, 622)] + [None] * 50)
    def test_reconnect_comes_first_and_waits_the_whole_grace_once(self, _button, _clock):
        bot = make_bot()
        bot._battle_rewards = Mock(handle=Mock(return_value=False))
        bot._live_battle_button = Mock(return_value=(100, 900))  # End Battle still matches under the dim
        bot._home_hud_visible = Mock(return_value=False)
        bot._home_screen_recovery()
        self.assertEqual(bot.input.click.call_args_list[0].args[:2], (639, 622))
        self.assertEqual(bot.stop_event.wait.call_args_list[0].args[0], 180)  # the grace, in one go

    def test_reconnect_buttons_of_both_dialogs(self):
        for (name, word_x) in (('dialog_connection_lost', 640), ('dialog_anyone_there', 655)):
            (x, y) = reconnect_button(VisionService, canvas((f'{name}.jpg', 520, 430), size=WAYDROID))
            self.assertTrue(abs(x - word_x) < 40 and 600 < y < 640, (name, x, y))

    def test_no_reconnect_button_elsewhere(self):
        self.assertIsNone(reconnect_button(VisionService, canvas(('gem_prompt.jpg', 520, 330), size=WAYDROID)))
        self.assertIsNone(reconnect_button(VisionService, canvas(('dialog_hv_title.jpg', 230, 0), ('dialog_hv_bottom.jpg', 150, 730), size=WAYDROID)))


class PopupTests(unittest.TestCase):
    @patch('app.core.bot.gem_prompt_visible', return_value=True)
    def test_never_the_okay_of_a_popup_with_a_gem(self, _gem):
        bot = make_bot()
        bot.vision.find_template.side_effect = lambda f, name, **kw: (700, 500) if name in ('okay.png', 'closex.png') else (None, None)
        self.assertTrue(bot._dismiss_okay_or_exit_on_frame(bot.window.screenshot()))
        looked = [c.args[1] for c in bot.vision.find_template.call_args_list]
        self.assertNotIn('okay.png', looked)
        self.assertIn('closex.png', looked)


class CooldownTests(unittest.TestCase):
    def test_a_card_that_failed_to_start_is_left_alone(self):
        up = bp.BuildPanelUpgrader(Mock(), Mock(), Mock(), Mock(), Mock())
        up._frame = Mock(return_value=np.zeros((1200, 1920, 3), np.uint8))
        up._open = Mock(return_value=True)
        up._close_panel = Mock()
        up._start = Mock(return_value='no Confirm button, not started:')
        row = UpgradeRow('Blacksmith', '', 2480000, 'elixir', True, (1480, 700))
        policy = bp.UpgradePolicy(reserve_builders=0)
        with patch.object(bp, 'parse_cards', return_value=[row]):
            self.assertIn('not started', up._one(bp.TAB_BUILDINGS, (10 ** 8, 10 ** 8, 10 ** 6), 1, policy, 'maxer'))
            self.assertEqual(up._one(bp.TAB_BUILDINGS, (10 ** 8, 10 ** 8, 10 ** 6), 1, policy, 'maxer'), 'upgrade: nothing affordable')
        self.assertEqual(up._start.call_count, 1)


class GuardTests(unittest.TestCase):
    def test_start_never_shadows_a_method(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(Bot.start)))
        assigned = {t.attr for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets
                    if isinstance(t, ast.Attribute) and getattr(t.value, 'id', '') == 'self'}
        methods = {name for name, v in vars(Bot).items() if callable(v)}
        self.assertFalse(assigned & methods)  # e.g. self._upgrade_walls = bool(...) broke the wall pass

    def test_builder_base_home_ends_recovery_in_a_builder_base_run(self):
        bot = make_bot()
        bot._find_home_village_builder = Mock(return_value=(None, None))
        bot.vision.find_template.side_effect = lambda f, name, **kw: (1763, 934) if name == 'mbuilder.png' else (None, None)
        frame = bot.window.screenshot()
        self.assertFalse(bot._home_hud_visible(frame))  # a Home Village run: wrong village
        bot._builder_base = True
        self.assertTrue(bot._home_hud_visible(frame))  # a Builder Base run: home

    def test_builder_base_errors_and_missed_ends_go_through_recovery(self):
        bot = make_bot()
        bot._recover_safely = Mock()
        bot._maybe_auto_upgrade = Mock()
        bot._bb_attack_once = Mock(side_effect=[RuntimeError('reward overlay'), False, False, False])
        bot._run_builder_base_loop(3600)
        self.assertEqual(bot._recover_safely.call_count, 4)  # after every cycle, including the failed one
        self.assertEqual(bot._bb_attack_once.call_count, 4)  # 4 in a row without a battle: stop, no crash

    def test_an_error_in_a_farm_cycle_is_a_cycle_without_a_battle(self):
        bot = make_bot()
        for hook in ('_maybe_clan_assist', '_maybe_upgrade_walls', '_maybe_auto_upgrade', '_maybe_idle',
                     '_recover_safely', '_multi_run_collect_home_village_resources', '_return_home'):
            setattr(bot, hook, Mock())
        bot._find_match_and_attack = Mock(side_effect=RuntimeError('boom'))
        self.assertIsNone(bot._run_loop(1, 3600))
        self.assertEqual(bot._find_match_and_attack.call_count, 4)  # the usual failure back-off, then stop

    def test_multi_run_skips_an_account_it_cannot_switch_to(self):
        bot = make_bot()
        bot.window.find_window.return_value = True
        for name in ('_reset_loot_session', '_emit_loot_update', '_ensure_correct_village', '_run_loop',
                     '_multi_run_builder_base_after_session', '_recover_safely'):
            setattr(bot, name, Mock())
        bot._switch_account_and_load_home = Mock(side_effect=[RuntimeError('name not read'), None])
        players = [SimpleNamespace(name='a', enabled=True), SimpleNamespace(name='b', enabled=True)]
        bot.start(1, 10, multi_run_players=players)
        self.assertEqual(bot._run_loop.call_count, 1)  # the second account still ran


if __name__ == '__main__':
    unittest.main()
