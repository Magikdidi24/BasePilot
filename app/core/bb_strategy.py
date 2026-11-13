'''Builder Base attack plan: which troop each bar card holds, and how each troop is played.

Every card is matched to a troop before its deploy, by the bottom of its portrait: in a
later stage, the health bar of a troop that survived the last one covers the top of its
portrait, and its card has no swap button any more. A troop's role says where and when it
lands (:func:`plan`) along the front: the edge of the base the scouting picked
(:mod:`app.core.bb_scout`), or else one top edge of the map (the bottom ones run into the
troop bar). The push enters at the front's entry, and

- the machine and the tanks (Boxer Giant, Power P.E.K.K.A, Drop Ship) open it, a little
  apart, so that one splash (Roaster, Crusher, Multi Mortar) does not hit them all;
- flankers (Raged Barbarians, Sneaky Archers, Beta Minions), a pair or two of them, land
  far out on both sides at once: they clear the outer buildings, so the push is funnelled
  into the core instead of walking around it; the others follow the tanks;
- wall breakers (Bombers) come a second after the tanks, once the defences are on them,
  and the support (Night Witches, Cannon Carts) right behind;
- Baby Dragons land alone along the front, apart from the push (Tantrum: more damage with
  no other air unit near).

That is the play of BB 2.0 guides (tank first, Bombers behind it, flanks at once, troops
spread against splash). A P.E.K.K.A push lands its P.E.K.K.As as one pack
(:data:`_PACK` apart: they all pick the same first building), the machine with them, and
the Bombers :data:`_PUSH_BREAKER_WAIT` later at the same spot: the defences are on the
P.E.K.K.As by then, and the Bouncing Bomb opens the wall they stand at. Live, a Bomber
landed first, alone, died in under 6 s before any wall, and P.E.K.K.As spread along the
front (0.025 screen heights apart) split between two outer buildings and walked around
the walls; that stage failed at 86 %.

A troop's profile also says when its ability fires, by tapping its card again (BB 2.0):
Boxer Block, Overcharge, Bouncing Bomb (it recharges), Skeleton Bomb, Bat Swarm, Fiery
Sneeze, and the machine's, which grows stronger the longer it charges. An ability goes at
the right moment, not all at once: once its troop is engaged (the health bar its card
shows during the fight falls under the profile's share), or under heavy fire (it lost the
profile's drop within :data:`_DROP_WINDOW`), at the latest after the profile's delay (for
an infinite one, only once the troop's health bar went unread for :data:`_BLIND_AFTER`),
never before its earliest one; never two of one troop kind within
:data:`_ABILITY_SPACING`, one tap per poll, and none for a dead troop (grey card). A troop
card's background tells its ability's state (:func:`ability_state`): it is only tapped
while ready (green), a used one-time ability turns it grey, a recharging one red until it
is green again. Only the machine charges its ability (tapped early, the game answers "You
need to wait..."), so it goes on time, and again at intervals. A card no template
recognises follows the push, ability at 10 s. The timings are first guesses from BB 2.0
guides, to tune on live battles.
'''
import math
import random
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from app.utils.common import get_template_path, read_image

MACHINE = 'machine'
# Roles, in their deploy order (see the module doc)
TANK = 'tank'
FLANK = 'flank'
BREAKER = 'breaker'
SUPPORT = 'support'
LONE = 'lone'
OTHER = 'other'


@dataclass(frozen = True)
class TroopProfile:
    role: str  # where and when it lands (see plan)
    ability_at: Optional[float]  # earliest s after landing for its ability (None: no active ability)
    ability_hp: Optional[float] = None  # fire once its health falls under this share (the troop is engaged)
    ability_latest: Optional[float] = None  # fire by then whatever its health (None: at ability_at; math.inf: never, but for an unread bar)
    ability_every: float = 0.0  # > 0: fire again, at least this long after the last tap (a recharging ability)
    ability_on_landing: bool = False  # its card tapped again right after it lands
    ability_drop: Optional[float] = None  # fire once it lost this share of its health within _DROP_WINDOW (heavy fire)


