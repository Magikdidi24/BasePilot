'''Builder Base attack plan: which troop each bar card holds, and how each troop is played.

Every card is matched to a troop before the first deploy: the green swap buttons that
locate the cards, and the colours the portraits lose once deployed, are only there until
then. A troop's profile gives its order (tanks open the way, wall breakers follow, damage
comes behind), where it lands (one shared entry point, so the groups push together, or
a slot of its own along the front for troops that do better alone) and when its ability
fires, by tapping its card again (BB 2.0): Boxer Block, Overcharge, Bouncing Bomb (it
recharges), Skeleton Bomb, Bat Swarm, Fiery Sneeze, and the machine's, which grows
stronger the longer it charges.

An ability goes at the right moment, not all at once: once its troop is engaged (the
health bar its card shows during the fight falls under the profile's share), at the
latest after the profile's delay, never before its earliest one; never two of one troop
kind within :data:`_ABILITY_SPACING`, one tap per poll, and none for a dead troop (grey
card). A troop card's background tells its ability's state (:func:`ability_state`): it
is only tapped while ready (green), a used one-time ability turns it grey, a recharging
one red until it is green again. Only the machine charges its ability (tapped early, the
game answers "You need to wait..."), so it goes on time, and again at intervals. A card no template recognises keeps the old play: a slot along the front, ability
at 10 s. The timings are first guesses from BB 2.0 guides, to tune on live battles.
'''
import random
from dataclasses import dataclass, field
from typing import Optional

import cv2

MACHINE = 'machine'


@dataclass(frozen = True)
class TroopProfile:
    order: int  # groups land in ascending order
    spread: bool  # a slot of its own along the front instead of the shared entry point
    gap: float  # s to wait before this troop's first card, after the previous group
    ability_at: Optional[float]  # earliest s after landing for its ability (None: no active ability)
    ability_hp: Optional[float] = None  # fire once its health falls under this share (the troop is engaged)
    ability_latest: Optional[float] = None  # fire by then whatever its health (None: at ability_at)
    ability_every: float = 0.0  # > 0: fire again, at least this long after the last tap (a recharging ability)


PROFILES = {
    # the tank; no health bar on its card, and its ability charges (up to three levels): on time, then again
    MACHINE: TroopProfile(order = 0, spread = False, gap = 0.0, ability_at = 20.0, ability_every = 20.0),
    'boxer': TroopProfile(order = 1, spread = False, gap = 0.4, ability_at = 2.0, ability_hp = 0.75, ability_latest = 15.0),  # tank: Boxer Block shield under fire
    'pekka': TroopProfile(order = 1, spread = False, gap = 0.4, ability_at = 4.0, ability_hp = 0.6, ability_latest = 16.0),  # tank: Overcharge in the thick of it
    'barbarian': TroopProfile(order = 2, spread = False, gap = 1.0, ability_at = None),  # Rage (22 s, passive): right behind the tanks
    'bomber': TroopProfile(order = 2, spread = False, gap = 1.5, ability_at = 3.0, ability_every = 2.0),  # walls first: Bouncing Bomb, again once recharged
    'cannoncart': TroopProfile(order = 2, spread = False, gap = 1.0, ability_at = None),  # stays a mobile cart (Mortar Mode left off)
    'archer': TroopProfile(order = 3, spread = False, gap = 1.0, ability_at = None),  # Cloak (11 s, passive): behind the tanks
    'dropship': TroopProfile(order = 3, spread = False, gap = 1.5, ability_at = 4.0, ability_hp = 0.85, ability_latest = 9.0),  # Skeleton Bomb once over the defences
    'minion': TroopProfile(order = 3, spread = False, gap = 1.0, ability_at = None),  # Power Shot (passive)
    'witch': TroopProfile(order = 3, spread = False, gap = 2.0, ability_at = 4.0, ability_hp = 0.9, ability_latest = 10.0),  # Bat Swarm once she is hit
    'babydragon': TroopProfile(order = 3, spread = True, gap = 1.0, ability_at = 3.0, ability_hp = 0.85, ability_latest = 9.0),  # apart (Tantrum); Fiery Sneeze when hit
}
UNKNOWN = TroopProfile(order = 9, spread = True, gap = 0.3, ability_at = 10.0)
TROOP_NAMES = {MACHINE: 'Battle Machine / Copter', 'boxer': 'Boxer Giant', 'pekka': 'Power P.E.K.K.A',
               'barbarian': 'Raged Barbarian', 'bomber': 'Bomber', 'cannoncart': 'Cannon Cart',
               'archer': 'Sneaky Archer', 'dropship': 'Drop Ship', 'minion': 'Beta Minion',
               'witch': 'Night Witch', 'babydragon': 'Baby Dragon'}

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
# The health bar a card shows during the fight: the card's width (its tap sits right of the
# centre) and the band above the portrait, in screen heights from the tap point.
_HEALTH_X = (-0.071, 0.032)
_HEALTH_Y = (-0.036, -0.015)
_ABILITY_SPACING = 1.2  # s between two abilities of one troop kind
_ABILITY_RECHECK = 1.5  # s after a one-time ability's tap before its card is checked (green still: the tap was lost)
_ABILITY_TRIES = 3
# Card background beside the portrait's top corners, in screen heights from the tap point.
# Live GPG HSV: blue (110, 183, 255) not deployed; green (42, 170, 188) ready; red (1, 74-175,
# 185-216) recharging; grey (95-110, 4-11, 170) used.
_BACKGROUND_X = (-0.057, 0.023)
_BACKGROUND_Y = -0.004
READY = 'ready'
RECHARGING = 'recharging'
USED = 'used'


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
    troop: str = ''


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


