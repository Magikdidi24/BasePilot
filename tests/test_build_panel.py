"""October 2026 Build panel: the readers on live 16:10 crops, and the gem-safety rules."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from app.config import Config
from app.core import build_panel as bp
from app.core import upgrade_menu
from app.core.bot import Bot
from app.core.upgrade_menu import RESOURCE_DARK, RESOURCE_ELIXIR, RESOURCE_GOLD, UpgradeRow
from app.core.upgrade_policy import UpgradePolicy
from tests.helpers import WAYDROID, bare_bot, canvas


def costed(rows):
    return {(r.label, r.cost, r.resource) for r in rows if r.cost}


class ReaderTests(unittest.TestCase):
    def test_home_village_cards(self):
        frame = canvas(('panel_hv_buildings.jpg', 1280, 0), size=WAYDROID)
        self.assertEqual(bp.panel_tab(_vision(), frame), bp.TAB_BUILDINGS)
        got = costed(bp.parse_cards(_vision(), frame))
        self.assertEqual({(c, r) for (_l, c, r) in got},
                         {(46800, RESOURCE_DARK), (2480000, RESOURCE_ELIXIR), (1120000, RESOURCE_GOLD)})
        # "Scattershot New 3 200 000" places a new building: never a candidate
        self.assertNotIn(3200000, {c for (_l, c, _r) in got})

    def test_lab_cards_and_tab(self):
        frame = canvas(('panel_hv_lab.jpg', 1280, 0), size=WAYDROID)
        self.assertEqual(bp.panel_tab(_vision(), frame), bp.TAB_ARMY)
        got = costed(bp.parse_cards(_vision(), frame))
        self.assertIn(10000, {c for (_l, c, _r) in got})  # Skeleton Spell, "10 000" first read "to ooo"
        self.assertEqual(len(got), 4)  # the locked "Upgrade Laboratory to Level 11" rows have no cost
        (x, y) = bp.find_tab(_vision(), frame, 1)
        self.assertTrue(1480 < x < 1570 and y > 1100)

    def test_builder_base_red_cost_is_not_affordable(self):
        frame = canvas(('panel_bb_buildings.jpg', 1280, 0), size=WAYDROID)
        got = costed(bp.parse_cards(_vision(), frame))
        self.assertNotIn(2320000, {c for (_l, c, _r) in got})  # Battle Machine, red
        self.assertIn((8000, RESOURCE_GOLD), {(c, r) for (_l, c, r) in got})  # the paler Builder Base gold
        (x, _y) = bp.find_tab(_vision(), frame, 1)
        self.assertTrue(1700 < x < 1820)  # two tabs only in the Builder Base

    def test_chips_and_the_goblin(self):
        (builders, lab) = bp.read_chips(_vision(), Config(), canvas(('chips_hv_builders_busy_lab_goblin.jpg', 1640, 860), size=WAYDROID))
        self.assertEqual((builders.free, builders.total, builders.regular_free), (0, 6, 0))
        self.assertEqual((lab.free, lab.goblin, lab.regular_free), (1, True, 0))  # only the gem-paid researcher
        (builders, lab) = bp.read_chips(_vision(), Config(), canvas(('chips_hv_goblins.jpg', 1640, 860), size=WAYDROID))
        self.assertEqual((builders.free, builders.goblin, builders.regular_free), (1, True, 0))
        (builders, lab) = bp.read_chips(_vision(), Config(), canvas(('chips_bb.jpg', 1640, 860), size=WAYDROID))
        self.assertEqual(((builders.free, builders.total), (lab.free, lab.total)), ((0, 3), (0, 1)))

    def test_the_chip_reader_crops_the_box_read_chips_anchors(self):
        # the box went through frame fractions and int() back: the builders' text 27 px tall
        # instead of 28 at this size and spot
        frame = np.zeros((767, 1227, 3), np.uint8)
        vision = Mock(**{'find_template.return_value': (1100, 700)})
        crops = []
        with (patch.object(upgrade_menu, '_chip_glyphs', return_value=None),
              patch.object(upgrade_menu.ppocr, 'read_line', side_effect=lambda img, **kw: crops.append(img.shape[:2]) or '')):
            bp.read_chips(vision, Mock(), frame)
        boxes = [bp._anchored(frame, None, 1100, 700, box) for box in (bp._BUILDER_TEXT, bp._LAB_TEXT)]
        self.assertEqual(crops, [(h, w) for (_x, _y, w, h) in boxes])

    def test_upgrade_dialog_resource_button(self):
        frame = canvas(('dialog_hv_title.jpg', 230, 0), ('dialog_hv_bottom.jpg', 150, 730), size=WAYDROID)
        self.assertTrue(bp.dialog_title_ok(_vision(), frame))
        (x, y) = bp.find_confirm_button(_vision(), frame, RESOURCE_ELIXIR)
        self.assertTrue(1250 < x < 1530 and 970 < y < 1100)  # the elixir Confirm, not the grey Hammer one
        self.assertIsNone(bp.find_confirm_button(_vision(), frame, RESOURCE_GOLD))
        self.assertFalse(bp.gem_prompt_visible(_vision(), frame))

    def test_gem_prompt(self):
        frame = canvas(('gem_prompt.jpg', 520, 330), size=WAYDROID)
        self.assertTrue(bp.gem_prompt_visible(_vision(), frame))
        self.assertIsNone(bp.find_confirm_button(_vision(), frame))  # its green button carries the gem
        self.assertFalse(bp.dialog_title_ok(_vision(), frame))
        self.assertIsNotNone(bp.find_close(_vision(), frame))

    def test_wall_upgrade_button_prefers_elixir(self):
        (point, resource) = bp.wall_upgrade_button(_vision(), canvas(('wall_grid_bb.jpg', 380, 680), size=WAYDROID))
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


class StartCountTests(unittest.TestCase):
    """run_pass counts the cards it tried to start: the idle spend burst goes on while passes
    try one (a card that failed sits out its cooldown, so the next pass reaches the next)."""
    def setUp(self):
        stop = Mock(**{'wait.return_value': False})
        window = Mock(**{'screenshot.return_value': np.zeros((1200, 1920, 3), np.uint8)})
        self.up = bp.BuildPanelUpgrader(window, Mock(), Mock(), Mock(), stop)
        self.up._open = Mock(return_value=True)
        self.up._close_panel = Mock()
        self.up._start = Mock(return_value='started')
        self.card = UpgradeRow(label='Cannon', section='', cost=5000, resource=RESOURCE_GOLD, affordable=True, center=(1500, 400))

    def one(self, mode, chip_after):
        with (patch.object(bp, 'parse_cards', return_value=[self.card]),
              patch.object(bp, 'choose_upgrade', return_value=self.card),
              patch.object(bp, 'read_chips', return_value=(chip_after, None))):
            return self.up._one(bp.TAB_BUILDINGS, (10 ** 6, 10 ** 6, 0), 1, UpgradePolicy(), mode)

    def test_a_start_is_counted_confirmed_or_not(self):
        for (case, chip) in (('confirmed', bp.Chip(0, 6, False)), ('slot still free', bp.Chip(1, 6, False)),
                             ('chip unreadable', None)):
            with self.subTest(case):
                self.up.tried = 0
                note = self.one('maxer', chip)
                self.assertEqual(self.up.tried, 1, note)

    def test_a_failed_start_is_counted_and_sits_out_its_cooldown(self):
        self.up._start.return_value = 'no Confirm button, not started:'
        note = self.one('maxer', bp.Chip(1, 6, False))
        self.assertEqual(self.up.tried, 1, note)
        self.assertIn('Cannon', self.up._failed)

    def test_a_gem_prompt_is_not_counted(self):  # no builder free after all: the burst stops there
        self.up._start.return_value = 'gem prompt closed, not started:'
        note = self.one('maxer', bp.Chip(1, 6, False))
        self.assertEqual(self.up.tried, 0, note)
        self.assertIn('Cannon', self.up._failed)

    def test_a_dry_run_tries_nothing(self):
        note = self.one('dry', bp.Chip(0, 6, False))
        self.assertEqual(self.up.tried, 0, note)
        self.up._start.assert_not_called()

    @patch.object(bp, 'read_chips', return_value=(bp.Chip(1, 6, True), bp.Chip(1, 2, True)))
    def test_each_pass_counts_from_zero(self, _chips):
        self.up.tried = 2  # what the last pass tried
        self.up.run_pass('maxer')  # goblin only: nothing to try
        self.assertEqual(self.up.tried, 0)

    def test_the_bot_hears_whether_the_pass_tried_a_card(self):
        bot = Bot.__new__(Bot)
        bot._panel_upgrader = Mock(**{'run_pass.return_value': 'note'})
        for (tried, expected) in ((0, False), (1, True), (2, True)):
            with self.subTest(tried=tried):
                bot._panel_upgrader.tried = tried
                self.assertIs(bot._build_panel_pass('maxer'), expected)


def make_bot():
    bot = bare_bot(np.zeros((1200, 1920, 3), np.uint8))
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
    @patch('app.core.bot.bb_strategy._portrait_hits', return_value=[])  # no other card than the swap buttons'
    @patch('app.core.bot.bb_strategy.identify', side_effect=['bomber', 'pekka', 'pekka'])
    @patch('app.core.bot.VisionService.find_all_template_centers', side_effect=[[(272, 1150), (430, 1150), (570, 1150), (710, 1150)], [(272, 1150)], []])
    def test_bb_plays_each_troop_in_its_order(self, _swaps, _identify, _hits, _alive):
        bot = make_bot()
        corners = {'left': (165, 570), 'top': (960, -15), 'right': (1762, 570)}  # the 16:10 diamond at 1920x1200
        bot.config.get_point = lambda key: list(corners[key])
        bot.vision.find_template.side_effect = lambda f, name, **kw: (250, 1100) if name == 'battlemachine.png' else (None, None)
        schedule = bot._deploy_bb_army(np.zeros((1200, 1920, 3), np.uint8))
        lift = int(round(91 * 1200 / 1600))
        taps = [c.args[:2] for c in bot.input.click.call_args_list]
        # a P.E.K.K.A push: the P.E.K.K.As as one pack, the machine card (its swap button beside
        # it is not a troop) with them, the Bomber 2.5 s later (its card again as it lands: the bomb)
        self.assertEqual(taps[-1], taps[-3])
        del taps[-1]
        cards = taps[0::2]
        self.assertEqual(cards, [(570, 1150 - lift), (710, 1150 - lift), (250, 1100), (430, 1150 - lift)])
        waits = [c.args[0] for c in bot.stop_event.wait.call_args_list]
        self.assertTrue(any(2.4 < w <= 2.5 for w in waits), waits)  # the Bomber waits for the pack to draw fire (less the check)
        points = taps[1::2]
        corner = corners['left'] if points[0][0] < 960 else corners['right']
        (ux, uy) = (960 - corner[0], -15 - corner[1])
        for (x, y) in points:  # on the edge from that corner to the top one, under the top HUD
            cross = ((x - corner[0]) * uy - (y - corner[1]) * ux) / (ux * ux + uy * uy) ** 0.5
            self.assertLessEqual(abs(cross), 2)
            self.assertGreaterEqual(y, 0.12 * 1200 - 1)
        (mx, my) = points[0]
        self.assertTrue(all(abs(x - mx) <= 0.1 * 1200 and abs(y - my) <= 0.1 * 1200 for (x, y) in points))  # one push
        self.assertEqual([a.card for a in schedule.items], cards)  # every card has an ability to come


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
