'''Builder Base scouting: where the defender's base sits on the screen, and where along its
edge an attack goes in.

The base is not at one place on the screen: the map, and the base on it, move from one
battle and one stage to the next (live GPG: a base in the middle, one in a bottom corner
with half the map empty). Read on a quarter-size frame before the deploy:

- the floor is the map's tiled ground: smooth (the buildings, the trees around the map and
  the cliffs' rocks are rough), not the dark green of the forest, the deep blue of the
  cliffs or the cyan of the water. Its large parts in the colour of the largest one (the
  game lights the base's area: the floor fades from teal to light green there) and their
  convex hull make the map;
- the base is what stands on the map off the floor and lit (buildings, walls; the forest
  is darker): its largest cluster and the parts near it, closed over the gaps between walls
  and buildings (the game's red no-deploy zone covers them);
- troops land on the floor in a band just off the base (:data:`_BAND`), out of the HUD.

Each spot of that band is scored by the base in reach of it (troops engage at once, a
notch of the base gives more) and by its distance to the base's centre (the core, where
the Builder Hall usually is). The best spot of each side of the base is an entry; the
attack takes one of the three best sides at random, so it does not always come from the
same place, and the others are kept for when the first troop does not land.
'''
import math
import random
from dataclasses import dataclass

import cv2
import numpy as np

_WORK = 4  # the frame is read at a quarter of its size
_SMOOTH_MAX = 5.5  # grey std (3x3, quarter size) of the floor's tiles; buildings and trees are rougher
# The HUD, as (x0, y0, x1, y1) shares of the frame: the names and the timer, the troop bar,
# End Battle and the boosts, the damage counter, the speed button. Never landed on.
_HUD = ((0.0, 0.0, 1.0, 0.1), (0.0, 0.82, 1.0, 1.0), (0.0, 0.69, 0.45, 1.0), (0.8, 0.69, 1.0, 1.0), (0.92, 0.58, 1.0, 0.72))
_HUD_MARGIN = 2  # quarter-size px kept clear of the HUD
_GROUND_MIN = 0.02  # share of the frame a floor part covers
_GROUND_HUE = 28  # a floor part's hue and saturation this close to the largest one's (the lit floor fades)
_GROUND_SAT = 45
_LIT_MIN = 88  # mean V (3x3) of a base pixel: the forest (V 37-71) and the cliffs (65-82) are darker
_MERGE = 0.08  # screen heights: parts of the base this close to its largest cluster belong to it
_CLOSE = 0.035  # screen heights: the gaps closed over (between walls, buildings)
_BAND = (0.045, 0.075)  # screen heights from the base to a landing spot (its red zone is ~1 tile wide)
_REACH = 0.12  # screen heights around a spot counted as buildings in reach
_WALL = 0.008  # screen heights: half the width of what a wall is at most (~12 px thick at 767p)
_CORE_WEIGHT = 1.2  # score lost per screen height to the base's centre
_SECTORS = 12  # sides of the base, one entry each
_APART = 0.15  # screen heights between two entries (a notch by the centre is the best spot of several sides)
_PICK = (3, 2, 1)  # odds of the three best sides
_JITTER = 0.006  # screen heights along the edge, so two troops do not stack on one pixel


@dataclass
class Scouting:
    centre: tuple  # the base's centre of mass, px
    entries: list  # (x, y) px: the chosen one, then the best of each other side, best first
    valid: np.ndarray  # quarter-size mask: where troops land
    distance: np.ndarray  # quarter-size: screen heights to the base
    frame_height: int


def _hud(shape):
    (sh, sw) = shape
    mask = np.zeros(shape, np.uint8)
    for (x0, y0, x1, y1) in _HUD:
        mask[int(y0 * sh):int(math.ceil(y1 * sh)), int(x0 * sw):int(math.ceil(x1 * sw))] = 1
    return mask


