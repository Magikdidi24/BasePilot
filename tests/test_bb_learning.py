"""Builder Base results and plan learning: the results screen read on live crops (y 75-700
of a 1227x767 battle: no names in them), the battle history file, the plan learner, and the
bot drawing a plan and scoring it."""
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.config import Config
from app.core import bb_learning, bb_results, bb_scout
from app.core.results_screen import settled_result
from app.services import ppocr
from app.utils import battle_history
from tests.helpers import bare_bot

FIXTURES = Path(__file__).parent / 'fixtures'


def results_frame(name):
    frame = np.zeros((767, 1227, 3), np.uint8)
    frame[75:700] = cv2.imread(str(FIXTURES / f'gpg767_bb_result_{name}.jpg'))
    Config().set_target_size_from_frame(frame)
    return frame


@unittest.skipUnless(ppocr.available(), 'needs the OCR models in app/data/ocr')
class ResultsScreenTests(unittest.TestCase):
    def test_stars_damage_and_rewards(self):
        want = {'75_1': (1, 75, 30000, 9), '93_2': (2, 93, 72000, 20), '142_3': (3, 142, 122000, 31),
                '158_3': (3, 158, 142000, 37)}  # the 158 % one has two silver stars and a gold one
        for (name, (stars, damage, gold, trophies)) in want.items():
            self.assertEqual(bb_results.read_result(results_frame(name)), bb_results.BattleResult(stars, damage, gold, trophies), name)

    def test_the_screen_is_read_once_its_animation_is_over(self):
        # the damage counts up from 0 % and the stars come one by one: two reads must agree
        now = [0.0]

        def wait(seconds):
            now[0] += seconds
            return False
        frames = [results_frame('counting')] * 2 + [results_frame('142_3')] * 8
        result = settled_result(lambda: frames.pop(0), wait, bb_results.read_result, monotonic=lambda: now[0])
        self.assertEqual((result.stars, result.damage), (3, 142))
        self.assertGreaterEqual(now[0], 2.0)  # 0 % twice at first sight is no result
        still = [results_frame('counting')] * 30  # a battle that really ends at 0 %
        self.assertEqual(settled_result(lambda: still.pop(0), wait, bb_results.read_result, monotonic=lambda: now[0]).damage, 0)

    def test_another_screen_reads_as_none(self):
        self.assertIsNone(bb_results.read_result(np.zeros((767, 1227, 3), np.uint8)))


class HistoryTests(unittest.TestCase):
    def test_records_go_in_one_line_each_and_come_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'battles.jsonl'
            battle_history.append({'village': 'builder', 'damage': 142}, path)
            with open(path, 'a', encoding='utf-8') as f:
                f.write('not json\n')
            battle_history.append({'village': 'home', 'gold': 300000}, path)
            records = battle_history.load(path)
        self.assertEqual([r['village'] for r in records], ['builder', 'home'])
        self.assertTrue(all('t' in r for r in records))
        self.assertEqual(battle_history.load(Path(d) / 'missing.jsonl'), [])


class PlanLearnerTests(unittest.TestCase):
    def test_the_players_play_comes_first_for_a_pekka_push(self):
        learner = bb_learning.PlanLearner()
        rng = random.Random(1)
        picks = [learner.choose('pekka', ['best', 'core', 'reach', 'mortar'], rng) for _ in range(200)]
        self.assertEqual(max(set(picks), key=picks.count), 'mortar')
        self.assertGreater(len(set(picks)), 1)  # the others get their chance

    def test_the_plan_that_wins_gets_played_more(self):
        learner = bb_learning.PlanLearner()
        for _ in range(15):
            learner.record('pekka', 'mortar', 70)
            learner.record('pekka', 'core', 175)
        rng = random.Random(2)
        picks = [learner.choose('pekka', ['best', 'core', 'reach', 'mortar'], rng) for _ in range(200)]
        self.assertGreater(picks.count('core'), 140)

    def test_each_stage_scores_its_own_plan(self):
        learner = bb_learning.PlanLearner()
        learner.record_battle('pekka', 'mortar', 'best', 200)
        learner.record_battle('pekka', 'core', None, 80)  # the first base not cleared: no second stage
        # first stage, of the whole 200 %: (7 + 1) / 11 and (3 + 0.4) / 7
        self.assertEqual(learner.summary('pekka', ['mortar', 'core']), 'mortar 145 % (1), core 97 % (1)')
        # second stage, its share over 100 %: 100 + (3 + 1) / 7 x 100; core never played there
        self.assertEqual(learner.summary('pekka', ['best', 'core'], stage=2), 'best 157 % (1), core 150 % (0)')

    def test_beliefs_come_from_the_history(self):
        records = [{'t': 'x', 'village': 'builder', 'army': 'other', 'plan': 'reach', 'damage': 160},  # one plan: the second stage's
                   {'t': 'x', 'village': 'builder', 'army': 'other', 'plan': 'core', 'damage': 50},  # one plan, the first base only
                   {'t': 'x', 'village': 'builder', 'army': 'other', 'plan': 'best', 'plan1': 'core', 'plan2': 'best', 'damage': 200},
                   {'t': 'x', 'village': 'home', 'gold': 1}, {'t': 'x', 'village': 'builder', 'plan': 'bogus', 'damage': 10}]
        learner = bb_learning.PlanLearner.from_history(records)
        self.assertEqual(learner.summary('other', ['reach', 'core', 'best']), 'reach 100 % (0), core 106 % (2), best 100 % (0)')
        self.assertEqual(learner.summary('other', ['reach', 'core', 'best'], stage=2), 'reach 151 % (1), core 150 % (0), best 157 % (1)')


