'''The Home Village results screen: stars, total damage and the loot won.

The screen is laid out around the window's middle and scales with its height (live
1227x767): three stars at the top, "Total damage: N%" on the middle one, then "You got:"
the gold, elixir and dark elixir won, each number right-aligned against its icon. A star
is lit when won (live: silver) and dark when not. The numbers are read by the PP-OCR line
model (:mod:`app.services.ppocr`). The screen animates in (the damage and the loot count up
from 0), so :func:`app.core.bb_results.settled_result` reads it until two reads agree.
'''
import re
from dataclasses import asdict, dataclass
from typing import Optional

import cv2
import numpy as np

from app.services import ppocr

# Where each star is sampled: (x from the middle, y) and the half side, in screen heights.
# Live 1227x767: the side stars at (485, 160) and (740, 160); the middle one is sampled on
# its lower body (613, 158), under "Total damage: N%".
_STARS = (((-0.167, 0.209), 0.029), ((0.0, 0.206), 0.016), ((0.166, 0.209), 0.029))
_STAR_LIT = 0.6  # share of a star's box over V 170 (live: 1.00 won, 0.00 not)
# (x0, x1) from the middle and (y0, y1), in screen heights
_DAMAGE = ((-0.07, 0.075), (0.141, 0.183))
_LOOT_X = (-0.2, 0.045)  # the numbers end at the icons (+0.05)
_LOOT_ROWS = {'gold': (0.443, 0.482), 'elixir': (0.508, 0.548), 'dark': (0.574, 0.613)}
_DIGIT_GAP = 0.025  # a wider blank than a digit group's space (0.016) ends the number
_PAD = 0.008  # kept around the number for the OCR


@dataclass(frozen = True)
class HomeResult:
    stars: int
    damage: int  # %
    gold: Optional[int] = None
    elixir: Optional[int] = None
    dark: Optional[int] = None

    def as_dict(self):
        return asdict(self)


def _crop(frame, box):
    (h, w) = frame.shape[:2]
    ((x0, x1), (y0, y1)) = box
    return frame[max(0, int(y0 * h)):min(h, int(y1 * h)), max(0, int(w / 2 + x0 * h)):min(w, int(w / 2 + x1 * h))]


def _digits(text):
    digits = re.sub(r'\D', '', text or '')
    return int(digits) if digits else None


def _number_on_the_right(crop, h):
    '''The white number right-aligned in ``crop``, cut out of the base behind it (live: a
    gold-coloured building left of it read as a "U") and read; None when none shows.'''
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = (hsv[..., 2] >= 200) & (hsv[..., 1] <= 60)
    cols = np.flatnonzero(white.sum(axis = 0) >= max(2, crop.shape[0] // 10))
    if cols.size == 0:
        return None
    (gap, pad) = (max(3, int(_DIGIT_GAP * h)), max(2, int(_PAD * h)))
    left = right = int(cols[-1])
    for c in cols[::-1]:
        if left - int(c) > gap:
            break
        left = int(c)
    return _digits(ppocr.read_line(crop[:, max(0, left - pad):right + pad + 1]))


def stars(frame):
    '''How many of the three stars are lit.'''
    (h, w) = frame.shape[:2]
    lit = 0
    for ((dx, y), half) in _STARS:
        (cx, cy, r) = (int(w / 2 + dx * h), int(y * h), max(2, int(half * h)))
        patch = frame[max(0, cy - r):cy + r, max(0, cx - r):cx + r]
        if patch.size and (cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[..., 2] >= 170).mean() >= _STAR_LIT:
            lit += 1
    return lit


def read_result(frame):
    ''':class:`HomeResult` of the results screen on ``frame``, or None when its damage does
    not read (another screen, or no OCR model).'''
    crop = _crop(frame, _DAMAGE)
    damage = _digits(ppocr.read_line(crop)) if crop.size else None
    if damage is None or damage > 100:
        return None
    h = frame.shape[0]
    loot = {k: _number_on_the_right(_crop(frame, (_LOOT_X, rows)), h) for (k, rows) in _LOOT_ROWS.items()}
    return HomeResult(stars(frame), damage, **loot)


def loot_share(result, left = None, held = None):
    '''The share of the base's gold and elixir the raid took, 0-1: what it won over what
    the base held, that is the won plus what was ``left`` in it as the battle ended (its
    available loot read during the battle: many reads agree by then), else ``held`` (read
    before the battle); None when neither is known. Each is (gold, elixir, dark).'''
    if result is None or result.gold is None or result.elixir is None:
        return None
    won = result.gold + result.elixir
    if left is not None:
        total = won + int(left[0] or 0) + int(left[1] or 0)
    elif held is not None:
        total = int(held[0] or 0) + int(held[1] or 0)
    else:
        return None
    return min(1.0, won / total) if total > 0 else None
