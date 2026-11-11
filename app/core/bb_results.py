'''The Builder Base results screen: stars, total damage, gold and trophies won.

The screen is laid out around the window's middle and scales with its height: three stars
over "Total damage: N%", the rewards to the right. A star is lit when won, gold or silver
(live: stage-1 stars came silver on some bases), and dark when not. The numbers are read by
the PP-OCR line model (:mod:`app.services.ppocr`), like the HUD's. The screen animates in
(stars one by one, the damage counting up from 0 %), so :func:`settled_result` reads it
until two reads agree.
'''
import re
import time
from dataclasses import asdict, dataclass
from typing import Optional

import cv2

from app.services import ppocr
from app.utils.logger import setup_logger

logger = setup_logger('BBResults')

# Star centres: (x from the middle, y), in screen heights. Live 1227x767: (460, 225),
# (612, 170), (762, 225).
_STARS = ((-0.2, 0.293), (0.0, 0.222), (0.193, 0.293))
_STAR_HALF = 0.029  # screen heights around a star's centre
_STAR_LIT = 0.6  # share of that box over V 170: a won star (live: 1.00 won, 0.00 not)
# (x0, x1) from the middle and (y0, y1), in screen heights
_DAMAGE = ((-0.12, 0.12), (0.407, 0.477))
_GOLD = ((0.112, 0.32), (0.597, 0.644))
_TROPHIES = ((0.165, 0.32), (0.66, 0.707))
_SETTLE_EVERY = 0.4  # s between two reads
_SETTLE_TIMEOUT = 6.0  # s
_SETTLE_MIN = 2.0  # s after the screen first shows: the damage counts up from 0 % (live: 0 % read at first sight)


@dataclass(frozen = True)
class BattleResult:
    stars: int
    damage: int  # %, up to 200 over the two stages
    gold: Optional[int] = None
    trophies: Optional[int] = None

    def as_dict(self):
        return asdict(self)


def _crop(frame, box):
    (h, w) = frame.shape[:2]
    ((x0, x1), (y0, y1)) = box
    return frame[max(0, int(y0 * h)):min(h, int(y1 * h)), max(0, int(w / 2 + x0 * h)):min(w, int(w / 2 + x1 * h))]


def _number(frame, box):
    crop = _crop(frame, box)
    if crop.size == 0:
        return None
    digits = re.sub(r'\D', '', ppocr.read_line(crop) or '')
    return int(digits) if digits else None


def stars(frame):
    '''How many of the three stars are lit.'''
    (h, w) = frame.shape[:2]
    lit = 0
    for (dx, y) in _STARS:
        (cx, cy, r) = (int(w / 2 + dx * h), int(y * h), int(_STAR_HALF * h))
        patch = frame[max(0, cy - r):cy + r, max(0, cx - r):cx + r]
        if patch.size and (cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[..., 2] >= 170).mean() >= _STAR_LIT:
            lit += 1
    return lit


def read_result(frame):
    ''':class:`BattleResult` of the results screen on ``frame``, or None when its damage
    does not read (another screen, or no OCR model).'''
    damage = _number(frame, _DAMAGE)
    if damage is None or damage > 200:
        return None
    return BattleResult(stars(frame), damage, _number(frame, _GOLD), _number(frame, _TROPHIES))


def settled_result(capture, wait, monotonic = time.monotonic, read = None):
    '''The results screen once its animation is over: read every :data:`_SETTLE_EVERY` s
    until two reads agree (after :data:`_SETTLE_MIN`), or the last read after
    :data:`_SETTLE_TIMEOUT`. ``capture()`` gives a frame, ``wait(s)`` is true when the run
    stops; ``read(frame)`` reads one (default :func:`read_result`; the Home Village's is
    :func:`app.core.hv_results.read_result`).'''
    read = read or read_result
    start = monotonic()
    (last, result) = (None, None)
    while True:
        frame = capture()
        result = read(frame) if frame is not None else None
        if result is not None and result == last and monotonic() - start >= _SETTLE_MIN:
            return result
        last = result if result is not None else last
        if monotonic() - start >= _SETTLE_TIMEOUT or wait(_SETTLE_EVERY):
            return last
