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
        with patch('app.core.bot.time.monotonic', side_effect=lambda: next(clock)), \
             patch.object(bot, '_bb_return_home_point', side_effect=[None] * 10 + [(613, 648)]), \
             patch('app.core.bot.VisionService.find_all_template_centers', return_value=[]):
            self.assertTrue(bot._bb_fight_to_the_end([[5, (275, 688), 0], [3, (709, 688), 6]]))
        taps = [c.args[:2] for c in bot.input.click.call_args_list]
        self.assertEqual(taps[-1], (613, 648))  # only the results screen ends it
        self.assertEqual(set(taps), {(275, 688), (709, 688), (613, 648)})  # nothing else: no End Battle, no Surrender
        self.assertEqual(taps.count((275, 688)), 1)  # a one-time ability
        self.assertGreaterEqual(taps.count((709, 688)), 2)  # the Bomber's recharges

    def test_troops_back_on_the_bar_are_deployed_again(self):
        bot = make_bot()
        clock = itertools.count()
        swaps = [[(275, 732)]] + [[]] * 50  # the next stage's cards show their swap buttons once
        with patch('app.core.bot.time.monotonic', side_effect=lambda: next(clock)), \
             patch.object(bot, '_bb_return_home_point', side_effect=[None] * 12 + [(613, 648)]), \
             patch('app.core.bot.VisionService.find_all_template_centers', side_effect=swaps), \
             patch.object(bot, '_deploy_bb_army', return_value=[[10 ** 6, (999, 688), 0]]) as deploy:
            self.assertTrue(bot._bb_fight_to_the_end([[10 ** 6, (275, 688), 0]]))
        deploy.assert_called_once()


if __name__ == '__main__':
    unittest.main()
