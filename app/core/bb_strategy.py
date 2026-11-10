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

import cv2

MACHINE = 'machine'


@dataclass(frozen = True)
class TroopProfile:
    order: int  # groups land in ascending order
    spread: bool  # a slot of its own along the front instead of the shared entry point
    gap: float  # s to wait before this troop's first card, after the previous group
    ability_at: Optional[float]  # s after landing when the card is tapped again (None: never)
    ability_every: float = 0.0  # > 0: tapped again at this interval (a recharging ability)


PROFILES = {
    MACHINE: TroopProfile(order = 0, spread = False, gap = 0.0, ability_at = 16.0),  # the tank; its ability grows while it charges
    'boxer': TroopProfile(order = 1, spread = False, gap = 0.4, ability_at = 7.0),  # tank: Boxer Block shield once under fire
    'pekka': TroopProfile(order = 1, spread = False, gap = 0.4, ability_at = 9.0),  # tank and damage: Overcharge once in the base
    'barbarian': TroopProfile(order = 2, spread = False, gap = 1.0, ability_at = None),  # Rage (22 s, passive): right behind the tanks
    'bomber': TroopProfile(order = 2, spread = False, gap = 1.5, ability_at = 3.0, ability_every = 12.0),  # walls: Bouncing Bomb, recharges
    'cannoncart': TroopProfile(order = 2, spread = False, gap = 1.0, ability_at = None),  # stays a mobile cart (Mortar Mode left off)
    'archer': TroopProfile(order = 3, spread = False, gap = 1.0, ability_at = None),  # Cloak (11 s, passive): behind the tanks
    'dropship': TroopProfile(order = 3, spread = False, gap = 1.5, ability_at = 6.0),  # Skeleton Bomb over the walls
    'minion': TroopProfile(order = 3, spread = False, gap = 1.0, ability_at = None),  # Power Shot (passive)
    'witch': TroopProfile(order = 3, spread = False, gap = 2.0, ability_at = 6.0),  # behind the tanks: Bat Swarm
    'babydragon': TroopProfile(order = 3, spread = True, gap = 1.0, ability_at = 5.0),  # Tantrum: stronger with no air unit near, so apart; Fiery Sneeze
}
UNKNOWN = TroopProfile(order = 9, spread = True, gap = 0.3, ability_at = 10.0)

# (troop, template of its card portrait), cut from a live GPG bar and from the Change Troops
# menu, whose portraits are drawn at the bar's scale (the bar's templates match it at 0.96+)
TROOP_TEMPLATES = tuple((troop, f'bb{troop}.png') for troop in PROFILES if troop != MACHINE)
_MATCH_MIN = 0.8
# A card whose troop died in the last stage is drawn in grey but its portrait still matches
# (0.86 measured): colour tells. Mean HSV saturation of a portrait, live GPG: 75-160 alive,
# 0-1 dead.
_ALIVE_MIN_SATURATION = 30
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


def alive(frame, center):
    '''The card portrait around ``center`` is in colour (its troop can still be deployed).'''
    (h, w) = frame.shape[:2]
    (dx, dy) = (int(0.043 * h), int(0.024 * h))  # about the portrait templates' half-size
    (x, y) = (int(center[0]), int(center[1]))
    patch = frame[max(0, y - dy):min(h, y + dy), max(0, x - dx):min(w, x + dx)]
    return patch.size > 0 and cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[..., 1].mean() >= _ALIVE_MIN_SATURATION


def read_bar(vision, frame, swaps, lift, machine_x = None):
    '''The deployable troop cards on the bar, left to right: the cards over a swap button
    (new troops, before their first deploy) and the portraits a template recognises in
    colour (troops back from the last stage carry no swap button; a selected card's button
    may not match). Dead troops' grey cards and the machine card are left out.'''
    h = frame.shape[0]
    same = 0.05 * h  # cards are ~0.12 h apart
    cards = [Card(identify(vision, frame, s), (s[0], s[1] - lift)) for s in sorted(swaps)
             if machine_x is None or abs(s[0] - machine_x) > lift]
    roi = vision.bottom_half_region(frame)
    for (troop, template) in TROOP_TEMPLATES:
        for (x, y) in vision.find_all_template_centers(frame, template, threshold = _MATCH_MIN, region = roi, max_matches = 10, suppress_pad_frac = 0.1):
            if machine_x is not None and abs(x - machine_x) <= lift:
                continue
            twin = next((i for (i, c) in enumerate(cards) if abs(c.tap[0] - x) < same), None)
            if twin is None:
                if alive(frame, (x, y)):
                    cards.append(Card(troop, (x, y)))
            elif not cards[twin].troop:
                cards[twin] = Card(troop, cards[twin].tap)
    return sorted(cards, key = lambda c: c.tap[0])


def plan(cards, machine, entry, front, frame_height, rng = random):
    '''Deploy steps, in order: the machine (``machine``: its card, or None) and each card,
    grouped by troop profile. Grouped troops land on ``entry`` (a little jitter each);
    spread ones take the ``front`` slots in turn.'''
    jitter = _ENTRY_JITTER * frame_height
    near = lambda: (int(entry[0] + rng.uniform(-jitter, jitter)), int(entry[1] + rng.uniform(-jitter, jitter)))
    groups = sorted({c.troop for c in cards}, key = lambda t: (PROFILES.get(t, UNKNOWN).order, t))
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
