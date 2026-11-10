"""October 2026 Build panel: the readers on live 16:10 crops, and the gem-safety rules."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.config import Config
from app.core import build_panel as bp
from app.core.bot import Bot
from app.core.upgrade_menu import RESOURCE_DARK, RESOURCE_ELIXIR, RESOURCE_GOLD

FIXTURES = Path(__file__).parent / 'fixtures'


def canvas(*parts):
    """Live 1920x1200 crops (no player name in them) pasted back where they were taken."""
    frame = np.zeros((1200, 1920, 3), np.uint8)
    for (name, y, x) in parts:
        img = cv2.imread(str(FIXTURES / f'{name}.jpg'))
        frame[y:y + img.shape[0], x:x + img.shape[1]] = img
    Config().set_target_size_from_frame(frame)
    return frame


def costed(rows):
    return {(r.label, r.cost, r.resource) for r in rows if r.cost}


class ReaderTests(unittest.TestCase):
    def test_home_village_cards(self):
        frame = canvas(('panel_hv_buildings', 0, 1280))
        self.assertEqual(bp.panel_tab(_vision(), frame), bp.TAB_BUILDINGS)
        got = costed(bp.parse_cards(_vision(), frame))
        self.assertEqual({(c, r) for (_l, c, r) in got},
                         {(46800, RESOURCE_DARK), (2480000, RESOURCE_ELIXIR), (1120000, RESOURCE_GOLD)})
        # "Scattershot New 3 200 000" places a new building: never a candidate
        self.assertNotIn(3200000, {c for (_l, c, _r) in got})

    def test_lab_cards_and_tab(self):
        frame = canvas(('panel_hv_lab', 0, 1280))
        self.assertEqual(bp.panel_tab(_vision(), frame), bp.TAB_ARMY)
        got = costed(bp.parse_cards(_vision(), frame))
        self.assertIn(10000, {c for (_l, c, _r) in got})  # Skeleton Spell, "10 000" first read "to ooo"
        self.assertEqual(len(got), 4)  # the locked "Upgrade Laboratory to Level 11" rows have no cost
        (x, y) = bp.find_tab(_vision(), frame, 1)
        self.assertTrue(1480 < x < 1570 and y > 1100)

    def test_builder_base_red_cost_is_not_affordable(self):
        frame = canvas(('panel_bb_buildings', 0, 1280))
        got = costed(bp.parse_cards(_vision(), frame))
        self.assertNotIn(2320000, {c for (_l, c, _r) in got})  # Battle Machine, red
        self.assertIn((8000, RESOURCE_GOLD), {(c, r) for (_l, c, r) in got})  # the paler Builder Base gold
        (x, _y) = bp.find_tab(_vision(), frame, 1)
        self.assertTrue(1700 < x < 1820)  # two tabs only in the Builder Base

    def test_chips_and_the_goblin(self):
        (builders, lab) = bp.read_chips(_vision(), Config(), canvas(('chips_hv_builders_busy_lab_goblin', 860, 1640)))
        self.assertEqual((builders.free, builders.total, builders.regular_free), (0, 6, 0))
        self.assertEqual((lab.free, lab.goblin, lab.regular_free), (1, True, 0))  # only the gem-paid researcher
        (builders, lab) = bp.read_chips(_vision(), Config(), canvas(('chips_hv_goblins', 860, 1640)))
        self.assertEqual((builders.free, builders.goblin, builders.regular_free), (1, True, 0))
        (builders, lab) = bp.read_chips(_vision(), Config(), canvas(('chips_bb', 860, 1640)))
        self.assertEqual(((builders.free, builders.total), (lab.free, lab.total)), ((0, 3), (0, 1)))

    def test_upgrade_dialog_resource_button(self):
        frame = canvas(('dialog_hv_title', 0, 230), ('dialog_hv_bottom', 730, 150))
        self.assertTrue(bp.dialog_title_ok(_vision(), frame))
        (x, y) = bp.find_confirm_button(_vision(), frame, RESOURCE_ELIXIR)
        self.assertTrue(1250 < x < 1530 and 970 < y < 1100)  # the elixir Confirm, not the grey Hammer one
        self.assertIsNone(bp.find_confirm_button(_vision(), frame, RESOURCE_GOLD))
        self.assertFalse(bp.gem_prompt_visible(_vision(), frame))

    def test_gem_prompt(self):
        frame = canvas(('gem_prompt', 330, 520))
        self.assertTrue(bp.gem_prompt_visible(_vision(), frame))
        self.assertIsNone(bp.find_confirm_button(_vision(), frame))  # its green button carries the gem
        self.assertFalse(bp.dialog_title_ok(_vision(), frame))
        self.assertIsNotNone(bp.find_close(_vision(), frame))

    def test_wall_upgrade_button_prefers_elixir(self):
        (point, resource) = bp.wall_upgrade_button(_vision(), canvas(('wall_grid_bb', 680, 380)))
        self.assertEqual(resource, RESOURCE_ELIXIR)
        self.assertTrue(600 < point[0] < 680)


def _vision():
    from app.services.vision import VisionService
    return VisionService


class GemSafetyTests(unittest.TestCase):
    def setUp(self):
        self.stop = Mock()
        self.stop.wait.return_value = False
        self.window = Mock()
        self.window.screenshot.return_value = np.zeros((1200, 1920, 3), np.uint8)
        self.input = Mock()
        self.up = bp.BuildPanelUpgrader(self.window, self.input, Mock(), Mock(), self.stop)

    @patch.object(bp, 'read_chips', return_value=(bp.Chip(1, 6, True), bp.Chip(1, 2, True)))
    def test_goblin_only_never_opens_the_panel(self, _chips):
        note = self.up.run_pass('maxer')
        self.assertTrue(note.startswith('nothing free'), note)
        self.input.click.assert_not_called()

    @patch.object(bp, 'find_close', return_value=(900, 100))
    @patch.object(bp, 'find_confirm_button', return_value=(500, 600))
    @patch.object(bp, 'dialog_title_ok', return_value=True)
    @patch.object(bp, 'gem_prompt_visible')
    def test_gem_prompt_after_confirm_is_closed(self, gem, _title, _confirm, close):
        gem.side_effect = [False] + [True] * 3
        close.side_effect = [(900, 100), None]
        note = self.up.confirm(RESOURCE_ELIXIR, 'Blacksmith')
        self.assertTrue(note.startswith('gem prompt closed'), note)
        self.assertEqual([c.args[:2] for c in self.input.click.call_args_list], [(500, 600), (900, 100)])

    @patch.object(bp, 'find_close', side_effect=[(900, 100), None])
    @patch.object(bp, 'find_confirm_button', return_value=None)
    @patch.object(bp, 'dialog_title_ok', return_value=True)
    @patch.object(bp, 'gem_prompt_visible', return_value=False)
    def test_no_resource_button_means_no_tap_but_the_close(self, *_mocks):
        note = self.up.confirm(RESOURCE_GOLD, 'Wall')
        self.assertTrue(note.startswith('no Confirm button'), note)
        self.assertEqual([c.args[:2] for c in self.input.click.call_args_list], [(900, 100)])


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
    bot.config = SimpleNamespace(aspect_key='16_10', width=1920, height=1200, scale_scalar=lambda v: int(v * 0.75))
    bot._update_config_size = Mock()
    return bot


class BotFlowTests(unittest.TestCase):
    def test_find_a_match_is_only_looked_for_in_the_battle_card(self):
        bot = make_bot()
        bot._find_template_once = Mock(return_value=(None, None))
        bot._wait_for_attack_with_nudge = Mock(return_value=(None, None))
        self.assertEqual(bot._find_match_and_attack(1), 'no_attack')
        (x, _y, w, _h) = bot._find_template_once.call_args.kwargs['region']
        self.assertLessEqual(x + w, 0.29 * 1920)  # the Ranked Battle card starts there

    @patch('app.core.bot.bb_strategy.alive', return_value=True)
    @patch('app.core.bot.bb_strategy.identify', side_effect=['bomber', 'pekka', 'pekka'])
    @patch('app.core.bot.AttackStrategy')
    @patch('app.core.bot.VisionService.find_all_template_centers', return_value=[(272, 1150), (430, 1150), (570, 1150), (710, 1150)])
    def test_bb_plays_the_machine_then_each_troop_in_its_order(self, _swaps, strategy, _identify, _alive):
        bot = make_bot()
        bot.vision.find_all_template_centers.return_value = []  # no other card than the swap buttons'
        bot.stop_event.wait.return_value = False
        bot.vision.find_template.side_effect = lambda f, name, **kw: (250, 1100) if name == 'battlemachine.png' else (None, None)
        strategy.return_value._even_diamond_top_perimeter_points.return_value = [(600, 300), (960, 120), (1320, 300)]
        schedule = bot._deploy_bb_army(np.zeros((1200, 1920, 3), np.uint8))
        lift = int(round(91 * 1200 / 1600))
        cards = [c.args[:2] for c in bot.input.click.call_args_list][0::2]
        # the machine card (its swap button beside it is not a troop), then the P.E.K.K.As, then the Bomber
        self.assertEqual(cards, [(250, 1100), (570, 1150 - lift), (710, 1150 - lift), (430, 1150 - lift)])
        points = [c.args[:2] for c in bot.input.click.call_args_list][1::2]
        (ex, ey) = points[0]
        self.assertTrue(all(abs(x - ex) <= 30 and abs(y - ey) <= 30 for (x, y) in points))  # one entry point
        self.assertEqual([c for (_due, c, _every) in schedule], cards)  # every card gets its ability tap


    @patch('app.core.bot.wall_upgrade_button', return_value=((638, 1041), RESOURCE_ELIXIR))
    def test_selected_wall_goes_through_the_gem_safe_confirm(self, _button):
        bot = make_bot()
        bot._panel_upgrader = Mock()
        bot._panel_upgrader.confirm.return_value = 'started'
        self.assertTrue(bot._buy_selected_wall())
        self.assertEqual(bot.input.click.call_args.args[:2], (638, 1041))
        bot._panel_upgrader.confirm.assert_called_once_with(RESOURCE_ELIXIR, 'Wall')
        bot._panel_upgrader.confirm.return_value = 'gem prompt closed, not started:'
        self.assertIsNone(bot._buy_selected_wall())


if __name__ == '__main__':
    unittest.main()
