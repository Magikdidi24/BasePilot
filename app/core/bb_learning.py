'''Which Builder Base attack plan wins, learned from the battles played.

A plan is how the side of the base is picked (:mod:`app.core.bb_scout`):

- ``best``: the scouting's blend of buildings in reach and nearness to the core;
- ``core``: the side nearest the core (where the Builder Hall usually is);
- ``reach``: the side with the most buildings in reach;
- ``mortar``: the Multi Mortar's side (a P.E.K.K.A push with a Multi Mortar found).

Each battle's total damage (0-200 %) scores its plan. The plan of the next battle is
drawn by Thompson sampling: each plan's share of the damage is a Beta belief, one draw
each, the highest plays. Plans that win get played more, the others now and then, so a
plan that starts badly still gets its chance. A plan never played starts believed at
100 % (as if four battles at 100 %); the player's own play for a P.E.K.K.A push (the Multi
Mortar first) at 140 % (eight battles at 150 %): it leads the draws at first (58 %), and
yields to a plan that does clearly better (175 % against its 70 %, 15 battles each: the
other leads 80 % of the draws). Beliefs are kept per army (a P.E.K.K.A push, or any other).
'''
import random

PLANS = ('best', 'core', 'reach', 'mortar')
PEKKA = 'pekka'
OTHER = 'other'
_PRIOR = (3.0, 3.0)  # (alpha, beta) of a plan never played
_PRIORS = {(PEKKA, 'mortar'): (7.0, 3.0)}


class PlanLearner:
    def __init__(self):
        self._beliefs = {}  # (army, plan) -> [alpha, beta, battles]

    @classmethod
    def from_history(cls, records):
        learner = cls()
        for r in records:
            if r.get('village') == 'builder' and r.get('plan') in PLANS and isinstance(r.get('damage'), (int, float)):
                learner.record(r.get('army', OTHER), r['plan'], r['damage'])
        return learner

    def _belief(self, army, plan):
        if (army, plan) not in self._beliefs:
            (a, b) = _PRIORS.get((army, plan), _PRIOR)
            self._beliefs[(army, plan)] = [a, b, 0]
        return self._beliefs[(army, plan)]

    def record(self, army, plan, damage):
        share = min(1.0, max(0.0, float(damage) / 200.0))
        belief = self._belief(army, plan)
        belief[0] += share
        belief[1] += 1.0 - share
        belief[2] += 1

    def choose(self, army, available, rng = random):
        '''One of ``available`` plans, by a draw from each one's belief.'''
        draws = [(rng.betavariate(*self._belief(army, p)[:2]), p) for p in available]
        return max(draws)[1]

    def summary(self, army, available):
        '''"mortar 70 % (3), best 50 % (0)": each plan's expected share of the damage, ×200,
        and its battles, for the log.'''
        parts = []
        for p in available:
            (a, b, n) = self._belief(army, p)
            parts.append(f'{p} {200 * a / (a + b):.0f} % ({n})')
        return ', '.join(parts)
