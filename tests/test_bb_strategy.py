"""Builder Base: which troop each card holds, the deploy plan, and a fight played to its end.
Crops of a live 1227x767 GPG battle (no player name in them), PNG like the other 767p ones."""
import itertools
import random
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.config import Config
from app.core import bb_strategy
from app.core.bot import Bot
from app.services.vision import VisionService

FIXTURES = Path(__file__).parent / 'fixtures'


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
    bot.vision = vision or Mock()
    bot._update_config_size = Mock()
    return bot


class BarTests(unittest.TestCase):
    def test_each_card_is_matched_to_its_troop(self):
        frame = canvas('gpg767_bb_bar', 100, 640)  # Battle Machine, five Power P.E.K.K.As, a Bomber
        swaps = sorted(VisionService.find_all_template_centers(frame, 'bbswap.png', region=VisionService.bottom_half_region(frame),
                                                               max_matches=12, suppress_pad_frac=0.1))
        self.assertEqual([bb_strategy.identify(VisionService, frame, s) for s in swaps], ['pekka'] * 5 + ['bomber'])

    def test_six_witches_even_the_selected_card_without_its_swap_button(self):
        frame = canvas('gpg767_bb_witch_bar', 100, 640)
        swaps = VisionService.find_all_template_centers(frame, 'bbswap.png', region=VisionService.bottom_half_region(frame),
                                                        max_matches=12, suppress_pad_frac=0.1)
        (mx, _my) = VisionService.find_template(frame, 'battlemachine.png', region=VisionService.bottom_half_region(frame))
        cards = bb_strategy.read_bar(VisionService, frame, swaps, 44, mx)
        self.assertEqual([c.troop for c in cards], ['witch'] * 6)

    def test_next_stage_the_survivor_and_the_reinforcement_not_the_dead(self):
        # stage 2: five witches died (grey cards), one came back without a swap button,
        # a Bomber came as reinforcement; the machine card is the Battle Copter now
        frame = canvas('gpg767_bb_stage2_bar', 100, 640)
        roi = VisionService.bottom_half_region(frame)
        swaps = VisionService.find_all_template_centers(frame, 'bbswap.png', region=roi, max_matches=12, suppress_pad_frac=0.1)
        (mx, my) = VisionService.find_template(frame, 'flyingmachine.png', region=roi)
        self.assertTrue(mx and bb_strategy.alive(frame, (mx, my)))
        cards = bb_strategy.read_bar(VisionService, frame, swaps, 44, mx)
        self.assertEqual([c.troop for c in cards], ['witch', 'bomber'])
        self.assertTrue(abs(cards[0].tap[0] - 351) <= 20)  # the second card, the one in colour

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
    def test_the_machine_tanks_then_each_troop_in_its_order(self):
        cards = [bb_strategy.Card('bomber', (709, 688)), bb_strategy.Card('pekka', (275, 688)),
                 bb_strategy.Card('', (900, 688)), bb_strategy.Card('pekka', (364, 688))]
        steps = bb_strategy.plan(cards, (159, 705), (500, 200), [(300, 300), (900, 300)], 767, rng=random.Random(1))
        self.assertEqual([s.card for s in steps], [(159, 705), (275, 688), (364, 688), (709, 688), (900, 688)])
        # the machine, the P.E.K.K.As and the Bomber push together; the unknown troop takes a front slot
        self.assertTrue(all(abs(s.point[0] - 500) <= 10 and abs(s.point[1] - 200) <= 10 for s in steps[:4]))
        self.assertEqual(steps[4].point, (300, 300))
        self.assertEqual([s.wait for s in steps], [0.0, 0.4, 0.0, 1.5, 0.3])  # the Bomber waits behind the tanks


class FightTests(unittest.TestCase):
    def test_return_home_of_the_results_screen(self):
        bot = make_bot(VisionService)
        (x, y) = bot._bb_return_home_point(canvas('gpg767_bb_results', 400, 560), ocr=False)  # art drawn at 0.9
        self.assertTrue(abs(x - 613) <= 15 and abs(y - 648) <= 15)
        self.assertIsNone(bot._bb_return_home_point(canvas('gpg767_bb_fight_bar', 100, 640), ocr=False))

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
