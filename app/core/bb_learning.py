'''Which Builder Base attack plan wins, learned from the battles played.

A plan is the side of the base the attack goes in from (:mod:`app.core.bb_scout`), the
best one by the plan's own measure:

- ``best``: the scouting's blend of buildings in reach and nearness to the core;
- ``core``: the side nearest the core (where the Builder Hall usually is);
- ``reach``: the side with the most buildings in reach;
- ``mortar``: the Multi Mortar's side (a P.E.K.K.A push with a Multi Mortar found).

Until November 14, 2026 the scouting then drew one of its three best sides at random, so a
plan's side varied as much within the plan as between plans and its score was mostly that
draw (61 battles: 159 % of damage on the first half, 158 % on the second). Those battles
carry no ``s1`` / ``s2`` (the side played) in the history, and do not count.

A battle has two stages, two bases, and each stage draws its own plan, scored by its own
stage: the first by its damage up to 100 % (did the side clear the first base), the second
by the damage over 100 %. Plans that go in from the same side of a base are the same attack
there, and the stage scores each of them: on 53 live bases core took another side than
best on 10, reach on 5, and the Multi Mortar's side was another on 15 of the 26 with one.
A stage whose opening did not land on its plan's side (another side took it, or a map
edge) scores nothing. Plans are believed per army and kind of base:
a P.E.K.K.A push's bases with a Multi Mortar seen apart from the others, as ``mortar`` is
only drawn there and has to be compared with the other plans on the same bases.

Only the newest :data:`WINDOW` battles count: the army levels up and the bases change, so
old battles stop speaking for the plans.

The plan of a stage is drawn by Thompson sampling: each plan's share is a Beta belief, one
draw each, the highest plays. Plans that win get played more, the others now and then, so a
plan that starts badly still gets its chance. A plan never played starts believed at half
its stage (as if six battles at 50 %); the player's own play for a P.E.K.K.A push, the Multi
Mortar first, at 70 % (ten battles' worth), so it leads the first draws on a base with one.

The Home Village's Earthquake placement is learned the same way (:class:`QuakeLearner`),
from every raid.
'''
import random
from collections import deque

PLANS = ('best', 'core', 'reach', 'mortar')
PEKKA = 'pekka'
OTHER = 'other'
WINDOW = 40  # Builder Base battles the plans are believed from: the newest
FIRST = 1
SECOND = 2


def bases(army, mortar_seen):
    '''The beliefs a stage draws from: its army's, and for a P.E.K.K.A push, those of the
    bases with a Multi Mortar seen or of the others (the scouting looks for one only then).'''
    return f'{army}, Multi Mortar' if mortar_seen else army


_PRIOR = (3.0, 3.0)  # (alpha, beta) of a plan never played
_PRIORS = {(bases(PEKKA, True), 'mortar'): (7.0, 3.0)}


class _Learner:
    '''Thompson sampling over plans, per key and stage: Beta beliefs of each plan's share.'''
    village = None  # the history records it learns from
    plans = ()
    priors = {}
    window = None  # the newest battles the beliefs hold (None: every battle)

    def __init__(self):
        self._beliefs = {}  # (key, stage, plan) -> [alpha, beta, battles]
        self._battles = deque()  # the scores of the battles in the window, oldest first

    @classmethod
    def from_history(cls, records):
        learner = cls()
        for r in records:
            if r.get('village') == cls.village:
                learner.add(r)
        return learner

    @classmethod
    def scores(cls, record):
        '''``(key, stage, plan, share)`` the history ``record`` scores.'''
        raise NotImplementedError

    def add(self, record):
        '''Learn from a history ``record``; past the window, the oldest battle is forgotten.'''
        scores = self.scores(record)
        for score in scores:
            self._add(*score)
        if self.window and scores:
            self._battles.append(scores)
            if len(self._battles) > self.window:
                for score in self._battles.popleft():
                    self._add(*score, forget = True)

    def _belief(self, key, stage, plan):
        if (key, stage, plan) not in self._beliefs:
            (a, b) = self.priors.get((key, plan), _PRIOR)
            self._beliefs[(key, stage, plan)] = [a, b, 0]
        return self._beliefs[(key, stage, plan)]

    def _add(self, key, stage, plan, share, forget = False):
        share = min(1.0, max(0.0, float(share)))
        sign = -1 if forget else 1
        belief = self._belief(key, stage, plan)
        belief[0] += sign * share
        belief[1] += sign * (1.0 - share)
        belief[2] += sign

    def choose(self, key, available, rng = random, stage = FIRST):
        '''One of ``available`` plans, by a draw from each one's belief.'''
        draws = [(rng.betavariate(*self._belief(key, stage, p)[:2]), p) for p in available]
        return max(draws)[1]

    def _expected(self, share, stage):
        raise NotImplementedError

    def summary(self, key, available, stage = FIRST):
        '''"mortar 94 % (3), best 50 % (0)": each plan's expected score and its battles,
        for the log.'''
        parts = []
        for p in available:
            (a, b, n) = self._belief(key, stage, p)
            parts.append(f'{p} {self._expected(a / (a + b), stage):.0f} % ({n})')
        return ', '.join(parts)


class PlanLearner(_Learner):
    '''The Builder Base's plans, per army, kind of base and stage, scored by the stage's damage.'''
    village = 'builder'
    plans = PLANS
    priors = _PRIORS
    window = WINDOW

    @staticmethod
    def _share(damage, stage):
        return min(damage, 100.0) / 100.0 if stage == FIRST else (damage - 100.0) / 100.0

    def _expected(self, share, stage):
        '''The stage's damage the share stands for (0-100 %).'''
        return 100.0 * share

    @classmethod
    def scores(cls, record):
        damage = record.get('damage')
        if not isinstance(damage, (int, float)):
            return []
        army = record.get('army', OTHER)
        out = []
        for (stage, plan, side) in ((FIRST, record.get('plan1'), record.get('s1')), (SECOND, record.get('plan2'), record.get('s2'))):
            if plan not in cls.plans or not isinstance(side, dict) or side.get('front') != 0:
                continue  # played before the sides were fixed, or not from the plan's side
            if stage == SECOND and damage < 100:
                continue  # the battle never reached the second base
            key = bases(army, side.get('mortar') is not None)
            alike = side.get('plans') or [plan]  # the plans that went in from this side: one attack
            out.extend((key, stage, p, cls._share(damage, stage)) for p in cls.plans if p in alike)
        return out


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
