"""Builder Base: which troop each card holds, the deploy plan, and a fight played to its end.
Crops of a live 1227x767 GPG battle (no player name in them), PNG like the other 767p ones."""
import itertools
import math
import random
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.config import Config
from app.core import bb_scout, bb_strategy
from app.core.bot import Bot
from app.services.vision import VisionService

FIXTURES = Path(__file__).parent / 'fixtures'
LIFT = 44  # px from a swap button up to its card's tap at 767p


def canvas(name, x, y):
    """A live 1227x767 crop pasted back where it was taken."""
    frame = np.zeros((767, 1227, 3), np.uint8)
    img = cv2.imread(str(FIXTURES / f'{name}.png'))
    frame[y:y + img.shape[0], x:x + img.shape[1]] = img
    Config().set_target_size_from_frame(frame)
    return frame


def make_bot(vision=None):
    bot = Bot.__new__(Bot)
    bot.stop_event = Mock()
    bot.stop_event.is_set.return_value = False
    bot.stop_event.wait.return_value = False
    bot.window = Mock()
    bot.window.screenshot.return_value = np.zeros((767, 1227, 3), np.uint8)
    bot.input = Mock()
    if vision is None:
        vision = Mock()
        vision.find_template_with_confidence.return_value = (None, None, 0.0)
    bot.vision = vision
    bot._update_config_size = Mock()
    return bot


def bar(frame, machine_template=None):
    roi = VisionService.bottom_half_region(frame)
    swaps = VisionService.find_all_template_centers(frame, 'bbswap.png', region=roi, max_matches=12, suppress_pad_frac=0.1)
    mx = VisionService.find_template(frame, machine_template, region=roi)[0] if machine_template else None
    return bb_strategy.read_bar(VisionService, frame, swaps, LIFT, mx)


class BarTests(unittest.TestCase):
    def test_each_card_is_matched_to_its_troop(self):
        frame = canvas('gpg767_bb_bar', 100, 640)  # Battle Machine, five Power P.E.K.K.As, a Bomber
        swaps = sorted(VisionService.find_all_template_centers(frame, 'bbswap.png', region=VisionService.bottom_half_region(frame),
                                                               max_matches=12, suppress_pad_frac=0.1))
        self.assertEqual([bb_strategy.identify(VisionService, frame, s) for s in swaps], ['pekka'] * 5 + ['bomber'])

    def test_six_witches_even_the_selected_card_without_its_swap_button(self):
        cards = bar(canvas('gpg767_bb_witch_bar', 100, 640), 'battlemachine.png')
        self.assertEqual([c.troop for c in cards], ['witch'] * 6)

    def test_next_stage_the_survivor_and_the_reinforcement_not_the_dead(self):
        # stage 2: five witches died (grey cards), one came back without a swap button,
        # a Bomber came as reinforcement; the machine card is the Battle Copter now
        frame = canvas('gpg767_bb_stage2_bar', 100, 640)
        (mx, my) = VisionService.find_template(frame, 'flyingmachine.png', region=VisionService.bottom_half_region(frame))
        self.assertTrue(mx and bb_strategy.alive(frame, (mx, my)))
        cards = bar(frame, 'flyingmachine.png')
        self.assertEqual([c.troop for c in cards], ['witch', 'bomber'])
        self.assertEqual([c.tap for c in cards], [(365, 688), (814, 691)])  # the second card, the one in colour

    def test_next_stage_the_survivors_whose_health_bar_covers_their_portrait(self):
        # stage 2 live: five P.E.K.K.As survived (a health bar over each portrait, no swap
        # button), the Bomber died, a P.E.K.K.A came as reinforcement
        cards = bar(canvas('gpg767_bb_stage2_pekka_bar', 100, 640), 'battlemachine.png')
        self.assertEqual([c.troop for c in cards], ['pekka'] * 6)
        self.assertEqual([c.tap for c in cards], [(275, 688), (365, 688), (455, 688), (545, 688), (634, 688), (814, 691)])

    def test_deployed_cards_are_not_on_the_bar_any_more(self):
        # mid-fight their portraits still match, but their cards are green, red or grey
        for name in ('gpg767_bb_pekka_fight_bar', 'gpg767_bb_witch_fight_bar', 'gpg767_bb_ability_states_bar'):
            self.assertEqual(bar(canvas(name, 100, 640), 'battlemachine.png'), [], name)

    def test_every_troop_of_the_change_troops_menu(self):
        # the menu draws the portraits at the bar's scale: each card is read as a bar card
        # whose swap button would sit under it
        frame = canvas('gpg767_bb_change_troops', 300, 470)
        troops = ['barbarian', 'archer', 'boxer', 'minion', 'bomber', 'babydragon', 'cannoncart', 'witch', 'dropship', 'pekka']
        swaps = [(round(360.2 + 86.2 * i) + 14, 587) for i in range(len(troops))]
        self.assertEqual([bb_strategy.identify(VisionService, frame, s) for s in swaps], troops)

    def test_an_unknown_card_is_no_troop(self):
        frame = canvas('gpg767_bb_bar', 100, 640)
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
        cards = [bb_strategy.Card('bomber', (724, 688))] + [bb_strategy.Card('pekka', (275 + 90 * k, 688)) for k in range(5)]
        steps = bb_strategy.plan(cards, (159, 705), bb_strategy.edge_front(self.EDGE, self.H, rng=self.STILL))
        self.assertEqual([s.troop for s in steps], ['machine'] + ['pekka'] * 5 + ['bomber'])
        self.assertEqual([s.card for s in steps[1:6]], [(275 + 90 * k, 688) for k in range(5)])  # left to right
        self.assertEqual([s.wait for s in steps], [0.0, 0.3, 0.0, 0.0, 0.0, 0.0, 1.0])  # the Bomber once the tanks draw fire
        (along, off) = self.offsets(steps)
        self.assertTrue(all(d <= 1.5 for d in off), off)  # all on the front
        self.assertAlmostEqual(along[0], 0.0, delta=0.002)  # the machine at the entry
        for (got, want) in zip(along[1:6], (0.025, -0.025, 0.05, -0.05, 0.075)):  # the tanks around it, splash apart
            self.assertAlmostEqual(got, want, delta=0.002)
        self.assertAlmostEqual(along[6], 0.0, delta=0.002)  # the Bomber behind them

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