def make_bot():
    bot = bare_bot()
    bot._update_config_size = Mock()
    return bot


class BotPlanTests(unittest.TestCase):
    def battle(self, name):
        frame = np.zeros((767, 1227, 3), np.uint8)
        frame[70:630] = cv2.imread(str(FIXTURES / f'gpg767_bb_scout_{name}.jpg'))
        return frame

    def test_the_drawn_plan_picks_the_side(self):
        frame = self.battle('green_middle')  # it has a Multi Mortar at (717, 415)
        pekkas = [Mock(troop='pekka')]
        towards = bb_scout.towards
        for (plan, check) in (('mortar', lambda e, s: e[0] == bb_scout.towards(s, (717, 415), rng=random.Random(0))[0]),
                              ('core', lambda e, s: True), ('reach', lambda e, s: True)):
            bot = make_bot()
            bot._bb_plans = Mock()
            bot._bb_plans.choose.return_value = plan
            bot._bb_plans.summary.return_value = ''
            with patch('app.core.bot.bb_scout.towards', side_effect=lambda s, t, rng=None: towards(s, t, rng=random.Random(0))):
                (scouting, entries) = bot._bb_plan_entries(frame, pekkas)
            self.assertEqual(bot._bb_stage_plans[1], ('pekka', plan))
            self.assertTrue(entries and check(entries, scouting), plan)
            self.assertEqual(sorted(bot._bb_plans.choose.call_args.args[1]), ['best', 'core', 'mortar', 'reach'])

    def test_the_second_stage_draws_its_own_plan_and_a_redeploy_keeps_it(self):
        bot = make_bot()
        bot._bb_plans = Mock()
        bot._bb_plans.choose.return_value = 'core'
        bot._bb_plans.summary.return_value = ''
        bot._bb_stage_plans = {1: ('pekka', 'mortar')}
        frame = self.battle('blue_middle')
        bot._bb_plan_entries(frame, [Mock(troop='witch')], 2)
        self.assertEqual(bot._bb_plans.choose.call_args.kwargs['stage'], 2)
        self.assertEqual(bot._bb_stage_plans[2], ('pekka', 'core'))  # the battle's army: the first stage's
        bot._bb_plan_entries(frame, [Mock(troop='witch')], 2)  # troops back on the bar within the stage
        bot._bb_plans.choose.assert_called_once()

    def test_the_result_scores_the_plan_and_goes_in_the_history(self):
        bot = make_bot()
        bot._bb_plans = bb_learning.PlanLearner()
        bot._bb_stage_plans = {1: ('pekka', 'mortar'), 2: ('pekka', 'core')}
        result = bb_results.BattleResult(3, 158, 142000, 37)
        with patch('app.core.bot.results_screen.settled_result', return_value=result), \
                patch('app.core.bot.battle_history.append') as append:
            bot._bb_record_result(0.0)
        record = append.call_args.args[0]
        self.assertEqual((record['village'], record['plan'], record['plan1'], record['plan2'], record['army'], record['damage'], record['stars']),
                         ('builder', 'core', 'mortar', 'core', 'pekka', 158, 3))
        # the opening (the Multi Mortar's side) gets the battle, the second base's plan its share
        self.assertEqual(bot._bb_plans.summary('pekka', ['mortar']), 'mortar 142 % (1)')
        self.assertEqual(bot._bb_plans.summary('pekka', ['core'], stage=2), 'core 151 % (1)')


if __name__ == '__main__':
    unittest.main()
