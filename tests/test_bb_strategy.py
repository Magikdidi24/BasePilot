"""Builder Base: which troop each card holds, the deploy plan, and a fight played to its end.
Crops of a live 1227x767 GPG battle (no player name in them), PNG like the other 767p ones."""
import itertools
import math
import random
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import cv2
import numpy as np

from app.core import bb_scout, bb_strategy
from app.core.build_panel import find_close
from app.services.vision import VisionService
from tests.helpers import FIXTURES, bare_bot, canvas

LIFT = 44  # px from a swap button up to its card's tap at 767p


def make_bot(vision=None):
    bot = bare_bot(np.zeros((767, 1227, 3), np.uint8))
    if vision is None:
        vision = Mock()
        vision.find_template_with_confidence.return_value = (None, None, 0.0)
    bot.vision = vision
    bot._update_config_size = Mock()
    bot._bb_record_result = Mock(return_value=None)  # no results screen to read, no history written
    bot._bb_plans = Mock()  # no history read
    bot._bb_plans.summary.return_value = ''
    bot._bb_plans.choose.side_effect = lambda army, available, stage=1: available[0]
    return bot


def bar(frame, machine_template=None):
    roi = VisionService.bottom_half_region(frame)
    swaps = VisionService.find_all_template_centers(frame, 'bbswap.png', region=roi, max_matches=12, suppress_pad_frac=0.1)
    mx = VisionService.find_template(frame, machine_template, region=roi)[0] if machine_template else None
    return bb_strategy.read_bar(VisionService, frame, swaps, LIFT, mx)


class BarTests(unittest.TestCase):
    def test_each_card_is_matched_to_its_troop(self):
        frame = canvas(('gpg767_bb_bar.png', 100, 640))  # Battle Machine, five Power P.E.K.K.As, a Bomber
        swaps = sorted(VisionService.find_all_template_centers(frame, 'bbswap.png', region=VisionService.bottom_half_region(frame),
                                                               max_matches=12, suppress_pad_frac=0.1))
        self.assertEqual([bb_strategy.identify(VisionService, frame, s) for s in swaps], ['pekka'] * 5 + ['bomber'])

    def test_six_witches_even_the_selected_card_without_its_swap_button(self):
        cards = bar(canvas(('gpg767_bb_witch_bar.png', 100, 640)), 'battlemachine.png')
        self.assertEqual([c.troop for c in cards], ['witch'] * 6)

    def test_next_stage_the_survivor_and_the_reinforcement_not_the_dead(self):
        # stage 2: five witches died (grey cards), one came back without a swap button,
        # a Bomber came as reinforcement; the machine card is the Battle Copter now
        frame = canvas(('gpg767_bb_stage2_bar.png', 100, 640))
        (mx, my) = VisionService.find_template(frame, 'flyingmachine.png', region=VisionService.bottom_half_region(frame))
        self.assertTrue(mx and bb_strategy.alive(frame, (mx, my)))
        cards = bar(frame, 'flyingmachine.png')
        self.assertEqual([c.troop for c in cards], ['witch', 'bomber'])
        self.assertEqual([c.tap for c in cards], [(365, 688), (814, 691)])  # the second card, the one in colour

    def test_next_stage_the_survivors_whose_health_bar_covers_their_portrait(self):
        # stage 2 live: five P.E.K.K.As survived (a health bar over each portrait, no swap
        # button), the Bomber died, a P.E.K.K.A came as reinforcement
        cards = bar(canvas(('gpg767_bb_stage2_pekka_bar.png', 100, 640)), 'battlemachine.png')
        self.assertEqual([c.troop for c in cards], ['pekka'] * 6)
        self.assertEqual([c.tap for c in cards], [(275, 688), (365, 688), (455, 688), (545, 688), (634, 688), (814, 691)])

    def test_deployed_cards_are_not_on_the_bar_any_more(self):
        # mid-fight their portraits still match, but their cards are green, red or grey
        for name in ('gpg767_bb_pekka_fight_bar', 'gpg767_bb_witch_fight_bar', 'gpg767_bb_ability_states_bar'):
            self.assertEqual(bar(canvas((f'{name}.png', 100, 640)), 'battlemachine.png'), [], name)

    def test_every_troop_of_the_change_troops_menu(self):
        # the menu draws the portraits at the bar's scale: each card is read as a bar card
        # whose swap button would sit under it
        frame = canvas(('gpg767_bb_change_troops.png', 300, 470))
        troops = ['barbarian', 'archer', 'boxer', 'minion', 'bomber', 'babydragon', 'cannoncart', 'witch', 'dropship', 'pekka']
        swaps = [(round(360.2 + 86.2 * i) + 14, 587) for i in range(len(troops))]
        self.assertEqual([bb_strategy.identify(VisionService, frame, s) for s in swaps], troops)

    def test_an_unknown_card_is_no_troop(self):
        frame = canvas(('gpg767_bb_bar.png', 100, 640))
        self.assertEqual(bb_strategy.identify(VisionService, frame, (900, 732)), '')  # an empty reinforcement slot


