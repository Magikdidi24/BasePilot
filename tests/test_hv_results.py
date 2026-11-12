"""Home Village results and the learned Earthquake placement: the results screen read on
live crops (x 380-860, y 20-480 of a 1227x767 raid: no names in them), the raid's share of
the base's loot, the placement learner, and the bot drawing a placement and scoring it."""
import itertools
import random
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.core import bb_learning, hv_results
from app.core.bot import Bot
from app.core.results_screen import settled_result
from app.services import ppocr
from app.utils.profile_settings_store import (EARTHQUAKE_METHOD_CURVE, EARTHQUAKE_METHOD_LEARN, EARTHQUAKE_METHOD_RANDOM,
                                              _normalize_earthquake_method)

FIXTURES = Path(__file__).parent / 'fixtures'


def results_frame(name):
    frame = np.zeros((767, 1227, 3), np.uint8)
    frame[20:480, 380:860] = cv2.imread(str(FIXTURES / f'gpg767_hv_result_{name}.jpg'))
    return frame


@unittest.skipUnless(ppocr.available(), 'needs OpenCV DNN and the model in app/data/ocr')
class ResultsScreenTests(unittest.TestCase):
    def test_stars_damage_and_loot(self):
        self.assertEqual(hv_results.read_result(results_frame('54_1')), hv_results.HomeResult(1, 54, 283551, 347568, 2758))

    def test_the_numbers_are_cut_out_of_the_base(self):
        # live: a gold-coloured building left of the gold read as a "U" in a wider crop
        self.assertEqual(hv_results.read_result(results_frame('counting')), hv_results.HomeResult(1, 0, 0, 0, 0))

    def test_other_window_sizes(self):
        frame = results_frame('54_1')
        for size in ((1440, 900), (1920, 1200)):
            big = cv2.resize(frame, size, interpolation=cv2.INTER_CUBIC)
            self.assertEqual(hv_results.read_result(big), hv_results.HomeResult(1, 54, 283551, 347568, 2758), size)

    def test_the_screen_is_read_once_its_count_is_over(self):
        now = [0.0]

        def wait(seconds):
            now[0] += seconds
            return False
        frames = [results_frame('counting')] * 2 + [results_frame('54_1')] * 8
        result = settled_result(lambda: frames.pop(0), wait, hv_results.read_result, monotonic=lambda: now[0])
        self.assertEqual((result.damage, result.gold), (54, 283551))

    def test_another_screen_reads_as_none(self):
        self.assertIsNone(hv_results.read_result(np.zeros((767, 1227, 3), np.uint8)))


class StarTests(unittest.TestCase):
    def test_each_lit_star_counts(self):
        frame = np.zeros((767, 1227, 3), np.uint8)
        self.assertEqual(hv_results.stars(frame), 0)
        for (n, ((dx, y), half)) in enumerate(hv_results._STARS, 1):
            (cx, cy, r) = (int(613 + dx * 767), int(y * 767), int(half * 767))
            frame[cy - r:cy + r, cx - r:cx + r] = 230  # a silver star's body
            self.assertEqual(hv_results.stars(frame), n)


class LootShareTests(unittest.TestCase):
    def test_share_of_the_gold_and_elixir_the_base_held(self):
        result = hv_results.HomeResult(1, 54, 300000, 200000, 2000)
        # what was left at the end: the won plus it is what the base held
        self.assertAlmostEqual(hv_results.loot_share(result, left=(300000, 200000, 6000)), 0.5)
        self.assertAlmostEqual(hv_results.loot_share(result, left=(300000, 200000, 6000), held=(7000000, 400000, 8000)), 0.5)
        self.assertAlmostEqual(hv_results.loot_share(result, held=(600000, 400000, 8000)), 0.5)  # a sneaky raid: no reads during it
        self.assertEqual(hv_results.loot_share(result, held=(100000, 100000, 0)), 1.0)  # capped
        self.assertIsNone(hv_results.loot_share(result))
        self.assertIsNone(hv_results.loot_share(hv_results.HomeResult(1, 54, None, 200000), left=(1, 1, 0)))


class QuakeLearnerTests(unittest.TestCase):
    def test_both_placements_get_tried_at_first(self):
        learner = bb_learning.QuakeLearner()
        rng = random.Random(3)
        picks = [learner.choose('valkyrie', bb_learning.QUAKES, rng) for _ in range(200)]
        self.assertGreater(picks.count('curve'), 60)
        self.assertGreater(picks.count('random'), 60)

    def test_the_placement_that_loots_more_gets_played_more(self):
        records = [{'village': 'home', 'army': 'valkyrie', 'plan': 'random', 'loot': 75} for _ in range(12)]
        records += [{'village': 'home', 'army': 'valkyrie', 'plan': 'curve', 'loot': 45} for _ in range(12)]
        records += [{'village': 'home', 'gold': 300000}]  # a raid whose results screen was not read
        records += [{'village': 'builder', 'plan': 'best', 'damage': 150}]
        learner = bb_learning.QuakeLearner.from_history(records)
        rng = random.Random(4)
        picks = [learner.choose('valkyrie', bb_learning.QUAKES, rng) for _ in range(200)]
        self.assertGreater(picks.count('random'), 160)
        # 12 raids each at 45 % and 75 %, pulled towards the 50 % they started at
        self.assertEqual(learner.summary('valkyrie', bb_learning.QUAKES), 'curve 47 % (12), random 67 % (12)')
        self.assertEqual(learner.summary('sneaky', ['curve']), 'curve 50 % (0)')  # per army