PROFILES = {
    # no health bar on its card, and its ability charges (up to three levels): on time, then again
    MACHINE: TroopProfile(TANK, ability_at = 20.0, ability_every = 20.0),
    'boxer': TroopProfile(TANK, 2.0, ability_hp = 0.75, ability_latest = 15.0),  # Boxer Block shield under fire
    # Overcharge: a one-time blast around her; she lives on (her card stays in colour). It goes
    # in the thick of the defences: once several of them take a quarter of her health within
    # 3 s, or under half of it before she falls; never on time alone (unless her health bar
    # goes unread for _BLIND_AFTER). Live, the old rule (under
    # 70 %, or at 30 s) fired the five of them at 64-69 % within 13 s, on the first outer
    # building, and at full health at 30 s, out of reach of anything
    'pekka': TroopProfile(TANK, 2.0, ability_hp = 0.5, ability_latest = math.inf, ability_drop = 0.25),
    'dropship': TroopProfile(TANK, 4.0, ability_hp = 0.85, ability_latest = 9.0),  # flies over the walls; Skeleton Bomb once hit
    'barbarian': TroopProfile(FLANK, None),  # Rage (22 s, passive)
    'archer': TroopProfile(FLANK, None),  # Cloak (11 s, passive): picks off the outer buildings
    'minion': TroopProfile(FLANK, None),  # Power Shot (passive): the edge buildings
    # walls: Bouncing Bomb as it lands (its next attack, the first wall), again once recharged;
    # if that tap was lost, at once when ready, first of all under 50 % health (the player's play)
    'bomber': TroopProfile(BREAKER, 0.0, ability_hp = 0.5, ability_every = 2.0, ability_on_landing = True),
    'witch': TroopProfile(SUPPORT, 4.0, ability_hp = 0.9, ability_latest = 10.0),  # Bat Swarm once she is hit
    'cannoncart': TroopProfile(SUPPORT, None),  # stays a mobile cart (Mortar Mode left off)
    'babydragon': TroopProfile(LONE, 3.0, ability_hp = 0.85, ability_latest = 9.0),  # Fiery Sneeze when hit
}
UNKNOWN = TroopProfile(OTHER, ability_at = 10.0)
TROOP_NAMES = {MACHINE: 'Battle Machine / Copter', 'boxer': 'Boxer Giant', 'pekka': 'Power P.E.K.K.A',
               'dropship': 'Drop Ship', 'barbarian': 'Raged Barbarian', 'archer': 'Sneaky Archer',
               'minion': 'Beta Minion', 'bomber': 'Bomber', 'witch': 'Night Witch', 'cannoncart': 'Cannon Cart',
               'babydragon': 'Baby Dragon'}

# role: (s to wait before its first card, screen heights between two of its cards along the front)
_ROLES = {TANK: (0.3, 0.025), FLANK: (0.0, 0.02), BREAKER: (1.0, 0.015), SUPPORT: (1.2, 0.025), LONE: (0.5, 0.08), OTHER: (0.3, 0.02)}
_ROLE_ORDER = (TANK, FLANK, BREAKER, SUPPORT, LONE, OTHER)
_PUSH_ORDER = (TANK, BREAKER, FLANK, SUPPORT, LONE, OTHER)  # a P.E.K.K.A push; the machine right after the tanks
_PACK = 0.006  # screen heights between two tanks of a P.E.K.K.A push: with the landing jitter, a pack about a tile wide
_PUSH_BREAKER_WAIT = 2.5  # s from the machine (or the last tank) to the push's first Bomber: the defences are on the pack by then
_FLANK = 0.17  # screen heights from the entry out to each flank (~10 tiles)
_FLANK_PAIRS = 2  # flankers out on each side at most: one pair per three of them, the rest follow the tanks
_LONE_FROM = 0.09  # screen heights from the entry to the first lone troop
_ENTRY_SPREAD = 0.1  # the entry: the front's middle, give or take this share of it
_ENTRY_JITTER = 0.006  # screen heights along the front, so two troops do not stack on one pixel
_FRONT_MARGIN = 0.06  # screen heights kept clear of the map's corner
_FRONT_TOP = 0.12  # screen heights under the top HUD (the players' names, the timer)

