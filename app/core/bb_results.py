'''The Builder Base results screen: stars, total damage, gold and trophies won; and the
battle's damage while it goes on (:func:`live_damage`).

The screen is laid out around the window's middle and scales with its height: three stars
over "Total damage: N%", the rewards to the right. A star is lit when won, gold or silver
(live: stage-1 stars came silver on some bases), and dark when not. The numbers are read by
the PP-OCR line model (:mod:`app.services.ppocr`), like the HUD's. The screen animates in
(stars one by one, the damage counting up from 0 %), so
:func:`app.core.results_screen.settled_result` reads it until two reads agree.
'''
from dataclasses import asdict, dataclass
from typing import Optional

from app.core.results_screen import crop, digits, lit_stars
from app.services import ppocr

# Star centres, (x from the middle, y), and the half side of the box sampled around them, in
# screen heights. Live 1227x767: (460, 225), (612, 170), (762, 225).
_STARS = (((-0.2, 0.293), 0.029), ((0.0, 0.222), 0.029), ((0.193, 0.293), 0.029))
# (x0, x1) from the middle and (y0, y1), in screen heights
_DAMAGE = ((-0.12, 0.12), (0.407, 0.477))
_GOLD = ((0.112, 0.32), (0.597, 0.644))
_TROPHIES = ((0.165, 0.32), (0.66, 0.707))
# During the battle, the "Overall Damage" box at the bottom right: its number, right-aligned,
# (x0, x1) from the right edge and (y0, y1), in screen heights. Live 1227x767: x 1131-1202, y 597-615.
_LIVE_DAMAGE = ((0.02, 0.135), (0.768, 0.812))


@dataclass(frozen = True)
class BattleResult:
    stars: int
    damage: int  # %, up to 200 over the two stages
    gold: Optional[int] = None
    trophies: Optional[int] = None

    def as_dict(self):
        return asdict(self)


def _number(frame, box):
    part = crop(frame, box)
    return digits(ppocr.read_line(part)) if part.size else None


def stars(frame):
    '''How many of the three stars are lit.'''
    return lit_stars(frame, _STARS)


def live_damage(frame):
    '''The battle's damage so far, on its "Overall Damage" box: % of the two bases, up to 200
    (the second base's count goes on from the first one's 100). None when it does not read:
    another screen (they show other numbers there, never with a "%"), or no OCR model. Live,
    on two recorded runs: 918 reads in battle, never one lower than the read before it.'''
    (h, w) = frame.shape[:2]
    ((r0, r1), (y0, y1)) = _LIVE_DAMAGE
    part = frame[int(y0 * h):int(y1 * h), max(0, int(w - r1 * h)):max(0, int(w - r0 * h))]
    if not part.size:
        return None
    text = ppocr.read_line(part, allowed = '0123456789%')
    if not text or not text.endswith('%'):
        return None
    damage = digits(text)
    return damage if damage is not None and damage <= 200 else None


def read_result(frame):
    ''':class:`BattleResult` of the results screen on ``frame``, or None when its damage
    does not read (another screen, or no OCR model).'''
    damage = _number(frame, _DAMAGE)
    if damage is None or damage > 200:
        return None
    return BattleResult(stars(frame), damage, _number(frame, _GOLD), _number(frame, _TROPHIES))
