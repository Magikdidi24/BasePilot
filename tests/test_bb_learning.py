"""Builder Base results and plan learning: the results screen read on live crops (y 75-700
of a 1227x767 battle: no names in them), the battle history file, the plan learner, and the
bot drawing a plan and scoring it."""
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.core import bb_learning, bb_results, bb_scout
from app.core.results_screen import settled_result
from app.services import ppocr
from app.utils import battle_history
from tests.helpers import bare_bot, canvas

FIXTURES = Path(__file__).parent / 'fixtures'


def results_frame(name):
    return canvas((f'gpg767_bb_result_{name}.jpg', 0, 75))


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


MM = bb_learning.bases('pekka', True)  # a P.E.K.K.A push's beliefs on bases with a Multi Mortar seen


def battle(plan1, damage, plan2=None, army='pekka', mortar=None, front=0, alike1=None, alike2=None):
    """A Builder Base battle's history record, played since the sides were fixed."""
    record = {'t': 'x', 'village': 'builder', 'army': army, 'damage': damage, 'plan1': plan1,
              's1': {'side': 'top', 'mortar': mortar, 'front': front, 'plans': alike1 or [plan1]}}
    if plan2:
        record.update(plan2=plan2, s2={'side': 'left', 'mortar': mortar, 'front': 0, 'plans': alike2 or [plan2]})
    return record


class PlanLearnerTests(unittest.TestCase):
    def test_the_players_play_comes_first_on_a_base_with_a_multi_mortar(self):
        learner = bb_learning.PlanLearner()
        rng = random.Random(1)
        picks = [learner.choose(MM, ['best', 'core', 'reach', 'mortar'], rng) for _ in range(200)]
        self.assertEqual(max(set(picks), key=picks.count), 'mortar')
        self.assertGreater(len(set(picks)), 1)  # the others get their chance

    def test_the_plan_that_wins_gets_played_more(self):
        learner = bb_learning.PlanLearner()
        for _ in range(15):
            learner.add(battle('mortar', 70, mortar=0.1))
            learner.add(battle('core', 175, mortar=0.3))
        rng = random.Random(2)
        picks = [learner.choose(MM, ['best', 'core', 'reach', 'mortar'], rng) for _ in range(200)]
        self.assertGreater(picks.count('core'), 140)

    def test_each_stage_scores_its_own_damage_on_its_kind_of_base(self):
        learner = bb_learning.PlanLearner()
        learner.add(battle('mortar', 200, 'best', mortar=0.1))
        learner.add(battle('core', 80))  # the first base not cleared, no Multi Mortar on it
        # first stage, its damage up to 100 %: (7 + 1) / 11 with a Multi Mortar, (3 + 0.8) / 7 without
        self.assertEqual(learner.summary(MM, ['mortar', 'core']), 'mortar 73 % (1), core 50 % (0)')
        self.assertEqual(learner.summary('pekka', ['core']), 'core 54 % (1)')
        # second stage, the damage over 100 %: (3 + 1) / 7; core never played there
        self.assertEqual(learner.summary(MM, ['best', 'core'], stage=2), 'best 57 % (1), core 50 % (0)')

    def test_plans_that_go_in_from_the_same_side_score_together(self):
        learner = bb_learning.PlanLearner()
        learner.add(battle('core', 100, alike1=['best', 'core']))  # reach went in elsewhere on that base
        self.assertEqual(learner.summary('pekka', ['best', 'core', 'reach']), 'best 57 % (1), core 57 % (1), reach 50 % (0)')

    def test_a_stage_off_its_plans_side_scores_nothing(self):
        learner = bb_learning.PlanLearner()
        learner.add(battle('best', 100, front=1))  # the opening landed on the next side
        self.assertEqual(learner.summary('pekka', ['best']), 'best 50 % (0)')

    def test_only_the_newest_battles_count(self):
        learner = bb_learning.PlanLearner.from_history([battle('core', 100)] * 40 + [battle('core', 0)] * 40)
        self.assertEqual(learner.summary('pekka', ['core']), 'core 7 % (40)')  # 3 / 46: the 40 cleared bases are gone
        learner.add(battle('core', 100))  # live, the window slides on
        self.assertEqual(learner.summary('pekka', ['core']), 'core 9 % (40)')  # 4 / 46

    def test_beliefs_come_from_the_battles_with_their_sides(self):
        records = [{'t': 'x', 'village': 'builder', 'army': 'pekka', 'plan': 'core', 'plan1': 'core', 'damage': 100},  # a side drawn at random
                   battle('reach', 160, 'core', army='other'),
                   {'t': 'x', 'village': 'home', 'gold': 1}, battle('bogus', 10)]
        learner = bb_learning.PlanLearner.from_history(records)
        self.assertEqual(learner.summary('pekka', ['core']), 'core 50 % (0)')
        self.assertEqual(learner.summary('other', ['reach']), 'reach 57 % (1)')  # (3 + 1) / 7
        self.assertEqual(learner.summary('other', ['core'], stage=2), 'core 51 % (1)')  # (3 + 0.6) / 7