class SettingTests(unittest.TestCase):
    def test_learn_is_kept(self):
        self.assertEqual(_normalize_earthquake_method(EARTHQUAKE_METHOD_LEARN), EARTHQUAKE_METHOD_LEARN)
        self.assertEqual(_normalize_earthquake_method('learn'), EARTHQUAKE_METHOD_LEARN)
        self.assertEqual(_normalize_earthquake_method('Random Placement'), EARTHQUAKE_METHOD_RANDOM)
        self.assertEqual(_normalize_earthquake_method(None), EARTHQUAKE_METHOD_CURVE)


def make_bot():
    bot = Bot.__new__(Bot)
    bot.stop_event = Mock()
    bot.stop_event.is_set.return_value = False
    bot.stop_event.wait.return_value = False
    bot.window = Mock()
    bot.window.screenshot.return_value = np.zeros((767, 1227, 3), np.uint8)
    bot.input = Mock()
    bot.vision = Mock()
    bot._update_config_size = Mock()
    bot._session_id = '2026-11-11T20:00:00'
    return bot


class BotTests(unittest.TestCase):
    def test_a_fixed_placement_is_played_and_kept_for_the_result(self):
        bot = make_bot()
        bot._earthquake_method = EARTHQUAKE_METHOD_RANDOM
        self.assertEqual(bot._quake_placement(3), EARTHQUAKE_METHOD_RANDOM)
        self.assertEqual(bot._hv_quake, ('valkyrie', 'random'))

    def test_learn_draws_the_placement(self):
        bot = make_bot()
        bot._earthquake_method = EARTHQUAKE_METHOD_LEARN
        bot._hv_quakes = Mock()
        bot._hv_quakes.choose.return_value = 'random'
        bot._hv_quakes.summary.return_value = ''
        self.assertEqual(bot._quake_placement(1), EARTHQUAKE_METHOD_RANDOM)
        bot._hv_quakes.choose.assert_called_once_with('sneaky', bb_learning.QUAKES)
        self.assertEqual(bot._hv_quake, ('sneaky', 'random'))

    @patch('app.core.bot.battle_history.append')
    def test_the_result_is_written_and_scores_the_placement(self, append):
        bot = make_bot()
        result = hv_results.HomeResult(2, 71, 300000, 200000, 2000)
        bot._hv_quake = ('valkyrie', 'curve')
        bot._hv_loot_left = (300000, 200000, 6000)
        bot._hv_quakes = bb_learning.QuakeLearner()
        with patch('app.core.bot.hv_results.read_result', return_value=result), \
                patch('app.core.bot.results_screen.settled_result', return_value=result):
            self.assertEqual(bot._hv_record_result(), result)
        record = append.call_args.args[0]
        self.assertEqual({k: record[k] for k in ('village', 'stars', 'damage', 'gold', 'elixir', 'dark', 'army', 'plan', 'loot')},
                         {'village': 'home', 'stars': 2, 'damage': 71, 'gold': 300000, 'elixir': 200000, 'dark': 2000,
                          'army': 'valkyrie', 'plan': 'curve', 'loot': 50})
        self.assertEqual(bot._hv_quakes.summary('valkyrie', ['curve']), 'curve 50 % (1)')
        self.assertTrue(bot._hv_result_recorded)

    @patch('app.core.bot.battle_history.append')
    def test_no_results_screen_writes_nothing(self, append):
        bot = make_bot()
        self.assertIsNone(bot._hv_record_result())  # a black frame: no damage to read
        append.assert_not_called()
        self.assertLessEqual(bot.window.screenshot.call_count, 2)  # no settling on another screen

    @patch('app.core.bot.battle_history.append')
    def test_the_hud_loot_is_written_only_for_a_raid_without_results(self, append):
        bot = make_bot()
        (bot._loot_totals, bot._loot_prev_resources, bot._loot_callback) = ((0, 0, 0), (1000000, 1000000, 10000), None)
        bot._suppress_loot_negative_error_once = False
        bot._hv_result_recorded = True
        bot._record_loot((1300000, 1200000, 12000))
        append.assert_not_called()  # the results screen wrote this raid
        self.assertEqual(bot._loot_totals, (300000, 200000, 2000))  # the session totals still count it
        bot._record_loot((1500000, 1400000, 13000))
        self.assertEqual(append.call_args.args[0]['gold'], 200000)


class FirstReadTests(unittest.TestCase):
    def test_a_misread_first_is_not_taken_for_the_loot(self):
        bot = make_bot()
        polls = itertools.count()
        state = {'poll': 0}

        def screenshot():
            state['poll'] = next(polls)
            return np.zeros((767, 1227, 3), np.uint8)
        bot.window.screenshot.side_effect = screenshot
        bot.vision.find_template.side_effect = lambda f, name, **kw: (600, 650) if name == 'endbattle.png' else (None, None)
        bot._battle_rewards = None
        # a high misread first (live: 709379 read 7093790), then the loot drops for 20 s
        reads = [(7093790, 597951, 5639)] + [(735196 - 10000 * k, 597951 - 8000 * k, 5639) for k in range(20)] + [(535196, 437951, 5639)] * 40
        with patch('app.core.bot.time.monotonic', side_effect=lambda: float(state['poll'])), \
                patch('app.core.bot.read_enemy_loot', side_effect=lambda f: reads.pop(0) if reads else None):
            bot._play_out_battle()
        self.assertGreaterEqual(bot.window.screenshot.call_count, 20 + 12)  # the misread did not end it at 12 s
        self.assertEqual(bot._hv_loot_left, (535196, 437951, 5639))  # what the base still held at the end


if __name__ == '__main__':
    unittest.main()
