'''Builder Base attack plan: which troop each bar card holds, and how each troop is played.

Every card is matched to a troop before the first deploy: the green swap buttons that
locate the cards, and the colours the portraits lose once deployed, are only there until
then. A troop's profile gives its order (tanks open the way, wall breakers follow, damage
comes behind), where it lands (one shared entry point, so the groups push together, or
a slot of its own along the front for troops that do better alone) and when its ability
fires, by tapping its card again (BB 2.0): Power P.E.K.K.A Overcharge, Bomber Bouncing
Bomb (it recharges), Night Witch Bat Swarm, Baby Dragon Fiery Sneeze, and the machine's,
which grows stronger the longer it charges. A card no template recognises keeps the old
play: a slot along the front, ability at 10 s. The timings are first guesses from BB 2.0
guides, to tune on live battles.
'''
import random
from dataclasses import dataclass
from typing import Optional

MACHINE = 'machine'


@dataclass(frozen = True)
class TroopProfile:
    order: int  # groups land in ascending order
    spread: bool  # a slot of its own along the front instead of the shared entry point
    gap: float  # s to wait before this troop's first card, after the previous group
    ability_at: Optional[float]  # s after landing when the card is tapped again (None: never)
    ability_every: float = 0.0  # > 0: tapped again at this interval (a recharging ability)


PROFILES = {
    MACHINE: TroopProfile(order = 0, spread = False, gap = 0.0, ability_at = 16.0),  # the tank, ability left to charge
    'pekka': TroopProfile(order = 1, spread = False, gap = 0.4, ability_at = 9.0),  # Overcharge once in the base
    'bomber': TroopProfile(order = 2, spread = False, gap = 1.5, ability_at = 3.0, ability_every = 12.0),  # walls, behind the tanks
}
UNKNOWN = TroopProfile(order = 9, spread = True, gap = 0.3, ability_at = 10.0)

# (troop, template of its card portrait), cut from live GPG bars
TROOP_TEMPLATES = (('pekka', 'bbpekka.png'), ('bomber', 'bbbomber.png'))
_MATCH_MIN = 0.8
# Portrait centre from the swap button under it, and the search half-size, in screen heights
# (the bar scales with the height; measured on a 1227x767 GPG bar).
_PORTRAIT_OFFSET = (-0.018, -0.047)
_PORTRAIT_HALF = (0.065, 0.045)
_ENTRY_JITTER = 0.012  # screen heights around the entry point, so groups do not stack on one pixel


@dataclass(frozen = True)
class Card:
    troop: str  # a PROFILES key, or '' when no template matched
    tap: tuple  # the card art: a tap there selects the troop (the swap button below must not be tapped)


@dataclass(frozen = True)
class Step:
    card: tuple  # tap: selects the troop
    point: tuple  # tap: lands it
    wait: float  # s before this step
    profile: TroopProfile


def identify(vision, frame, swap):
    '''The troop of the card whose swap button is at ``swap``, or '' when unknown.'''
    (h, w) = frame.shape[:2]
    (cx, cy) = (swap[0] + _PORTRAIT_OFFSET[0] * h, swap[1] + _PORTRAIT_OFFSET[1] * h)
    (x0, y0) = (max(0, int(cx - _PORTRAIT_HALF[0] * h)), max(0, int(cy - _PORTRAIT_HALF[1] * h)))
    (x1, y1) = (min(w, int(cx + _PORTRAIT_HALF[0] * h)), min(h, int(cy + _PORTRAIT_HALF[1] * h)))
    best = ('', _MATCH_MIN)
    for (troop, template) in TROOP_TEMPLATES:
        (_x, _y, score) = vision.find_template_with_confidence(frame, template, threshold = 0, region = (x0, y0, x1 - x0, y1 - y0))
        if score >= best[1]:
            best = (troop, score)
    return best[0]


def plan(cards, machine, entry, front, frame_height, rng = random):
    '''Deploy steps, in order: the machine (``machine``: its card, or None) and each card,
    grouped by troop profile. Grouped troops land on ``entry`` (a little jitter each);
    spread ones take the ``front`` slots in turn.'''
    jitter = _ENTRY_JITTER * frame_height
    near = lambda: (int(entry[0] + rng.uniform(-jitter, jitter)), int(entry[1] + rng.uniform(-jitter, jitter)))
    groups = sorted({c.troop for c in cards}, key = lambda t: PROFILES.get(t, UNKNOWN).order)
    steps = []
    if machine is not None:
        steps.append(Step(machine, near(), 0.0, PROFILES[MACHINE]))
    slots = iter(front)
    for troop in groups:
        profile = PROFILES.get(troop, UNKNOWN)
        for (i, card) in enumerate(c for c in cards if c.troop == troop):
            point = next(slots, entry) if profile.spread else near()
            steps.append(Step(card.tap, point, profile.gap if i == 0 and steps else 0.0, profile))
    return steps
