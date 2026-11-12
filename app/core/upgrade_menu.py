'''What the Build panel reader (:mod:`app.core.build_panel`) and the upgrade policy share.

:class:`UpgradeRow` is one upgrade card (label, cost, resource, affordability, click
point), with the resource names and the Town Hall / Wall row tests the policy needs.
:func:`_parse_fraction_chip` reads a "free/total" chip (builders, laboratory) in the part
of the frame the panel reader gives it. Vision only — no clicks.
'''
import difflib
import re
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2

from app.services import ppocr
from app.services.vision import VisionService
from app.utils.logger import setup_logger

logger = setup_logger('UpgradeMenu')

SECTION_IN_PROGRESS = 'in_progress'

RESOURCE_GOLD = 'gold'
RESOURCE_ELIXIR = 'elixir'
RESOURCE_DARK = 'dark_elixir'


@dataclass(frozen = True)
class UpgradeRow:
    '''One upgrade card of the Build panel, in full-frame coordinates.'''
    label: str
    section: str  # always '' from the Build panel, which skips running upgrades
    cost: Optional[int]  # parsed white cost; None for in-progress / red / unparsed rows
    resource: Optional[str]  # RESOURCE_* from the icon right of the cost; None when unknown
    affordable: Optional[bool]  # True: white cost parsed; False: cost zone reads red; None: unknown
    center: Tuple[int, int]  # label center — the row's click target


def _normalize_label(text):
    return ' '.join((text or '').lower().split())


def is_wall_row(row):
    return any(t.startswith('wall') for t in _normalize_label(row.label).split())


def is_town_hall_row(row):
    '''The village's hall: the Town Hall, or the Builder Hall in the Builder Base (maxer
    keeps it, rusher takes it first). Fuzzy on purpose — this exclusion is what keeps the
    maxer off the hall, and OCR mangles the label ('TownMall', 'TownHail', 'TownHali' —
    all live) past any exact substring check. Priciest-first made this a live bug: the TH
    row is the most expensive row on the board, so a mangled TH label became the top pick.
    A label cut down to its first word ('Town', 'Towm') still counts: no other building
    name starts with Town (Tower and Tornado do not match the pattern).'''
    compact = _normalize_label(row.label).replace(' ', '')
    if 'townhall' in compact or 'builderhall' in compact:
        return True
    if re.match('to(w|v|vv)[nmh]', compact) or re.fullmatch('bui?lder', compact):
        return True  # 'Town', 'Towm', 'Tovvn' (not 'Tower', 'Tornado'); 'Builder' alone (a cut Barracks waits one pass)
    # Probe the prefix too: trailing OCR junk ('townmallx2') dilutes the full-string
    # ratio below threshold while the first chars still read as the hall.
    return any(difflib.SequenceMatcher(None, probe, 'townhall').ratio() >= 0.8 for probe in (compact, compact[:8])) \
        or any(difflib.SequenceMatcher(None, probe, 'builderhall').ratio() >= 0.8 for probe in (compact, compact[:11]))


# The 1 is the chip font's only narrow glyph (width 0.3-0.45 of its height; the other
# digits and the slash 0.6 and up). Small, it is the glyph OCR loses (Tesseract read it as a
# V, or merged it into the slash: live 1227x767, "1/2" read "2"): its shape reads it.
_ONE_MAX_ASPECT = 0.5
_CHIP_LINE_MARGIN = 0.3  # blank around the glyphs in the OCR line, in glyph heights
# Shapes are only trusted in full-white ink (glyph peaks 250-255 on a clear screen). While a
# dialog's dark overlay fades in or out, the glyph whites sit near the 190 white floor, which
# keeps only bits of the strokes: a 0 breaks into arcs as narrow as a 1 (such splits peak at
# 190-201). Those frames get the line read, as before.
_CHIP_INK_MIN_PEAK = 235