class PlanTests(unittest.TestCase):
    H = 767
    EDGE = bb_strategy.front_edge((105, 364), (614, -10), 767)  # the 16:10 diamond's left and top corners at 1227x767
    STILL = SimpleNamespace(uniform=lambda a, b: 0.0)  # the entry mid-front, no jitter

    def offsets(self, steps):
        """Each step's landing point as screen heights along the front from its middle, and
        its distance off the front line in px."""
        ((x0, y0), (x1, y1)) = self.EDGE
        length = math.hypot(x1 - x0, y1 - y0)
        (ux, uy) = ((x1 - x0) / length, (y1 - y0) / length)
        along = [((s.point[0] - x0) * ux + (s.point[1] - y0) * uy - length / 2) / self.H for s in steps]
        off = [abs((s.point[0] - x0) * uy - (s.point[1] - y0) * ux) for s in steps]
        return (along, off)

    def test_the_front_keeps_clear_of_the_corner_and_the_top_hud(self):
        ((x0, y0), (x1, y1)) = self.EDGE
        self.assertAlmostEqual(math.hypot(x0 - 105, y0 - 364), 0.06 * 767, delta=1)
        self.assertAlmostEqual(y1, 0.12 * 767, delta=1)  # the timer and the names are above
        self.assertLess(x1, 614)

    def test_the_machine_and_tanks_open_a_little_apart_the_bomber_behind(self):
        cards = [bb_strategy.Card('bomber', (724, 688))] + [bb_strategy.Card('boxer', (275 + 90 * k, 688)) for k in range(5)]
        steps = bb_strategy.plan(cards, (159, 705), bb_strategy.edge_front(self.EDGE, self.H, rng=self.STILL))
        self.assertEqual([s.troop for s in steps], ['machine'] + ['boxer'] * 5 + ['bomber'])
        self.assertEqual([s.card for s in steps[1:6]], [(275 + 90 * k, 688) for k in range(5)])  # left to right
        self.assertEqual([s.wait for s in steps], [0.0, 0.3, 0.0, 0.0, 0.0, 0.0, 1.0])  # the Bomber once the tanks draw fire
        (along, off) = self.offsets(steps)
        self.assertTrue(all(d <= 1.5 for d in off), off)  # all on the front
        self.assertAlmostEqual(along[0], 0.0, delta=0.002)  # the machine at the entry
        for (got, want) in zip(along[1:6], (0.025, -0.025, 0.05, -0.05, 0.075)):  # the tanks around it, splash apart
            self.assertAlmostEqual(got, want, delta=0.002)
        self.assertAlmostEqual(along[6], 0.0, delta=0.002)  # the Bomber behind them

    def test_a_pekka_push_lands_one_pack_then_the_machine_then_the_bomber(self):
        # live, a Bomber landed first died alone before any wall, and P.E.K.K.As 0.025 screen
        # heights apart split between two outer buildings: the P.E.K.K.As now land as one pack
        # (one first building), the machine with them, the Bomber once the defences are on them
        cards = [bb_strategy.Card('bomber', (724, 688))] + [bb_strategy.Card('pekka', (275 + 90 * k, 688)) for k in range(5)]
        steps = bb_strategy.plan(cards, (159, 705), bb_strategy.edge_front(self.EDGE, self.H, rng=self.STILL))
        self.assertEqual([s.troop for s in steps], ['pekka'] * 5 + ['machine', 'bomber'])
        self.assertEqual([s.card for s in steps[:5]], [(275 + 90 * k, 688) for k in range(5)])  # left to right
        self.assertEqual([s.wait for s in steps], [0.0] * 6 + [2.5])
        (along, off) = self.offsets(steps)
        self.assertTrue(all(d <= 1.5 for d in off), off)
        for (got, want) in zip(along[:5], (0.0, 0.006, -0.006, 0.012, -0.012)):  # one pack, about a tile wide
            self.assertAlmostEqual(got, want, delta=0.002)
        self.assertAlmostEqual(along[5], 0.0, delta=0.002)  # the machine with them
        self.assertAlmostEqual(along[6], 0.0, delta=0.002)  # the Bomber behind them, at the same spot
        self.assertTrue(bb_strategy.PROFILES['bomber'].ability_on_landing)  # its bomb for the wall the pack stands at

    def test_a_pekka_push_without_its_machine_or_bomber(self):
        # a later stage: the machine is down, the Bomber died; the pack alone, no wait
        cards = [bb_strategy.Card('pekka', (275 + 90 * k, 688)) for k in range(3)]
        steps = bb_strategy.plan(cards, None, bb_strategy.edge_front(self.EDGE, self.H, rng=self.STILL))
        self.assertEqual([(s.troop, s.wait) for s in steps], [('pekka', 0.0)] * 3)

    def test_flankers_out_on_both_sides_then_breakers_support_and_lone_dragons(self):
        cards = ([bb_strategy.Card('barbarian', (100 + 10 * k, 688)) for k in range(6)]
                 + [bb_strategy.Card(t, (300 + 10 * k, 688)) for (k, t) in enumerate(('witch', 'babydragon', 'bomber', 'witch', 'babydragon', 'cannoncart', ''))])
        steps = bb_strategy.plan(cards, None, bb_strategy.edge_front(self.EDGE, self.H, rng=self.STILL))
        self.assertEqual([s.troop for s in steps],
                         ['barbarian'] * 6 + ['bomber', 'witch', 'witch', 'cannoncart', 'babydragon', 'babydragon', ''])
        self.assertEqual([s.wait for s in steps], [0.0] * 6 + [1.0, 1.2, 0.0, 0.0, 0.5, 0.0, 0.3])
        (along, off) = self.offsets(steps)
        self.assertTrue(all(d <= 1.5 for d in off), off)
        # two pairs of Raged Barbarians far out on each side at once (the funnel), two with the push
        for (got, want) in zip(along, (-0.17, 0.17, -0.19, 0.19, 0.0, 0.02)):
            self.assertAlmostEqual(got, want, delta=0.002)
        self.assertTrue(all(abs(a) <= 0.03 for a in along[6:10]))  # Bomber, Night Witches, Cannon Cart: the push
        self.assertAlmostEqual(along[10], 0.09, delta=0.002)  # the Baby Dragons apart, one each side
        self.assertAlmostEqual(along[11], -0.09, delta=0.002)
        self.assertAlmostEqual(along[12], 0.0, delta=0.002)  # an unknown troop follows the push

    def test_points_stay_on_a_short_front(self):
        edge = ((300.0, 200.0), (340.0, 170.0))  # 50 px: the flanks would fall off it
        cards = [bb_strategy.Card('archer', (100 + 10 * k, 688)) for k in range(6)]
        for step in bb_strategy.plan(cards, None, bb_strategy.edge_front(edge, self.H)):
            self.assertTrue(300 <= step.point[0] <= 340 and 170 <= step.point[1] <= 200, step.point)


