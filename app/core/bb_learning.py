'''Which Builder Base attack plan wins, learned from the battles played.

A plan is how the side of the base is picked (:mod:`app.core.bb_scout`):

- ``best``: the scouting's blend of buildings in reach and nearness to the core;
- ``core``: the side nearest the core (where the Builder Hall usually is);
- ``reach``: the side with the most buildings in reach;
- ``mortar``: the Multi Mortar's side (a P.E.K.K.A push with a Multi Mortar found).

A battle has two stages, two bases, and each stage draws its own plan: the first stage's
plan is scored by the battle's total damage (0-200 %: what it destroyed, and the troops it
left alive for the second base), the second stage's by its own share of it (the damage over
100 %). Before November 2026 a battle scored only the plan of its last stage with its whole
damage: a first stage's Multi Mortar push that cleared the base credited the plan drawn for
the second one (live: 5 battles in 19, the Multi Mortar seen at 72 % on its two failures
while its seven openings averaged about 150 %). Those records count for the stage they can
only belong to: the first under 100 %, the second from 100 % up.

The plan of a stage is drawn by Thompson sampling: each plan's share is a Beta belief, one
draw each, the highest plays. Plans that win get played more, the others now and then, so a
plan that starts badly still gets its chance. A plan never played starts believed at half
its stage (as if six battles at 50 %); the player's own play for a P.E.K.K.A push (the Multi
Mortar first) at 70 % (ten battles' worth): at the first stage it leads the draws at first,
and yields to a plan that does clearly better (175 % against its 70 %, 15 battles each: the
other leads the draws). Beliefs are kept per army (a P.E.K.K.A push, or any other).

The Home Village's Earthquake placement is learned the same way (:class:`QuakeLearner`).
'''
import random

PLANS = ('best', 'core', 'reach', 'mortar')
PEKKA = 'pekka'
OTHER = 'other'
_PRIOR = (3.0, 3.0)  # (alpha, beta) of a plan never played
_PRIORS = {(PEKKA, 'mortar'): (7.0, 3.0)}
FIRST = 1
SECOND = 2


class _Learner:
    '''Thompson sampling over plans, per army and stage: Beta beliefs of each plan's share.'''
    village = None  # the history records it learns from
    plans = ()
    priors = {}

    def __init__(self):
        self._beliefs = {}  # (army, stage, plan) -> [alpha, beta, battles]

    @classmethod
    def from_history(cls, records):
        learner = cls()
        for r in records:
            if r.get('village') == cls.village:
                for (army, stage, plan, share) in cls.scores(r):
                    learner._add(army, stage, plan, share)
        return learner

    @classmethod
    def scores(cls, record):
        '''``(army, stage, plan, share)`` the history ``record`` scores.'''
        raise NotImplementedError

    def _belief(self, army, stage, plan):
        if (army, stage, plan) not in self._beliefs:
            (a, b) = self.priors.get((army, plan), _PRIOR)
            self._beliefs[(army, stage, plan)] = [a, b, 0]
        return self._beliefs[(army, stage, plan)]

    def _add(self, army, stage, plan, share):
        share = min(1.0, max(0.0, float(share)))
        belief = self._belief(army, stage, plan)
        belief[0] += share
        belief[1] += 1.0 - share
        belief[2] += 1

    def choose(self, army, available, rng = random, stage = FIRST):
        '''One of ``available`` plans, by a draw from each one's belief.'''
        draws = [(rng.betavariate(*self._belief(army, stage, p)[:2]), p) for p in available]
        return max(draws)[1]

    def _expected(self, share, stage):
        raise NotImplementedError

    def summary(self, army, available, stage = FIRST):
        '''"mortar 140 % (3), best 100 % (0)": each plan's expected score and its battles,
        for the log.'''
        parts = []
        for p in available:
            (a, b, n) = self._belief(army, stage, p)
            parts.append(f'{p} {self._expected(a / (a + b), stage):.0f} % ({n})')
        return ', '.join(parts)


class PlanLearner(_Learner):
    '''The Builder Base's plans, per army and stage, scored by the battle's damage.'''
    village = 'builder'
    plans = PLANS
    priors = _PRIORS

    @staticmethod
    def _share(damage, stage):
        return damage / 200.0 if stage == FIRST else (damage - 100.0) / 100.0

    def _expected(self, share, stage):
        '''The battle's damage the share stands for: the first stage's of 200 %, the second
        stage's over the first base's 100 %.'''
        return 200.0 * share if stage == FIRST else 100.0 + 100.0 * share

    @classmethod
    def scores(cls, record):
        damage = record.get('damage')
        if not isinstance(damage, (int, float)):
            return []
        (first, second) = (record.get('plan1'), record.get('plan2'))
        if first is None and second is None:
            # one plan, before the stages were told apart: the last stage's (see the module doc)
            (first, second) = (record.get('plan'), None) if damage < 100 else (None, record.get('plan'))
        army = record.get('army', OTHER)
        out = []
        if first in cls.plans:
            out.append((army, FIRST, first, cls._share(damage, FIRST)))
        if second in cls.plans and damage >= 100:
            out.append((army, SECOND, second, cls._share(damage, SECOND)))
        return out

    def record(self, army, plan, damage, stage = FIRST):
        '''Score the plan of one stage with the battle's total ``damage`` (0-200 %).'''
        if stage == SECOND and damage < 100:
            return  # the battle never reached the second base
        self._add(army, stage, plan, self._share(damage, stage))

    def record_battle(self, army, first, second, damage):
        '''Score the plans of a battle's two stages (``second`` None: never reached).'''
        if first is not None:
            self.record(army, first, damage, FIRST)
        if second is not None:
            self.record(army, second, damage, SECOND)


QUAKES = ('curve', 'random')


class QuakeLearner(_Learner):
    '''Which Earthquake placement takes the most of a Home Village base's loot, per army
    (the attack method): the same draws, scored by the raid's ``loot`` (the % of the base's
    gold and elixir it took, :func:`app.core.hv_results.loot_share`). Both placements start
    believed at 50 % (six raids' worth), so the first draws try both.'''
    village = 'home'
    plans = QUAKES

    @classmethod
    def scores(cls, record):
        (plan, loot) = (record.get('plan'), record.get('loot'))
        if plan not in cls.plans or not isinstance(loot, (int, float)):
            return []
        return [(record.get('army', OTHER), FIRST, plan, loot / 100.0)]

    def _expected(self, share, stage):
        return 100.0 * share

    def record(self, army, plan, loot):
        '''Score a placement with the % of the base's loot the raid took.'''
        self._add(army, FIRST, plan, loot / 100.0)