def make_bot():
    bot = bare_bot()
    bot._update_config_size = Mock()
    return bot


class BotPlanTests(unittest.TestCase):
    def battle(self, name):
        frame = np.zeros((767, 1227, 3), np.uint8)
        frame[70:630] = cv2.imread(str(FIXTURES / f'gpg767_bb_scout_{name}.jpg'))
        return frame

    def test_the_drawn_plan_picks_its_side(self):
        frame = self.battle('green_middle')  # it has a Multi Mortar at (717, 415)
        pekkas = [Mock(troop='pekka')]
        towards = bb_scout.towards
        scouting = bb_scout.scout(frame)
        sides = {'best': scouting.entries[0], 'core': bb_scout.scout(frame, core_weight=3.0).entries[0],
                 'reach': bb_scout.scout(frame, core_weight=0.3).entries[0],
                 'mortar': towards(scouting, bb_scout.multi_mortar(frame, scouting), rng=random.Random(0))[0]}
        for (plan, side) in sides.items():
            bot = make_bot()
            bot._bb_plans = Mock()
            bot._bb_plans.choose.return_value = plan
            bot._bb_plans.summary.return_value = ''
            with patch('app.core.bot.bb_scout.towards', side_effect=lambda s, t, rng=None: towards(s, t, rng=random.Random(0))):
                (_scouting, entries, mortar, alike) = bot._bb_plan_entries(frame, pekkas)
            self.assertEqual(bot._bb_stage_plans[1], ('pekka', plan))
            self.assertEqual(entries[0], side, plan)
            self.assertLessEqual(math.dist(mortar, (717, 415)), 8)
            self.assertEqual(bot._bb_plans.choose.call_args.args[:2], (MM, ['best', 'core', 'reach', 'mortar']))
            # every plan whose side is within reach of this one is the same attack
            self.assertEqual(alike, [p for p in sides if math.dist(sides[p], side) < 0.15 * 767], plan)

    def test_plans_that_go_in_elsewhere_are_not_alike(self):
        frame = self.battle('green_left')  # reach goes in from the bottom right there, the others from the top
        bot = make_bot()
        bot._bb_plans = Mock()
        bot._bb_plans.choose.return_value = 'best'
        bot._bb_plans.summary.return_value = ''
        (_scouting, _entries, _mortar, alike) = bot._bb_plan_entries(frame, [Mock(troop='witch')])
        self.assertIn('core', alike)
        self.assertNotIn('reach', alike)

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

    def test_the_result_scores_the_sides_and_goes_in_the_history(self):
        bot = make_bot()
        bot._bb_plans = bb_learning.PlanLearner()
        bot._bb_stage_plans = {1: ('pekka', 'mortar'), 2: ('pekka', 'core')}
        bot._bb_stage_sides = {1: {'side': 'top', 'reach': 1.0, 'core': 0.33, 'mortar': 0.1, 'plans': ['mortar'], 'front': 0},
                               2: {'side': 'left', 'reach': 0.9, 'core': 0.2, 'mortar': None, 'plans': ['best', 'core'], 'front': 0}}
        result = bb_results.BattleResult(3, 158, 142000, 37)
        with patch('app.core.bot.results_screen.settled_result', return_value=result), \
                patch('app.core.bot.battle_history.append') as append:
            bot._bb_record_result(0.0)
        record = append.call_args.args[0]
        self.assertEqual((record['village'], record['plan'], record['plan1'], record['plan2'], record['army'], record['damage'], record['stars']),
                         ('builder', 'core', 'mortar', 'core', 'pekka', 158, 3))
        self.assertEqual((record['s1'], record['s2']), (bot._bb_stage_sides[1], bot._bb_stage_sides[2]))
        # the first base cleared from the Multi Mortar's side: (7 + 1) / 11; the second base's
        # 58 %, to both plans that went in from its side: (3 + 0.58) / 7
        self.assertEqual(bot._bb_plans.summary(MM, ['mortar']), 'mortar 73 % (1)')
        self.assertEqual(bot._bb_plans.summary('pekka', ['best', 'core'], stage=2), 'best 51 % (1), core 51 % (1)')


if __name__ == '__main__':
    unittest.main()