# (troop, template of its card portrait), cut from a live GPG bar and from the Change Troops
# menu, whose portraits are drawn at the bar's scale (the bar's templates match it at 0.96+)
TROOP_TEMPLATES = tuple((troop, f'bb{troop}.png') for troop in PROFILES if troop != MACHINE)
_MATCH_MIN = 0.8
# A portrait is matched from this share of its height down: a survivor's health bar covers
# the top ~35 % in the next stage (0.45 there on the full portrait, 0.98+ on the rest; the
# other troops' portraits stay under 0.46 on that part).
_PORTRAIT_FROM = 0.45
# A card whose troop died in the last stage is drawn in grey but its portrait still matches
# (0.86 measured): colour tells. Mean HSV saturation of a portrait, live GPG: 75-160 alive,
# 0-1 dead.
_ALIVE_MIN_SATURATION = 30
# Portrait centre from the swap button under it, and the search half-size, in screen heights
# (the bar scales with the height; measured on a 1227x767 GPG bar).
_PORTRAIT_OFFSET = (-0.018, -0.047)
_PORTRAIT_HALF = (0.065, 0.045)
# The health bar a card shows during the fight: the card's width (its tap sits right of the
# centre), and where its dark bottom edge is looked for, in screen heights from the tap point
# (a swap button's tap and a template's land a few px apart). The fill is read just above
# that edge: under it, the green of a ready card (or the red of a recharging one) has the
# bar's colours (live: a fixed band 3 px low read every bar full).
_HEALTH_X = (-0.071, 0.032)
_HEALTH_SEARCH = (-0.05, -0.005)
_HEALTH_FILL = (0.012, 0.003)  # screen heights above the edge
_HEALTH_EDGE_DARK = 80  # V of the edge's pixels
_HEALTH_EDGE_SHARE = 0.9  # of a row's pixels that dark: the edge, a full-width line (a dark portrait under it: ~0.65)
_ABILITY_SPACING = 1.2  # s between two abilities of one troop kind
_DROP_WINDOW = 3.0  # s over which a troop's health drop is measured (a profile's ability_drop)
_DROP_ANCHOR = 4.5  # s: the oldest reading a drop is measured from (the window and a poll or two)
_SPIKE = 0.1  # a health reading this far above both readings around it: misread
_HIT = 0.05  # health share a troop lost since its first readings: engaged in this stage
_BLIND_AFTER = 30.0  # s with no health reading (from landing): an ability with no deadline goes on time
_ABILITY_RECHECK = 1.5  # s after a one-time ability's tap before its card is checked (green still: the tap was lost)
_ABILITY_TRIES = 3
# Card background beside the portrait's top corners, in screen heights from the tap point.
# Live GPG HSV: blue (110, 183, 255) not deployed; green (42, 170, 188) ready; red (1, 74-175,
# 185-216) recharging; grey (95-110, 4-11, 170) used. A card turns green as its troop lands.
_BACKGROUND_X = (-0.057, 0.023)
_BACKGROUND_Y = -0.004
# Share of that background in the blue of a card still to deploy. Live GPG: 1.0 on a fresh
# card, 0.42-0.72 on a selected one, 0.55 on a survivor of the last stage, 0 once deployed.
_WAITING_MIN_BLUE = 0.25
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


def profile(troop):
    return PROFILES.get(troop, UNKNOWN)