class ScoutTests(unittest.TestCase):
    # base centre on each live scouting crop (y 70-630 of a 1227x767 battle, no names in it):
    # the map, and the base on it, sit somewhere else in each
    BASES = {'green_middle': (623, 377), 'blue_middle': (618, 353), 'green_long_wall': (667, 315),
             'blue_bottom_left': (550, 443), 'green_bottom': (485, 313), 'green_left': (570, 339), 'blue_spread': (606, 308)}
    BEST = SimpleNamespace(choices=lambda population, weights: [population[0]], uniform=lambda a, b: 0.0)

    @staticmethod
    def battle(name):
        frame = np.zeros((767, 1227, 3), np.uint8)
        frame[70:630] = cv2.imread(str(FIXTURES / f'gpg767_bb_scout_{name}.jpg'))
        return frame

    def test_the_base_is_found_wherever_it_sits(self):
        for (name, (x, y)) in self.BASES.items():
            scouting = bb_scout.scout(self.battle(name))
            self.assertIsNotNone(scouting, name)
            self.assertLessEqual(math.hypot(scouting.centre[0] - x, scouting.centre[1] - y), 40, (name, scouting.centre))

    def test_entries_lie_just_off_the_base_out_of_the_hud(self):
        for name in self.BASES:
            scouting = bb_scout.scout(self.battle(name))
            entries = scouting.entries[:3]
            self.assertEqual(len(entries), 3, name)
            for (x, y) in entries:
                self.assertTrue(scouting.valid[y // 4, x // 4], (name, x, y))
                self.assertTrue(0.045 <= scouting.distance[y // 4, x // 4] <= 0.075, (name, x, y))
                for (x0, y0, x1, y1) in bb_scout._HUD:
                    self.assertFalse(x0 * 1227 <= x <= x1 * 1227 and y0 * 767 <= y <= y1 * 767, (name, x, y))
            for (a, b) in itertools.combinations(entries, 2):
                self.assertGreaterEqual(math.hypot(a[0] - b[0], a[1] - b[1]), 0.15 * 767, name)

    def test_the_side_changes_from_battle_to_battle(self):
        frame = self.battle('green_middle')
        firsts = {bb_scout.scout(frame, rng=random.Random(seed)).entries[0] for seed in range(20)}
        self.assertEqual(len(firsts), 3)  # one of the three best sides each time

    def test_buildings_draw_the_attack_not_empty_walls(self):
        # three long walls with nothing inside on the right, the buildings bottom-left: walls
        # counted as targets, the best spot was by them, at (642, 294)
        best = bb_scout.scout(self.battle('blue_bottom_left'), rng=self.BEST).entries[0]
        (buildings, walls) = ((470, 480), (830, 400))
        self.assertLess(math.dist(best, buildings), math.dist(best, walls), best)

    def test_the_formation_hugs_the_base(self):
        for name in self.BASES:
            scouting = bb_scout.scout(self.battle(name), rng=random.Random(2))
            entry = scouting.entries[0]
            at = bb_scout.front(scouting, entry, rng=self.BEST)
            self.assertLessEqual(math.hypot(at(0.0)[0] - entry[0], at(0.0)[1] - entry[1]), 4, name)
            for offset in (0.025, -0.025, 0.09, -0.09, 0.17, -0.17):
                (x, y) = at(offset)
                self.assertTrue(scouting.valid[y // 4, x // 4], (name, offset, x, y))
                self.assertLessEqual(math.hypot(x - entry[0], y - entry[1]), 0.3 * 767, (name, offset))

    def test_no_base_on_a_blank_screen(self):
        self.assertIsNone(bb_scout.scout(np.zeros((767, 1227, 3), np.uint8)))

    MORTARS = {'green_middle': (717, 415), 'green_bottom': (444, 346), 'green_left': (594, 394),  # gold, stone, wood
               'blue_gold_mortar': (527, 349), 'green_silver_mortar': (539, 408),
               'blue_middle': None, 'green_long_wall': None, 'blue_bottom_left': None, 'blue_spread': None}

    def test_the_multi_mortar_whatever_its_level_and_light(self):
        for (name, want) in self.MORTARS.items():
            frame = self.battle(name)
            got = bb_scout.multi_mortar(frame, bb_scout.scout(frame))
            if want is None:
                self.assertIsNone(got, name)
            else:
                self.assertIsNotNone(got, name)
                self.assertLessEqual(math.dist(got, want), 8, (name, got))

    def test_a_pekka_push_lands_by_the_multi_mortar(self):
        for (name, mortar) in self.MORTARS.items():
            if mortar is None:
                continue
            scouting = bb_scout.scout(self.battle(name))
            entries = bb_scout.towards(scouting, mortar, rng=random.Random(4))
            (ys, xs) = np.nonzero(scouting.valid)
            nearest = float(np.hypot(xs * 4 + 2 - mortar[0], ys * 4 + 2 - mortar[1]).min())
            self.assertTrue(scouting.valid[entries[0][1] // 4, entries[0][0] // 4], name)
            self.assertLessEqual(math.dist(entries[0], mortar), nearest + 0.02 * 767 + 1, name)
            self.assertGreaterEqual(len(entries), 2, name)  # other sides for when that spot does not land


class FightTests(unittest.TestCase):
    def test_return_home_of_the_results_screen(self):
        bot = make_bot(VisionService)
        (x, y) = bot._bb_return_home_point(canvas(('gpg767_bb_results.png', 400, 560)), ocr=False)  # the art at the bot's own scale
        self.assertTrue(abs(x - 613) <= 15 and abs(y - 648) <= 15)
        self.assertIsNone(bot._bb_return_home_point(canvas(('gpg767_bb_fight_bar.png', 100, 640)), ocr=False))

    def test_return_home_waits_for_the_results_screen_to_go(self):
        bot = make_bot()
        clock = itertools.count(0, 0.5)
        with patch('app.core.bot.time.monotonic', side_effect=lambda: next(clock)), \
                patch.object(bot, '_bb_return_home_point', side_effect=[(613, 648), (613, 648), None]):
            self.assertTrue(bot._bb_leave_results((613, 648)))
        self.assertEqual(bot.input.click.call_count, 1)  # still fading out for a moment: no second tap

    def test_a_results_screen_that_stays_gets_one_more_tap(self):
        bot = make_bot()
        clock = itertools.count(0, 1.0)
        with patch('app.core.bot.time.monotonic', side_effect=lambda: next(clock)), \
                patch.object(bot, '_bb_return_home_point', return_value=(613, 648)):
            self.assertFalse(bot._bb_leave_results((613, 648)))
        self.assertEqual(bot.input.click.call_count, 2)  # the tap, then once more after a lost tap's delay

    def test_the_speed_button_while_it_reads_1x(self):
        bot = make_bot(VisionService)
        (x, y) = bot._bb_speed_point(canvas(('gpg767_bb_speed_070216.png', 1080, 400)))  # 1:00 left: "1x"
        self.assertTrue(abs(x - 1181) <= 5 and abs(y - 492) <= 5)
        self.assertEqual(bot._bb_speed_point(canvas(('gpg767_bb_speed_070606.png', 1080, 400))), (x, y))  # another battle's
        self.assertIsNone(bot._bb_speed_point(canvas(('gpg767_bb_speed_070220.png', 1080, 400))))  # "4x" already
        self.assertIsNone(bot._bb_speed_point(canvas(('gpg767_bb_speed_070146.png', 1080, 400))))  # earlier: no button

    def test_the_last_minute_is_sped_up_and_a_lost_tap_tried_again(self):
        bot = make_bot()
        clock = itertools.count()  # 2 s a poll
        speed = [None, (1181, 492), (1181, 492), None, None, None]  # 1x; the first tap is lost; then 4x
        with patch('app.core.bot.time.monotonic', side_effect=lambda: next(clock)), \
                patch.object(bot, '_bb_return_home_point', side_effect=[None] * 8 + [(613, 648), None]), \
                patch.object(bot, '_bb_speed_point', side_effect=speed) as button, \
                patch('app.core.bot.VisionService.find_all_template_centers', return_value=[]):
            self.assertTrue(bot._bb_fight_to_the_end(bb_strategy.Abilities()))
        taps = [c.args[:2] for c in bot.input.click.call_args_list]
        self.assertEqual(taps, [(1181, 492), (1181, 492), (613, 648)])
        self.assertEqual(button.call_count, 6)  # not looked at again for 3 s after a tap

    def test_the_fight_is_played_out_and_left_by_return_home_only(self):
        bot = make_bot()
        clock = itertools.count()
        abilities = bb_strategy.Abilities()
        abilities.add(bb_strategy.Step((275, 688), (0, 0), 0, bb_strategy.PROFILES['pekka'], 'pekka'), 0)
        abilities.add(bb_strategy.Step((709, 688), (0, 0), 0, bb_strategy.PROFILES['bomber'], 'bomber'), 0)
        pekka = iter([1.0])  # she lands untouched, then the defences have her at 40 %
        with patch('app.core.bot.time.monotonic', side_effect=lambda: next(clock)), \
                patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.health', side_effect=lambda frame, card: next(pekka, 0.4) if card == (275, 688) else 0.4), \
                patch('app.core.bb_strategy.ability_state', return_value=bb_strategy.READY), \
                patch.object(bot, '_bb_return_home_point', side_effect=[None] * 12 + [(613, 648), None]), \
                patch('app.core.bot.VisionService.find_all_template_centers', return_value=[]):
            self.assertTrue(bot._bb_fight_to_the_end(abilities))
        taps = [c.args[:2] for c in bot.input.click.call_args_list]
        self.assertEqual(taps[-1], (613, 648))  # only the results screen ends it
        self.assertEqual(set(taps), {(275, 688), (709, 688), (613, 648)})  # nothing else: no End Battle, no Surrender
        self.assertIn(taps.count((275, 688)), (1, 2, 3))  # Overcharge once engaged; retried while the card stays green
        self.assertGreaterEqual(taps.count((709, 688)), 2)  # the Bomber's, again each time its card is green again

    def test_troops_back_on_the_bar_are_deployed_again(self):
        bot = make_bot()
        clock = itertools.count()
        swaps = [[(275, 732)]] + [[]] * 50  # the next stage's reinforcement shows its swap button once
        with patch('app.core.bot.time.monotonic', side_effect=lambda: next(clock)), \
                patch.object(bot, '_bb_return_home_point', side_effect=[None] * 12 + [(613, 648), None]), \
                patch('app.core.bot.VisionService.find_all_template_centers', side_effect=swaps), \
                patch.object(bot, '_deploy_bb_army', return_value=bb_strategy.Abilities()) as deploy:
            self.assertTrue(bot._bb_fight_to_the_end(bb_strategy.Abilities()))
        deploy.assert_called_once()

    def test_a_troop_left_on_the_bar_lands_once_more_at_the_entry(self):
        bot = make_bot()
        bot.config = SimpleNamespace(get_point=lambda key: list({'left': (105, 364), 'top': (614, -10), 'right': (1126, 364)}[key]))
        pekkas = [bb_strategy.Card('pekka', (275 + 90 * k, 688)) for k in range(3)]
        reads = [(pekkas, None), ([pekkas[2]], None)]  # the third one's tap fell off the deploy zone
        with patch.object(bot, '_read_bb_bar', side_effect=reads):
            abilities = bot._deploy_bb_army(np.zeros((767, 1227, 3), np.uint8))  # no base on it: a map edge
        taps = [c.args[:2] for c in bot.input.click.call_args_list]
        self.assertEqual(taps[0::2], [(275, 688), (365, 688), (455, 688), (455, 688)])
        self.assertTrue(abs(taps[-1][0] - taps[1][0]) <= 10 and abs(taps[-1][1] - taps[1][1]) <= 10)  # where the first one landed
        self.assertEqual([a.card for a in abilities.items], [(275, 688), (365, 688), (455, 688)])  # one each

    def test_an_opening_that_does_not_land_goes_again_from_the_next_side(self):
        bot = make_bot()
        pekkas = [bb_strategy.Card('pekka', (275 + 90 * k, 688)) for k in range(2)]
        fronts = [('A', lambda o: (300, 200)), ('B', lambda o: (800, 300)), ('C', lambda o: (500, 500))]
        with patch.object(bot, '_read_bb_bar', side_effect=[(pekkas, (159, 705)), ([], None)]), \
                patch.object(bot, '_bb_fronts', return_value=fronts), \
                patch.object(bot, '_bb_swaps_shown', return_value=True), \
                patch.object(bot, '_bb_landed', side_effect=[False, True]) as landed:
            abilities = bot._deploy_bb_army(np.zeros((767, 1227, 3), np.uint8))
        taps = [c.args[:2] for c in bot.input.click.call_args_list]
        # the P.E.K.K.A pack and the machine at once on side A (a no-deploy spot), then again on side B
        pack = [(275, 688), (365, 688), (159, 705)]
        self.assertEqual(taps, [t for card in pack for t in (card, (300, 200))] + [t for card in pack for t in (card, (800, 300))])
        self.assertEqual(landed.call_count, 2)
        self.assertEqual([a.card for a in abilities.items], pack)  # each one's ability once
        # at the usual pace: live, 0.2 s and 0.1 s took one card in two of a stage's second bar
        self.assertEqual({c.kwargs['pause'] for c in bot.input.click.call_args_list}, {0.25, 0.2})

    def test_any_other_army_opens_with_its_first_troop(self):
        bot = make_bot()
        witches = [bb_strategy.Card('witch', (275 + 90 * k, 688)) for k in range(2)]
        fronts = [('A', lambda o: (300, 200)), ('B', lambda o: (800, 300)), ('C', lambda o: (500, 500))]
        with patch.object(bot, '_read_bb_bar', side_effect=[(witches, (159, 705)), ([], None)]), \
                patch.object(bot, '_bb_fronts', return_value=fronts), \
                patch.object(bot, '_bb_swaps_shown', return_value=True), \
                patch.object(bot, '_bb_landed', side_effect=[False, True]) as landed:
            bot._deploy_bb_army(np.zeros((767, 1227, 3), np.uint8))
        taps = [c.args[:2] for c in bot.input.click.call_args_list]
        # the machine alone on side A (a no-deploy spot), again on side B, the witches after it
        self.assertEqual(taps[:4], [(159, 705), (300, 200), (159, 705), (800, 300)])
        self.assertEqual(taps[4::2], [(275, 688), (365, 688)])
        self.assertEqual(landed.call_count, 2)

    def test_the_landing_check_comes_off_the_bombers_wait(self):
        bot = make_bot()
        cards = [bb_strategy.Card('pekka', (275, 688)), bb_strategy.Card('bomber', (724, 688))]
        clock = [100.0]

        def landed():  # the check takes a second
            clock[0] += 1.0
            return True
        with patch.object(bot, '_read_bb_bar', side_effect=[(cards, None), ([], None)]), \
                patch.object(bot, '_bb_fronts', return_value=[('A', lambda o: (300, 200)), ('B', lambda o: (800, 300))]), \
                patch.object(bot, '_bb_swaps_shown', return_value=True), \
                patch.object(bot, '_bb_landed', side_effect=landed), \
                patch('app.core.bot.time.monotonic', side_effect=lambda: clock[0]):
            bot._deploy_bb_army(np.zeros((767, 1227, 3), np.uint8))
        self.assertIn(call(1.5), bot.stop_event.wait.call_args_list)  # 2.5 s from the pack, the check's second included

    def test_each_stage_keeps_the_base_it_was_planned_on(self):
        bot = make_bot()
        frame = np.zeros((767, 1227, 3), np.uint8)
        pekkas = [bb_strategy.Card('pekka', (275, 688))]
        with patch.object(bot, '_read_bb_bar', side_effect=[(pekkas, None), ([], None)]), \
                patch.object(bot, '_bb_fronts', return_value=[('A', lambda o: (300, 200))]), \
                patch('app.core.bot.save_frame') as save:
            bot._deploy_bb_army(frame, stage=2)
        save.assert_called_once_with(frame, 'scouting', 'stage2', keep=400)

    def test_the_opening_is_the_pack_or_the_first_troop(self):
        pekkas = [bb_strategy.Card('pekka', (275 + 90 * k, 688)) for k in range(5)] + [bb_strategy.Card('bomber', (724, 688))]
        steps = bb_strategy.plan(pekkas, (159, 705), lambda offset: (300, 200))
        self.assertEqual(bb_strategy.opening(steps), 6)  # the five P.E.K.K.As and the machine, not the Bomber
        witches = [bb_strategy.Card('witch', (275 + 90 * k, 688)) for k in range(6)]
        self.assertEqual(bb_strategy.opening(bb_strategy.plan(witches, (159, 705), lambda offset: (300, 200))), 1)
        flanked = [bb_strategy.Card('pekka', (275 + 90 * k, 688)) for k in range(2)] + [bb_strategy.Card('barbarian', (455 + 90 * k, 688)) for k in range(3)]
        self.assertEqual(bb_strategy.opening(bb_strategy.plan(flanked, None, lambda offset: (300, 200))), 2)  # not the flankers


class LiveStatusTests(unittest.TestCase):
    def test_storages_and_the_session_gains_after_each_battle(self):
        bot = make_bot()
        bot._loot_callback = Mock()
        bot._state_callback = Mock()
        bot._reset_loot_session()
        reads = [(651626, 1356974, 278), (660000, 1400000, 283), None]  # gold, elixir, gems; then an unreadable HUD
        with patch.object(bot, '_read_hud_triplet_stable', side_effect=reads):
            bot._bb_live_status()
            bot._bb_live_status()
            bot._bb_live_status()
        self.assertEqual(bot._loot_totals, (8374, 43026, 0))  # the gems are no loot
        self.assertEqual(bot._loot_callback.call_args.args[:3], (8374, 43026, 0))
        states = [c.args[0] for c in bot._state_callback.call_args_list]
        self.assertEqual([s['state'] for s in states], ['Builder Base'] * 3)
        self.assertEqual([s['storages'] for s in states], ['652k / 1.4M', '660k / 1.4M', None])


class CartTests(unittest.TestCase):
    @staticmethod
    def home(name):
        """The Builder Base village, back from a battle (y 76-552 of a 1227x767 frame)."""
        return canvas((f'gpg767_bb_home_cart_{name}.jpg', 0, 76))

    def test_the_full_cart_wherever_the_view_left_it(self):
        bot = make_bot(VisionService)
        for (name, want) in (('full', (842, 120)), ('panned', (848, 393)), ('not_full', None)):
            with patch.object(bot, '_bb_still_frame', return_value=self.home(name)):
                got = bot._find_bb_full_elixir_cart()
            if want is None:
                self.assertIsNone(got, name)
            else:
                self.assertLessEqual(math.dist(got, want), 10, (name, got))

    def collect(self, finds):
        bot = make_bot()
        with patch.object(bot, '_find_bb_full_elixir_cart', side_effect=finds), \
                patch.object(bot, '_bb_pan_down_left_from_center') as pan, \
                patch.object(bot, '_wait_for_image', return_value=(613, 600)), \
                patch('app.core.bot.find_close', return_value=(1072, 78)):
            bot._bb_collect_elixir_cart_after_attack()
        return ([c.args[:2] for c in bot.input.click.call_args_list], pan.call_count)

    def test_a_cart_on_screen_is_collected_without_a_pan(self):
        # the cart, its Collect, then its window's X (left open, it ate the next Battle tap)
        self.assertEqual(self.collect([(842, 120)]), ([(842, 120), (613, 600), (1072, 78)], 0))

    def test_a_cart_off_screen_is_looked_for_after_one_pan(self):
        self.assertEqual(self.collect([None, (848, 393)]), ([(848, 393), (613, 600), (1072, 78)], 1))

    def test_the_cart_window_x(self):
        frame = canvas(('gpg767_bb_cart_window.jpg', 600, 60))  # live, after Collect
        self.assertLessEqual(math.dist(find_close(VisionService, frame), (1072, 78)), 6)

    def test_no_tap_at_all_without_a_full_cart(self):
        self.assertEqual(self.collect([None, None]), ([], 1))  # no "empty" taps on the walls


class CardTests(unittest.TestCase):
    TAPS = [(275 + 90 * k, 688) for k in range(6)]  # the six troop cards of a 1227x767 bar

    def assertHealth(self, got, want):
        self.assertEqual([g is None for g in got], [w is None for w in want], got)
        for (g, w) in zip(got, want):
            if w is not None:
                self.assertAlmostEqual(g, w, delta=0.1)

    def test_health_bars_of_a_live_fight(self):
        pekkas = canvas(('gpg767_bb_pekka_fight_bar.png', 100, 640))  # five P.E.K.K.As and a Bomber, mid-fight
        self.assertHealth([bb_strategy.health(pekkas, t) for t in self.TAPS], [0.65, 0.35, 1.0, 1.0, 0.45, 0.9])
        witches = canvas(('gpg767_bb_witch_fight_bar.png', 100, 640))  # two in the red, two dead, two untouched
        self.assertHealth([bb_strategy.health(witches, t) for t in self.TAPS], [0.13, 1.0, 0.15, None, None, 1.0])
        self.assertEqual([bb_strategy.alive(witches, t) for t in self.TAPS], [True, True, True, False, False, True])
        before = canvas(('gpg767_bb_bar.png', 100, 640))  # not deployed yet: no bar
        self.assertEqual([bb_strategy.health(before, t) for t in self.TAPS], [None] * 6)

    def test_health_whatever_the_card_anchor(self):
        # live: P.E.K.K.As under fire 18 s in, their cards green (Overcharge ready). A swap
        # button's tap sits 3 px lower than a portrait's, and a fixed band read there took
        # the green card under the bar for a full bar: 100 % for every one of them.
        frame = canvas(('gpg767_bb_pekka_engaged_bar.png', 100, 640))
        for dy in (-2, 0, 2, 3, 4):
            taps = [(x, y + dy) for (x, y) in self.TAPS]
            self.assertHealth([bb_strategy.health(frame, t) for t in taps], [0.89, 0.79, 0.89, 0.89, 0.92, 1.0])
        witches = canvas(('gpg767_bb_witch_fight_bar.png', 100, 640))  # a dark portrait under the bar is no edge
        self.assertHealth([bb_strategy.health(witches, (x, y + 3)) for (x, y) in self.TAPS], [0.13, 1.0, 0.15, None, None, 1.0])

    def test_ability_states_read_on_the_cards(self):
        # 19 s into a live fight: P.E.K.K.A 1 used its Overcharge (grey), the others' are ready
        # (green), the Bomber's Bouncing Bomb recharges (red); before the deploy: blue
        frame = canvas(('gpg767_bb_ability_states_bar.png', 100, 640))
        (ready, used, recharging) = (bb_strategy.READY, bb_strategy.USED, bb_strategy.RECHARGING)
        self.assertEqual([bb_strategy.ability_state(frame, t) for t in self.TAPS], [used, ready, ready, ready, ready, recharging])
        before = canvas(('gpg767_bb_bar.png', 100, 640))
        self.assertEqual([bb_strategy.ability_state(before, t) for t in self.TAPS], [None] * 6)
        self.assertEqual([bb_strategy.waiting(before, t) for t in self.TAPS], [True] * 6)
        self.assertEqual([bb_strategy.waiting(frame, t) for t in self.TAPS], [False] * 6)


class AbilityTests(unittest.TestCase):
    def abilities(self, troop, cards, landed=0):
        abilities = bb_strategy.Abilities()
        for card in cards:
            abilities.add(bb_strategy.Step(card, (0, 0), 0, bb_strategy.PROFILES[troop], troop), landed)
        return abilities

    def test_engaged_troops_fire_one_at_a_time_the_most_hurt_first(self):
        cards = [(275, 688), (365, 688), (455, 688)]
        hp = dict.fromkeys(cards, 0.2)
        used = set()
        state = lambda frame, card: bb_strategy.USED if card in used else bb_strategy.READY
        abilities = self.abilities('pekka', cards)
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', side_effect=state), \
                patch('app.core.bb_strategy.health', side_effect=lambda frame, card: hp[card]):
            self.assertIsNone(abilities.next_tap(1.0, 'frame'))  # not before the earliest (2 s)
            hp.update(dict.fromkeys(cards, 1.0))
            self.assertIsNone(abilities.next_tap(2.0, 'frame'))  # landed untouched
            self.assertIsNone(abilities.next_tap(2.5, 'frame'))
            hp.update({(275, 688): 0.45, (365, 688): 0.2, (455, 688): 0.4})
            first = abilities.next_tap(3.0, 'frame')
            self.assertEqual((first.card, first.health), ((365, 688), 0.2))  # the most hurt
            used.add(first.card)
            self.assertIsNone(abilities.next_tap(3.5, 'frame'))  # not two Overcharges at once
            self.assertEqual(abilities.next_tap(4.3, 'frame').card, (455, 688))
            used.add((455, 688))
            self.assertEqual(abilities.next_tap(5.6, 'frame').card, (275, 688))
            used.add((275, 688))
            self.assertIsNone(abilities.next_tap(30.0, 'frame'))  # their cards turned grey: each one once
            self.assertEqual(abilities.items, [])

    def pekka_fight(self, readings):
        """Overcharge taps of one P.E.K.K.A whose card reads ``readings`` ((s, health) per poll)."""
        abilities = self.abilities('pekka', [(275, 688)])
        taps = []
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', return_value=bb_strategy.READY):
            for (t, hp) in readings:
                with patch('app.core.bb_strategy.health', return_value=hp):
                    tap = abilities.next_tap(t, 'frame')
                if tap is not None:
                    taps.append((round(t, 2), tap.health, tap.why))
        return taps

    def test_the_overcharge_waits_for_the_thick_of_it(self):
        # a one-time blast around her, and she lives on. Live, the old rule fired the five of
        # them at 64-69 % on the first outer building, and at full health at 30 s: now it goes
        # under heavy fire or under half her health, never on time alone
        slow = [(2.0 + k, 1.0 - 0.02 * k) for k in range(20)]  # one outer building's fire: 100 % to 62 % in 19 s
        self.assertEqual(self.pekka_fight(slow), [])
        self.assertEqual(self.pekka_fight([(2.0 + 5 * k, 1.0) for k in range(30)]), [])  # untouched for 2.5 min
        attrition = [(2.0 + k, 1.0 - 0.03 * k) for k in range(20)]
        self.assertEqual([(t, round(hp, 2)) for (t, hp, _why) in self.pekka_fight(attrition)][:1], [(19.0, 0.49)])  # under half
        thick = [(2.0, 1.0), (2.7, 0.97), (3.4, 0.86), (4.1, 0.74)]  # the Roaster and the Crusher on her
        self.assertEqual(self.pekka_fight(thick)[:1], [(4.1, 0.74, 'lost 26% in 2.1 s')])
        steep = [(2.0, 1.0), (2.7, 0.89), (3.4, 0.77), (4.1, 0.66)]  # a steep fall is no misread bar
        self.assertEqual(self.pekka_fight(steep)[:1], [(4.1, 0.66, 'lost 34% in 2.1 s')])
        blow = [(2.0, 1.0), (2.8, 0.7), (3.6, 0.6)]  # one big blow, then more
        self.assertEqual(self.pekka_fight(blow)[:1], [(3.6, 0.6, 'lost 40% in 1.6 s')])

    def test_heavy_fire_whatever_the_poll_cadence(self):
        # a poll every ~0.8 s live, slower while taps go: 10 % of her health a second is heavy
        # fire from 0.7 to 2 s between readings, measured from the last one before the window
        for cadence in (0.7, 0.8, 1.0, 1.05, 1.1, 1.2, 1.5, 1.51, 2.0):
            with self.subTest(cadence=cadence):
                readings = [(2.0 + cadence * k, 1.0 - 0.1 * cadence * k) for k in range(int(8 / cadence))]
                taps = self.pekka_fight(readings)
                self.assertTrue(taps and taps[0][2].startswith('lost ') and taps[0][1] > 0.5, taps[:1])

    def test_the_pack_under_fire_one_after_another(self):
        # five P.E.K.K.As hit 1.5 s apart, 10 % a second: each one's under heavy fire,
        # though the spacing between two Overcharges skips some of her readings
        cards = [(275 + 90 * k, 688) for k in range(5)]
        abilities = self.abilities('pekka', cards)
        (clock, used, taps) = ([0.0], set(), [])
        hp = lambda frame, card: max(0.0, 1.0 - 0.1 * max(0.0, clock[0] - 3.0 - 1.5 * cards.index(card)))
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', side_effect=lambda frame, card: bb_strategy.USED if card in used else bb_strategy.READY), \
                patch('app.core.bb_strategy.health', side_effect=hp):
            for k in range(24):
                clock[0] = 2.0 + 0.8 * k
                tap = abilities.next_tap(clock[0], 'frame')
                if tap is not None:
                    taps.append((tap.card, tap.why[:5], tap.health > 0.6))
                    used.add(tap.card)
        self.assertEqual(taps, [(card, 'lost ', True) for card in cards])

    def test_one_bar_misread_high_is_no_heavy_fire(self):
        misread = [(2.0, 0.72), (2.7, 1.0), (3.4, 0.71), (4.1, 0.70), (4.8, 0.70)]  # one bar read full by mistake
        self.assertEqual(self.pekka_fight(misread), [])

    def test_a_survivor_back_hurt_waits_to_be_hit_again(self):
        # the next stage: she comes back at 40 %, not on fire on the edge of the base
        readings = [(2.0 + 0.8 * k, 0.4) for k in range(10)] + [(10.0, 0.37), (10.8, 0.34)]
        self.assertEqual([t for (t, _hp, _why) in self.pekka_fight(readings)], [10.8])

    def test_no_health_bar_read_the_overcharge_goes_on_time(self):
        taps = self.pekka_fight([(2.0 + 2 * k, None) for k in range(16)])
        self.assertEqual(taps[:1], [(30.0, None, 'no health bar read for 30 s: on time')])
        lost = self.pekka_fight([(2.0, 1.0)] + [(4.0 + 2 * k, None) for k in range(16)])  # read once, then never
        self.assertEqual(lost[:1], [(32.0, None, 'no health bar read for 30 s: on time')])

    def test_heavy_fire_tapped_again_while_her_card_stays_green(self):
        thick = [(2.0, 1.0), (2.7, 0.97), (3.4, 0.86), (4.1, 0.74)] + [(4.8 + 0.7 * k, 0.66) for k in range(6)]
        self.assertEqual([t for (t, _hp, _why) in self.pekka_fight(thick)], [4.1, 6.2, 8.3])  # a lost tap, three tries

    def test_the_bombers_bomb_goes_as_it_lands_then_once_recharged(self):
        bombers = bb_strategy.Abilities()
        step = bb_strategy.Step((709, 688), (0, 0), 0, bb_strategy.PROFILES['bomber'], 'bomber')
        bombers.add(step, 0.0, fired=True)  # tapped as it landed
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', return_value=bb_strategy.READY), \
                patch('app.core.bb_strategy.health', return_value=0.9):
            self.assertIsNone(bombers.next_tap(1.0, 'frame'))  # not twice at once
            self.assertEqual(bombers.next_tap(2.5, 'frame').card, (709, 688))  # green again: again
        lost = self.abilities('bomber', [(709, 688)])  # the landing tap lost: at once when ready
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', return_value=bb_strategy.READY), \
                patch('app.core.bb_strategy.health', return_value=0.4):
            self.assertEqual(lost.next_tap(0.5, 'frame').health, 0.4)

    def test_a_recharging_ability_does_not_starve_the_others(self):
        # at equal health the P.E.K.K.A's one-time Overcharge goes before the Bomber's bomb,
        # which comes back every time it recharges (it went first every poll before)
        abilities = self.abilities('pekka', [(275, 688)])
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', return_value=bb_strategy.READY), \
                patch('app.core.bb_strategy.health', return_value=1.0):
            self.assertIsNone(abilities.next_tap(2.0, 'frame'))  # she lands untouched
            self.assertIsNone(abilities.next_tap(2.5, 'frame'))
        abilities.add(bb_strategy.Step((709, 688), (0, 0), 0, bb_strategy.PROFILES['bomber'], 'bomber'), 0)
        used = set()
        state = lambda frame, card: bb_strategy.USED if card in used else bb_strategy.READY
        taps = []
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', side_effect=state), \
                patch('app.core.bb_strategy.health', return_value=0.4):
            for t in (6.0, 8.5, 11.0):
                tap = abilities.next_tap(t, 'frame')
                taps.append(tap.troop)
                if tap.troop == 'pekka':
                    used.add(tap.card)  # her card turns grey
        self.assertEqual(taps, ['pekka', 'bomber', 'bomber'])

    def test_a_lost_tap_is_tried_again_while_the_card_stays_green(self):
        abilities = self.abilities('pekka', [(275, 688)])
        readings = iter([1.0])  # she lands untouched, then the defences have her at 30 %
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', return_value=bb_strategy.READY), \
                patch('app.core.bb_strategy.health', side_effect=lambda frame, card: next(readings, 0.3)):
            taps = [t for t in (abilities.next_tap(s, 'frame') for s in (2.0, 5.0, 5.5, 6.6, 8.2, 9.8, 12.0)) if t]
        self.assertEqual(len(taps), 3)  # every 1.5 s while still green, three tries at most

    def test_no_tap_while_recharging_and_none_for_a_dead_troop(self):
        bombers = self.abilities('bomber', [(709, 688)])
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', return_value=bb_strategy.RECHARGING):
            self.assertIsNone(bombers.next_tap(10.0, 'frame'))  # red card: wait for green
        witches = self.abilities('witch', [(275, 688), (365, 688)])
        with patch('app.core.bb_strategy.alive', side_effect=lambda frame, card: card != (365, 688)), \
                patch('app.core.bb_strategy.ability_state', return_value=bb_strategy.READY), \
                patch('app.core.bb_strategy.health', return_value=1.0):
            self.assertIsNone(witches.next_tap(8.0, 'frame'))  # not hit yet: no Bat Swarm before 10 s
            self.assertEqual(witches.next_tap(10.0, 'frame').card, (275, 688))
            self.assertEqual([a.card for a in witches.items], [(275, 688)])  # the dead witch's is dropped

    def test_the_machine_charges_and_goes_on_time_then_again(self):
        machine = bb_strategy.Abilities()
        machine.add(bb_strategy.Step((159, 705), (0, 0), 0, bb_strategy.PROFILES[bb_strategy.MACHINE], bb_strategy.MACHINE), 0)
        with patch('app.core.bb_strategy.alive', return_value=True):
            self.assertIsNone(machine.next_tap(12.0, 'frame'))  # tapped early the game says "You need to wait"
            self.assertEqual(machine.next_tap(20.0, 'frame').card, (159, 705))
            self.assertIsNone(machine.next_tap(30.0, 'frame'))
            self.assertEqual(machine.next_tap(40.0, 'frame').card, (159, 705))


if __name__ == '__main__':
    unittest.main()