class FightTests(unittest.TestCase):
    def test_return_home_of_the_results_screen(self):
        bot = make_bot(VisionService)
        (x, y) = bot._bb_return_home_point(canvas('gpg767_bb_results', 400, 560), ocr=False)  # art drawn at 0.9
        self.assertTrue(abs(x - 613) <= 15 and abs(y - 648) <= 15)
        self.assertIsNone(bot._bb_return_home_point(canvas('gpg767_bb_fight_bar', 100, 640), ocr=False))

    def test_the_speed_button_while_it_reads_1x(self):
        bot = make_bot(VisionService)
        (x, y) = bot._bb_speed_point(canvas('gpg767_bb_speed_070216', 1080, 400))  # 1:00 left: "1x"
        self.assertTrue(abs(x - 1181) <= 5 and abs(y - 492) <= 5)
        self.assertEqual(bot._bb_speed_point(canvas('gpg767_bb_speed_070606', 1080, 400)), (x, y))  # another battle's
        self.assertIsNone(bot._bb_speed_point(canvas('gpg767_bb_speed_070220', 1080, 400)))  # "4x" already
        self.assertIsNone(bot._bb_speed_point(canvas('gpg767_bb_speed_070146', 1080, 400)))  # earlier: no button

    def test_the_last_minute_is_sped_up_and_a_lost_tap_tried_again(self):
        bot = make_bot()
        clock = itertools.count()  # 2 s a poll
        speed = [None, (1181, 492), (1181, 492), None, None, None]  # 1x; the first tap is lost; then 4x
        with patch('app.core.bot.time.monotonic', side_effect=lambda: next(clock)), \
                patch.object(bot, '_bb_return_home_point', side_effect=[None] * 8 + [(613, 648)]), \
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
        with patch('app.core.bot.time.monotonic', side_effect=lambda: next(clock)), \
                patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.health', return_value=1.0), \
                patch('app.core.bb_strategy.ability_state', return_value=bb_strategy.READY), \
                patch.object(bot, '_bb_return_home_point', side_effect=[None] * 12 + [(613, 648)]), \
                patch('app.core.bot.VisionService.find_all_template_centers', return_value=[]):
            self.assertTrue(bot._bb_fight_to_the_end(abilities))
        taps = [c.args[:2] for c in bot.input.click.call_args_list]
        self.assertEqual(taps[-1], (613, 648))  # only the results screen ends it
        self.assertEqual(set(taps), {(275, 688), (709, 688), (613, 648)})  # nothing else: no End Battle, no Surrender
        self.assertIn(taps.count((275, 688)), (1, 2, 3))  # Overcharge at its latest; retried while the card stays green
        self.assertGreaterEqual(taps.count((709, 688)), 2)  # the Bomber's, again each time its card is green again

    def test_troops_back_on_the_bar_are_deployed_again(self):
        bot = make_bot()
        clock = itertools.count()
        swaps = [[(275, 732)]] + [[]] * 50  # the next stage's reinforcement shows its swap button once
        with patch('app.core.bot.time.monotonic', side_effect=lambda: next(clock)), \
                patch.object(bot, '_bb_return_home_point', side_effect=[None] * 12 + [(613, 648)]), \
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

    def test_a_first_troop_that_does_not_land_goes_again_from_the_next_side(self):
        bot = make_bot()
        pekkas = [bb_strategy.Card('pekka', (275 + 90 * k, 688)) for k in range(2)]
        fronts = [('A', lambda o: (300, 200)), ('B', lambda o: (800, 300)), ('C', lambda o: (500, 500))]
        with patch.object(bot, '_read_bb_bar', side_effect=[(pekkas, (159, 705)), ([], None)]), \
                patch.object(bot, '_bb_fronts', return_value=fronts), \
                patch.object(bot, '_bb_swaps_shown', return_value=True), \
                patch.object(bot, '_bb_landed', side_effect=[False, True]) as landed:
            abilities = bot._deploy_bb_army(np.zeros((767, 1227, 3), np.uint8))
        taps = [c.args[:2] for c in bot.input.click.call_args_list]
        # the machine on side A (a no-deploy spot), again on side B, where everyone follows
        self.assertEqual(taps, [(159, 705), (300, 200), (159, 705), (800, 300), (275, 688), (800, 300), (365, 688), (800, 300)])
        self.assertEqual(landed.call_count, 2)
        self.assertEqual([a.card for a in abilities.items], [(159, 705), (275, 688), (365, 688)])  # the machine's once


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


