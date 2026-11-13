'''The Builder Base results screen: stars, total damage, gold and trophies won.

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


def read_result(frame):
    ''':class:`BattleResult` of the results screen on ``frame``, or None when its damage
    does not read (another screen, or no OCR model).'''
    damage = _number(frame, _DAMAGE)
    if damage is None or damage > 200:
        return None
    return BattleResult(stars(frame), damage, _number(frame, _GOLD), _number(frame, _TROPHIES))