def health(frame, tap):
    '''Share of its health the troop of the card at ``tap`` has left, from the bar its card
    shows during the fight (green, orange, then red, over a dark track), or None with no
    bar (not deployed yet, or dead). Live GPG: 0.13 for a red sliver, 0.71 for a bar a
    quarter empty.'''
    (h, w) = frame.shape[:2]
    (x0, x1) = (max(0, int(tap[0] + _HEALTH_X[0] * h) + 2), min(w, int(tap[0] + _HEALTH_X[1] * h) - 2))
    (y0, y1) = (max(0, int(tap[1] + _HEALTH_Y[0] * h)), min(h, int(tap[1] + _HEALTH_Y[1] * h)))
    if x1 <= x0 or y1 <= y0:
        return None
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    (hue, sat, val) = (hsv[..., 0], hsv[..., 1], hsv[..., 2])
    life = ((hue <= 75) | (hue >= 170)) & (sat >= 110) & (val >= 110)  # red to green, bright
    share = float(life.mean(axis = 1).max())
    return share if share >= 0.03 else None


def ability_state(frame, tap):
    ''':data:`READY`, :data:`RECHARGING` or :data:`USED` from the background of the troop
    card at ``tap``, or None (not deployed yet: blue; or unreadable). Pixels vote one by one:
    hue is circular, and the red of a recharge sits at both ends of it.'''
    (h, w) = frame.shape[:2]
    counts = {READY: 0, RECHARGING: 0, USED: 0}
    total = 0
    for dx in _BACKGROUND_X:
        (x, y) = (int(tap[0] + dx * h), int(tap[1] + _BACKGROUND_Y * h))
        patch = frame[max(0, y - 4):min(h, y + 4), max(0, x - 4):min(w, x + 4)]
        if patch.size == 0:
            continue
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
        (hue, sat, val) = (hsv[:, 0], hsv[:, 1], hsv[:, 2])
        counts[USED] += int(((sat <= 35) & (val >= 120) & (val <= 220)).sum())
        counts[RECHARGING] += int(((sat >= 60) & ((hue <= 10) | (hue >= 170))).sum())
        counts[READY] += int(((sat >= 100) & (hue >= 30) & (hue <= 60)).sum())
        total += len(hsv)
    if not total:
        return None
    (state, n) = max(counts.items(), key = lambda kv: kv[1])
    return state if n >= 0.5 * total else None


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
        steps.append(Step(machine, near(), 0.0, PROFILES[MACHINE], MACHINE))
    slots = iter(front)
    for troop in groups:
        profile = PROFILES.get(troop, UNKNOWN)
        for (i, card) in enumerate(c for c in cards if c.troop == troop):
            point = next(slots, entry) if profile.spread else near()
            steps.append(Step(card.tap, point, profile.gap if i == 0 and steps else 0.0, profile, troop))
    return steps


@dataclass
class Ability:
    card: tuple
    troop: str
    profile: TroopProfile
    earliest: float  # monotonic s
    latest: float  # monotonic s
    tries: int = 0
    health: Optional[float] = None  # at the last tap, for the log


@dataclass
class Abilities:
    """The ability taps still to come in one stage, handed out one per poll by :meth:`next_tap`."""
    items: list = field(default_factory = list)
    last_by_troop: dict = field(default_factory = dict)

    def add(self, step, landed):
        p = step.profile
        if p.ability_at is not None:
            latest = p.ability_latest if p.ability_latest is not None else p.ability_at
            self.items.append(Ability(step.card, step.troop, p, landed + p.ability_at, landed + latest))

    def next_tap(self, now, frame):
        """The :class:`Ability` to tap now (its ``card``), or None. Among the ready ones (past
        their earliest time, card green, and engaged or past their latest), the most hurt
        troop goes first; a troop kind that just used one waits :data:`_ABILITY_SPACING`; a dead
        troop's, or a used one-time ability's, is dropped."""
        ready = []
        for item in list(self.items):
            if now < item.earliest or now - self.last_by_troop.get(item.troop, -1e9) < _ABILITY_SPACING:
                continue
            if frame is not None and not alive(frame, item.card):
                self.items.remove(item)  # grey card: the troop is dead
                continue
            if frame is not None and item.troop != MACHINE:
                state = ability_state(frame, item.card)
                if state == USED and not item.profile.ability_every:
                    self.items.remove(item)  # done (by this bot, or the game at a stage's end)
                    continue
                if state != READY:
                    continue  # recharging, not deployed yet, or unreadable
            hp = None
            if frame is not None and item.troop != MACHINE and item.profile.ability_hp is not None:
                hp = health(frame, item.card)
            engaged = hp is not None and hp < item.profile.ability_hp
            if engaged or item.profile.ability_hp is None or now >= item.latest:
                ready.append((hp if hp is not None else 1.0, item.latest, item, hp))
        if not ready:
            return None
        (_rank, _latest, item, hp) = min(ready, key = lambda r: (r[0], r[1]))
        self.last_by_troop[item.troop] = now
        item.tries += 1
        item.health = hp
        if item.profile.ability_every:
            item.earliest = item.latest = now + item.profile.ability_every
        elif item.tries >= _ABILITY_TRIES:
            self.items.remove(item)
        else:
            item.earliest = item.latest = now + _ABILITY_RECHECK  # still green by then: the tap was lost
        return item