def _portrait_hits(vision, frame, template, region, limit = 1, threshold = -1.0):
    '''Up to ``limit`` spots of ``region`` (x, y, w, h) where the card portrait ``template``
    matches, at ``threshold`` or above, best first and a portrait apart:
    ``(score, (x, y))``, the portrait's centre. Only its part under
    :data:`_PORTRAIT_FROM` is matched (a survivor's health bar covers the top).'''
    full = read_image(get_template_path(template))
    (x, y, w, h) = region
    if full is None:
        return []
    full = vision._resize_template_for_screen(full, frame)
    top = int(round(_PORTRAIT_FROM * full.shape[0]))
    part = full[top:]
    (ph, pw) = part.shape[:2]
    patch = frame[max(0, y):y + h, max(0, x):x + w]
    if patch.shape[0] < ph or patch.shape[1] < pw:
        return []
    scores = cv2.matchTemplate(patch, part, cv2.TM_CCOEFF_NORMED)
    hits = []
    while len(hits) < limit:
        (_low, score, _at, (cx, cy)) = cv2.minMaxLoc(scores)
        if score < threshold:
            break
        hits.append((float(score), (max(0, x) + cx + pw // 2, max(0, y) + cy - top + full.shape[0] // 2)))
        scores[max(0, cy - ph):cy + ph, max(0, cx - pw):cx + pw] = -1.0  # the next one a portrait away
    return hits


def identify(vision, frame, swap):
    '''The troop of the card whose swap button is at ``swap``, or '' when unknown.'''
    (h, w) = frame.shape[:2]
    (cx, cy) = (swap[0] + _PORTRAIT_OFFSET[0] * h, swap[1] + _PORTRAIT_OFFSET[1] * h)
    (x0, y0) = (max(0, int(cx - _PORTRAIT_HALF[0] * h)), max(0, int(cy - _PORTRAIT_HALF[1] * h)))
    (x1, y1) = (min(w, int(cx + _PORTRAIT_HALF[0] * h)), min(h, int(cy + _PORTRAIT_HALF[1] * h)))
    best = ('', _MATCH_MIN)
    for (troop, template) in TROOP_TEMPLATES:
        for (score, _centre) in _portrait_hits(vision, frame, template, (x0, y0, x1 - x0, y1 - y0)):
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
    (y0, y1) = (max(0, int(tap[1] + _HEALTH_SEARCH[0] * h)), min(h, int(tap[1] + _HEALTH_SEARCH[1] * h)))
    if x1 <= x0 or y1 <= y0:
        return None
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    edges = np.nonzero((hsv[..., 2] < _HEALTH_EDGE_DARK).mean(axis = 1) >= _HEALTH_EDGE_SHARE)[0]
    if not len(edges):
        return None  # no bar: not deployed yet, or dead
    edge = int(edges.max())  # the lowest dark row: below it the card, above it the bar
    fill = hsv[max(0, edge - int(round(_HEALTH_FILL[0] * h))):max(1, edge - int(round(_HEALTH_FILL[1] * h)))]
    if not fill.size:
        return None
    (hue, sat, val) = (fill[..., 0], fill[..., 1], fill[..., 2])
    life = ((hue <= 75) | (hue >= 170)) & (sat >= 110) & (val >= 110)  # red to green, bright
    share = float(life.mean(axis = 1).max())
    return share if share >= 0.03 else None


def _background(frame, tap):
    '''HSV pixels (an int array, one row each) of the card background beside the top
    corners of the portrait of the card at ``tap``.'''
    (h, w) = frame.shape[:2]
    patches = []
    for dx in _BACKGROUND_X:
        (x, y) = (int(tap[0] + dx * h), int(tap[1] + _BACKGROUND_Y * h))
        patch = frame[max(0, y - 4):min(h, y + 4), max(0, x - 4):min(w, x + 4)]
        if patch.size:
            patches.append(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int))
    return np.concatenate(patches) if patches else np.zeros((0, 3), int)


def ability_state(frame, tap):
    ''':data:`READY`, :data:`RECHARGING` or :data:`USED` from the background of the troop
    card at ``tap``, or None (not deployed yet: blue; or unreadable). Pixels vote one by one:
    hue is circular, and the red of a recharge sits at both ends of it.'''
    hsv = _background(frame, tap)
    if not len(hsv):
        return None
    (hue, sat, val) = (hsv[:, 0], hsv[:, 1], hsv[:, 2])
    counts = {READY: int(((sat >= 100) & (hue >= 30) & (hue <= 60)).sum()),
              RECHARGING: int(((sat >= 60) & ((hue <= 10) | (hue >= 170))).sum()),
              USED: int(((sat <= 35) & (val >= 120) & (val <= 220)).sum())}
    (state, n) = max(counts.items(), key = lambda kv: kv[1])
    return state if n >= 0.5 * len(hsv) else None


def waiting(frame, tap):
    '''The troop of the card at ``tap`` is still to deploy: in colour (alive), on the blue
    background of a card not deployed yet.'''
    hsv = _background(frame, tap)
    if not len(hsv):
        return False
    blue = ((hsv[:, 0] >= 95) & (hsv[:, 0] <= 125) & (hsv[:, 1] >= 120) & (hsv[:, 2] >= 170)).mean()
    return blue >= _WAITING_MIN_BLUE and alive(frame, tap)


def read_bar(vision, frame, swaps, lift, machine_x = None):
    '''The troop cards still to deploy on the bar, left to right: the cards over a swap
    button (new troops, before the stage's first deploy) and the portraits a template
    recognises on a card :func:`waiting` (the swap buttons go once a troop has landed, and
    troops back from the last stage carry none). Deployed troops' cards, dead troops' grey
    ones and the machine card are left out. Every card's tap sits where a swap button's
    would put it, ``lift`` px over the button.'''
    h = frame.shape[0]
    same = 0.05 * h  # cards are ~0.12 h apart
    cards = [Card(identify(vision, frame, s), (s[0], s[1] - lift)) for s in sorted(swaps)
             if machine_x is None or abs(s[0] - machine_x) > lift]
    roi = vision.bottom_half_region(frame)
    for (troop, template) in TROOP_TEMPLATES:
        for (_score, (x, y)) in _portrait_hits(vision, frame, template, roi, limit = 10, threshold = _MATCH_MIN):
            tap = (int(round(x - _PORTRAIT_OFFSET[0] * h)), int(round(y - _PORTRAIT_OFFSET[1] * h - lift)))
            if machine_x is not None and abs(tap[0] - machine_x) <= lift:
                continue
            twin = next((i for (i, c) in enumerate(cards) if abs(c.tap[0] - tap[0]) < same), None)
            if twin is None:
                if waiting(frame, tap):
                    cards.append(Card(troop, tap))
            elif not cards[twin].troop:
                cards[twin] = Card(troop, cards[twin].tap)
    return sorted(cards, key = lambda c: c.tap[0])


def front_edge(corner, top, frame_height):
    '''The stretch of the map's top edge from ``corner`` (its left or right corner) towards
    ``top`` (its top corner) that troops land on: clear of the corner, and under the top
    HUD (the timer and the players' names). Two points, the corner's end first.'''
    ((ax, ay), (bx, by)) = (corner, top)
    length = math.hypot(bx - ax, by - ay)
    if length <= 0:
        return ((ax, ay), (ax, ay))
    (ux, uy) = ((bx - ax) / length, (by - ay) / length)
    start = min(_FRONT_MARGIN * frame_height, length / 2)
    end = length - start
    floor = _FRONT_TOP * frame_height
    if uy < 0 and ay + uy * end < floor:
        end = max(start, (floor - ay) / uy)
    return ((ax + ux * start, ay + uy * start), (ax + ux * end, ay + uy * end))


def _centre_out(count, spacing):
    '''Offsets of ``count`` troops spread around 0, nearest first: 0, +s, -s, +2s, ...'''
    return [spacing * ((i + 1) // 2) * (1 if i % 2 else -1) for i in range(count)]


def _flank_offsets(count, spacing):
    '''Offsets of ``count`` flankers: a pair (one each side) per three of them, up to
    :data:`_FLANK_PAIRS`, the others behind the tanks.'''
    pairs = min(_FLANK_PAIRS, count // 3)
    out = [side * (_FLANK + spacing * (i // 2)) for (i, side) in zip(range(2 * pairs), (-1, 1) * pairs)]
    return out + _centre_out(count - len(out), spacing)


def _lone_offsets(count, spacing):
    '''Offsets of ``count`` lone troops, by turns on each side of the push, each apart.'''
    return [(1 if i % 2 == 0 else -1) * (_LONE_FROM + spacing * (i // 2)) for i in range(count)]


def edge_front(edge, frame_height, rng = random):
    '''The landing spots along ``edge`` (:func:`front_edge`), entered near its middle:
    ``at(offset)`` is the spot ``offset`` screen heights along it from the entry, a little
    jitter each, kept on the edge.'''
    ((x0, y0), (x1, y1)) = edge
    length = math.hypot(x1 - x0, y1 - y0)
    (ux, uy) = ((x1 - x0) / length, (y1 - y0) / length) if length else (0.0, 0.0)
    entry = length * (0.5 + rng.uniform(-_ENTRY_SPREAD, _ENTRY_SPREAD))
    jitter = _ENTRY_JITTER * frame_height

    def at(offset):
        s = min(length, max(0.0, entry + offset * frame_height + rng.uniform(-jitter, jitter)))
        return (int(round(x0 + ux * s)), int(round(y0 + uy * s)))
    return at


def pekka_push(cards):
    return any(c.troop == 'pekka' for c in cards)


def plan(cards, machine, front):
    '''Deploy steps, in order: the machine (``machine``: its card, or None), then the cards
    role by role (see the module doc), each kind's cards left to right; for a P.E.K.K.A
    push (:func:`pekka_push`), the tanks (the P.E.K.K.As, any Boxer Giant or Drop Ship) as one
    pack, the machine, the Bombers :data:`_PUSH_BREAKER_WAIT` later, then the rest.
    ``front(offset)`` is the landing spot
    ``offset`` screen heights along the front from its entry (:func:`edge_front`,
    :func:`app.core.bb_scout.front`).'''
    at = front
    push = pekka_push(cards)
    order = _PUSH_ORDER if push else _ROLE_ORDER
    kinds = list(PROFILES)
    rank = lambda t: (order.index(profile(t).role), kinds.index(t) if t in kinds else len(kinds), t)
    ordered = sorted(cards, key = lambda c: (rank(c.troop), c.tap[0]))
    steps = []
    if machine is not None and not push:
        steps.append(Step(machine, at(0.0), 0.0, PROFILES[MACHINE], MACHINE))
    for role in order:
        group = [c for c in ordered if profile(c.troop).role == role]
        if group:
            (gap, spacing) = _ROLES[role]
            if push and role == TANK:
                spacing = _PACK
            elif push and role == BREAKER:
                gap = _PUSH_BREAKER_WAIT
            if role == FLANK:
                offsets = _flank_offsets(len(group), spacing)
            elif role == LONE:
                offsets = _lone_offsets(len(group), spacing)
            else:  # the machine, landed first, holds the tanks' middle slot
                skip = 1 if role == TANK and machine is not None and not push else 0
                offsets = _centre_out(len(group) + skip, spacing)[skip:]
            for (i, (card, offset)) in enumerate(zip(group, offsets)):
                steps.append(Step(card.tap, at(offset), gap if i == 0 and steps else 0.0, profile(card.troop), card.troop))
        if push and role == TANK and machine is not None:
            steps.append(Step(machine, at(0.0), 0.0, PROFILES[MACHINE], MACHINE))
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
    why: str = ''  # what fired the last tap besides its health, for the log
    landed: float = 0.0  # monotonic s
    first_hp: Optional[float] = None  # the lower of its first two health readings (a survivor of the last stage comes back hurt)
    reads: int = 0  # health readings lost() was given
    last_read: Optional[float] = None  # monotonic s of its last health reading
    seen: list = field(default_factory = list)  # (monotonic s, health): the last reading before _DROP_WINDOW, those within

    def lost(self, now, hp):
        '''Record ``hp`` read at ``now``; ``(share, s)``: the share of its health the troop
        lost over about :data:`_DROP_WINDOW`, and in how long, from its highest earlier
        reading, the last one before the window included (a poll every ~0.8 s: the window
        holds three or four) if no older than :data:`_DROP_ANCHOR`. A reading over both its
        neighbours by :data:`_SPIKE` was a bar misread high: left out (a steep fall, however
        steep, has no such peak).'''
        if self.reads < 2:
            self.first_hp = hp if self.first_hp is None else min(self.first_hp, hp)
        self.reads += 1
        if len(self.seen) >= 2 and self.seen[-1][1] - max(self.seen[-2][1], hp) > _SPIKE:
            self.seen.pop()
        before = [s for s in self.seen if _DROP_WINDOW < now - s[0] <= _DROP_ANCHOR]
        self.seen = before[-1:] + [s for s in self.seen if now - s[0] <= _DROP_WINDOW] + [(now, hp)]
        earlier = self.seen[:-1]
        if len(earlier) < 2:
            return (0.0, 0.0)
        (t, h) = max(earlier, key = lambda s: s[1])
        return (h - hp, now - t)


@dataclass
class Abilities:
    """The ability taps still to come in one stage, handed out one per poll by :meth:`next_tap`."""
    items: list = field(default_factory = list)
    last_by_troop: dict = field(default_factory = dict)

    def add(self, step, landed, fired = False):
        '''Schedule ``step``'s ability; ``fired``: already tapped as it landed (checked again
        :data:`_ABILITY_RECHECK` later, or once recharged).'''
        p = step.profile
        if p.ability_at is not None:
            latest = p.ability_latest if p.ability_latest is not None else p.ability_at
            item = Ability(step.card, step.troop, p, landed + p.ability_at, landed + latest, landed = landed)
            if fired:
                item.tries = 1
                item.earliest = item.latest = landed + max(p.ability_every, _ABILITY_RECHECK)
                self.last_by_troop[step.troop] = landed
            self.items.append(item)

    def forget(self, taps, near):
        '''Drop the abilities of the cards at ``taps`` (within ``near`` px across): their
        troops did not land.'''
        self.items = [a for a in self.items if all(abs(a.card[0] - t[0]) > near for t in taps)]

    def next_tap(self, now, frame):
        """The :class:`Ability` to tap now (its ``card``), or None. Among the ready ones (past
        their earliest time, card green, and engaged, under heavy fire or past their latest),
        the most hurt troop goes first, a one-time ability before a recharging one at equal
        health; a troop kind that just used one waits :data:`_ABILITY_SPACING`; a dead
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
            p = item.profile
            hp = None
            if frame is not None and item.troop != MACHINE and (p.ability_hp is not None or p.ability_drop is not None):
                hp = health(frame, item.card)
            if hp is not None:
                item.last_read = now
            (lost, span) = item.lost(now, hp) if hp is not None and p.ability_drop is not None else (0.0, 0.0)
            # under its share, and hit since it landed: a survivor of the last stage that comes
            # back under it waits to be hit again (not on the edge of the base)
            engaged = (hp is not None and p.ability_hp is not None and hp < p.ability_hp
                       and (item.first_hp is None or item.first_hp - hp >= _HIT))
            falling = p.ability_drop is not None and lost >= p.ability_drop
            # an ability with no deadline whose troop's health has not been read for a while
            # (no bar found on its card): on time after all, and the log says so
            blind = math.isinf(item.latest) and now - (item.landed if item.last_read is None else item.last_read) >= _BLIND_AFTER
            if engaged or falling or blind or (p.ability_hp is None and p.ability_drop is None) or now >= item.latest:
                why = f'lost {lost:.0%} in {span:.1f} s' if falling else f'no health bar read for {_BLIND_AFTER:.0f} s: on time' if blind else ''
                ready.append((hp if hp is not None else 1.0, bool(p.ability_every), item.latest, item, hp, why))
        if not ready:
            return None
        # the most hurt first; at equal health a one-time ability before a recharging one,
        # which comes back anyway (it must not starve the others), then the most overdue
        (_hp, _recharges, _latest, item, hp, why) = min(ready, key = lambda r: (r[0], r[1], r[2]))
        self.last_by_troop[item.troop] = now
        item.tries += 1
        item.health = hp
        item.why = why
        if item.profile.ability_every:
            item.earliest = item.latest = now + item.profile.ability_every
        elif item.tries >= _ABILITY_TRIES:
            self.items.remove(item)
        else:
            item.earliest = item.latest = now + _ABILITY_RECHECK  # still green by then: the tap was lost
        return item