def _parse_fraction_chip(frame, roi_frac, max_total):
    '''Read a "free/total" chip (above Build) → ``(free, total)`` or ``None``: the chip's line read
    whole, digits and the slash only (:mod:`app.services.ppocr`). When the ink shows the three
    glyphs, the line is cut on them, and a narrow one is a 1 from its shape whatever OCR made
    of it.'''
    if frame is None or frame.size == 0:
        return None
    (fh, fw) = frame.shape[:2]
    (rx, ry, rw, rh) = roi_frac
    roi = (int(fw * rx), int(fh * ry), int(fw * rw), int(fh * rh))
    glyphs = _chip_glyphs(frame, roi)
    if glyphs is not None:
        roi = _chip_line(frame, glyphs)
    (x, y, w, h) = roi
    text = ppocr.read_line(frame[y:y + h, x:x + w], allowed = '0123456789/') or ''
    logger.debug('chip roi=%s read %r, glyphs %s', roi, text, glyphs)
    return _fraction(text, glyphs, max_total)


def _chip_glyphs(frame, roi):
    '''The free digit, slash and total digit of a chip as frame boxes ``(x, y, w, h)``, from
    its white ink (a dark outline keeps the glyphs apart), or None unless ``roi`` holds
    exactly three glyph-tall blobs of full-white ink, none cut by its border: a cut or dimmed
    digit can look as narrow as a 1. The bits of the face above the text are much shorter
    than the glyphs.'''
    (x, y, w, h) = roi
    bgr = frame[y:y + h, x:x + w]
    mono = VisionService.preprocess_bw_ui_text(bgr, white_text = True)
    if mono is None or mono.size == 0:
        return None
    (h, w) = mono.shape[:2]
    stats = cv2.connectedComponentsWithStats((mono == 0).astype('uint8'), connectivity = 8)[2][1:, :4]
    if not len(stats):
        return None
    tallest = stats[:, 3].max()
    glyphs = sorted(tuple(int(v) for v in s) for s in stats if s[3] >= 0.75 * tallest)
    if len(glyphs) != 3 or any(gx == 0 or gy == 0 or gx + gw == w or gy + gh == h for (gx, gy, gw, gh) in glyphs):
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if any(gray[gy:gy + gh, gx:gx + gw].max() < _CHIP_INK_MIN_PEAK for (gx, gy, gw, gh) in glyphs):
        return None
    return [(x + gx, y + gy, gw, gh) for (gx, gy, gw, gh) in glyphs]


def _chip_line(frame, glyphs):
    '''The OCR box once the glyphs are known: theirs with a margin, set on the text itself
    rather than on the anchor.'''
    m = _CHIP_LINE_MARGIN * max(gh for (_x, _y, _w, gh) in glyphs)
    (fh, fw) = frame.shape[:2]
    x0 = max(0, int(min(gx for (gx, _y, _w, _h) in glyphs) - m))
    y0 = max(0, int(min(gy for (_x, gy, _w, _h) in glyphs) - m))
    x1 = min(fw, int(round(max(gx + gw for (gx, _y, gw, _h) in glyphs) + m)))
    y1 = min(fh, int(round(max(gy + gh for (_x, gy, _w, gh) in glyphs) + m)))
    return (x0, y0, x1 - x0, y1 - y0)


def _fraction(text, glyphs, max_total):
    '''``(free, total)`` from a chip's read: "1/6", or "16" when the slash is lost, or "116"
    when it is read as a 1. A narrow glyph is a 1 whatever was read. None unless both
    numbers are known and ``0 <= free <= total <= max_total``.'''
    digits = re.findall('[0-9]', text)
    slash = re.fullmatch('\\s*([0-9])?\\s*/\\s*([0-9])?\\s*', text)
    if slash:
        (free_s, total_s) = slash.groups()
    elif len(digits) == 2:
        (free_s, total_s) = digits
    elif len(digits) == 3 and digits[1] == '1':
        (free_s, total_s) = (digits[0], digits[2])
    else:
        (free_s, total_s) = (None, None)
    if glyphs is not None:
        (free_s, total_s) = ('1' if gw < _ONE_MAX_ASPECT * gh else d for ((_x, _y, gw, gh), d) in zip((glyphs[0], glyphs[2]), (free_s, total_s)))
    if free_s is None or total_s is None:
        return None
    (free, total) = (int(free_s), int(total_s))
    return (free, total) if 0 <= free <= total <= max_total else None