class CardTests(unittest.TestCase):
    TAPS = [(275 + 90 * k, 688) for k in range(6)]  # the six troop cards of a 1227x767 bar

    def assertHealth(self, got, want):
        self.assertEqual([g is None for g in got], [w is None for w in want], got)
        for (g, w) in zip(got, want):
            if w is not None:
                self.assertAlmostEqual(g, w, delta=0.1)

    def test_health_bars_of_a_live_fight(self):
        pekkas = canvas('gpg767_bb_pekka_fight_bar', 100, 640)  # five P.E.K.K.As and a Bomber, mid-fight
        self.assertHealth([bb_strategy.health(pekkas, t) for t in self.TAPS], [0.65, 0.35, 1.0, 1.0, 0.45, 0.9])
        witches = canvas('gpg767_bb_witch_fight_bar', 100, 640)  # two in the red, two dead, two untouched
        self.assertHealth([bb_strategy.health(witches, t) for t in self.TAPS], [0.13, 1.0, 0.15, None, None, 1.0])
        self.assertEqual([bb_strategy.alive(witches, t) for t in self.TAPS], [True, True, True, False, False, True])
        before = canvas('gpg767_bb_bar', 100, 640)  # not deployed yet: no bar
        self.assertEqual([bb_strategy.health(before, t) for t in self.TAPS], [None] * 6)

    def test_ability_states_read_on_the_cards(self):
        # 19 s into a live fight: P.E.K.K.A 1 used its Overcharge (grey), the others' are ready
        # (green), the Bomber's Bouncing Bomb recharges (red); before the deploy: blue
        frame = canvas('gpg767_bb_ability_states_bar', 100, 640)
        (ready, used, recharging) = (bb_strategy.READY, bb_strategy.USED, bb_strategy.RECHARGING)
        self.assertEqual([bb_strategy.ability_state(frame, t) for t in self.TAPS], [used, ready, ready, ready, ready, recharging])
        before = canvas('gpg767_bb_bar', 100, 640)
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
        hp = {(275, 688): 0.5, (365, 688): 0.2, (455, 688): 0.4}
        used = set()
        state = lambda frame, card: bb_strategy.USED if card in used else bb_strategy.READY
        abilities = self.abilities('pekka', cards)
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', side_effect=state), \
                patch('app.core.bb_strategy.health', side_effect=lambda frame, card: hp[card]):
            self.assertIsNone(abilities.next_tap(3.0, 'frame'))  # engaged, but not before the earliest (4 s)
            first = abilities.next_tap(5.0, 'frame')
            self.assertEqual((first.card, first.health), ((365, 688), 0.2))  # the most hurt
            used.add(first.card)
            self.assertIsNone(abilities.next_tap(5.5, 'frame'))  # not two Overcharges at once
            self.assertEqual(abilities.next_tap(6.3, 'frame').card, (455, 688))
            used.add((455, 688))
            self.assertEqual(abilities.next_tap(7.6, 'frame').card, (275, 688))
            used.add((275, 688))
            self.assertIsNone(abilities.next_tap(30.0, 'frame'))  # their cards turned grey: each one once
            self.assertEqual(abilities.items, [])

    def test_a_lost_tap_is_tried_again_while_the_card_stays_green(self):
        abilities = self.abilities('pekka', [(275, 688)])
        with patch('app.core.bb_strategy.alive', return_value=True), \
                patch('app.core.bb_strategy.ability_state', return_value=bb_strategy.READY), \
                patch('app.core.bb_strategy.health', return_value=0.3):
            taps = [t for t in (abilities.next_tap(s, 'frame') for s in (5.0, 5.5, 6.6, 8.2, 9.8, 12.0)) if t]
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