def scout(frame, rng = random):
    ''':class:`Scouting` of the base on ``frame`` (the battle before the deploy), or None
    when no floor or no base is found.'''
    (h, w) = frame.shape[:2]
    small = cv2.resize(frame, (w // _WORK, h // _WORK), interpolation = cv2.INTER_AREA)
    (sh, sw) = small.shape[:2]
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).astype(np.int16)
    (hue, sat, val) = (hsv[..., 0], hsv[..., 1], hsv[..., 2])
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mean = cv2.blur(gray, (3, 3))
    rough = np.sqrt(np.maximum(cv2.blur(gray * gray, (3, 3)) - mean * mean, 0))
    hud = _hud((sh, sw))
    water = (sat >= 180) | ((hue >= 85) & (hue <= 102) & (sat >= 150))
    cliff = (sat >= 140) & (val <= 95)
    forest = (sat >= 95) & (val <= 72) & (hue >= 45) & (hue <= 78)
    floor = ((rough < _SMOOTH_MAX) & ~water & ~cliff & ~forest & (hud == 0)).astype(np.uint8)
    floor = cv2.morphologyEx(floor, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    floor = cv2.morphologyEx(floor, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    (n, labels, stats, _c) = cv2.connectedComponentsWithStats(floor, connectivity = 8)
    parts = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= _GROUND_MIN * sh * sw]
    if not parts:
        return None
    largest = max(parts, key = lambda i: stats[i, cv2.CC_STAT_AREA])
    ref = np.median(hsv[labels == largest], axis = 0)

    def alike(i):
        med = np.median(hsv[labels == i], axis = 0)
        dh = abs(med[0] - ref[0])
        return min(dh, 180 - dh) <= _GROUND_HUE and abs(med[1] - ref[1]) <= _GROUND_SAT
    ground = np.isin(labels, [i for i in parts if alike(i)]).astype(np.uint8)
    hull = cv2.convexHull(cv2.findNonZero(ground))
    on_map = np.zeros((sh, sw), np.uint8)
    cv2.fillConvexPoly(on_map, hull, 1)
    lit = cv2.blur(val.astype(np.float32), (3, 3)) >= _LIT_MIN
    objects = ((on_map > 0) & (ground == 0) & (hud == 0) & lit & ~water).astype(np.uint8)
    objects = cv2.morphologyEx(objects, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    clusters = cv2.morphologyEx(objects, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    (n, labels, stats, _c) = cv2.connectedComponentsWithStats(clusters, connectivity = 8)
    if n <= 1:
        return None
    main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    reach = 2 * int(_MERGE * sh) + 1
    near = cv2.dilate((labels == main).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (reach, reach)))
    base = (np.isin(labels, np.unique(labels[(near > 0) & (labels > 0)])) & (objects > 0)).astype(np.uint8)
    k = 2 * int(_CLOSE * sh) + 1
    base = cv2.morphologyEx(base, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    (outlines, _hierarchy) = cv2.findContours(base, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    base = np.zeros_like(base)
    cv2.drawContours(base, outlines, -1, 1, thickness = cv2.FILLED)  # walled-in floor is no-deploy
    moments = cv2.moments(base, binaryImage = True)
    if not moments['m00']:
        return None
    (cx, cy) = (moments['m10'] / moments['m00'], moments['m01'] / moments['m00'])
    distance = cv2.distanceTransform(1 - base, cv2.DIST_L2, 3) * _WORK / h
    clear = cv2.erode(1 - hud, np.ones((2 * _HUD_MARGIN + 1,) * 2, np.uint8))
    valid = (ground > 0) & (distance >= _BAND[0]) & (distance <= _BAND[1]) & (clear > 0)
    (ys, xs) = np.nonzero(valid)
    if not len(xs):
        return None
    # Targets in reach: the buildings, not the walls (thin lines, gone in an opening wider than them)
    k = 2 * int(_WALL * sh) + 1
    buildings = cv2.morphologyEx(objects, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    r = int(_REACH * sh)
    disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)).astype(np.float32)
    in_reach = cv2.filter2D(buildings.astype(np.float32), -1, disk, borderType = cv2.BORDER_CONSTANT)[ys, xs]
    score = in_reach / max(1.0, float(in_reach.max())) - _CORE_WEIGHT * np.hypot(xs - cx, ys - cy) * _WORK / h
    sector = ((np.degrees(np.arctan2(ys - cy, xs - cx)) + 360) % 360 * _SECTORS // 360).astype(int)
    best = {}
    for i in np.argsort(-score, kind = 'stable'):
        if sector[i] not in best:
            best[sector[i]] = (float(score[i]), (int(xs[i]) * _WORK + _WORK // 2, int(ys[i]) * _WORK + _WORK // 2))
    ranked = []
    for (_s, p) in sorted(best.values(), key = lambda e: -e[0]):
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= _APART * h for q in ranked):
            ranked.append(p)
    top = ranked[:len(_PICK)]
    chosen = rng.choices(top, weights = _PICK[:len(top)])[0]
    return Scouting((int(cx * _WORK), int(cy * _WORK)), [chosen] + [p for p in ranked if p != chosen], valid, distance, h)


def side(scouting, entry):
    '''Where ``entry`` lies seen from the base's centre, for the log: "top-left", ...'''
    angle = math.degrees(math.atan2(entry[1] - scouting.centre[1], entry[0] - scouting.centre[0])) % 360
    names = ('right', 'bottom-right', 'bottom', 'bottom-left', 'left', 'top-left', 'top', 'top-right')
    return names[int((angle + 22.5) // 45) % 8]


def front(scouting, entry, rng = random):
    '''The landing spots of an attack from ``entry``: ``at(offset)`` is the spot ``offset``
    screen heights along the base's edge from the entry (both ways), moved onto the
    nearest spot troops land on, so flankers hug the base's sides.'''
    h = scouting.frame_height
    (ex, ey) = (entry[0] // _WORK, entry[1] // _WORK)
    gx = cv2.Sobel(scouting.distance, cv2.CV_32F, 1, 0, ksize = 5)[ey, ex]
    gy = cv2.Sobel(scouting.distance, cv2.CV_32F, 0, 1, ksize = 5)[ey, ex]
    if math.hypot(gx, gy) < 1e-6:  # flat: away from the centre
        (gx, gy) = (entry[0] - scouting.centre[0], entry[1] - scouting.centre[1])
    norm = math.hypot(gx, gy) or 1.0
    (ux, uy) = (-gy / norm, gx / norm)  # along the edge
    (vy, vx) = np.nonzero(scouting.valid)
    (px, py) = (vx * _WORK + _WORK // 2, vy * _WORK + _WORK // 2)

    def at(offset):
        s = offset * h + rng.uniform(-_JITTER, _JITTER) * h
        (x, y) = (entry[0] + s * ux, entry[1] + s * uy)
        i = int(np.argmin((px - x) ** 2 + (py - y) ** 2))
        return (int(px[i]), int(py[i]))
    return at
