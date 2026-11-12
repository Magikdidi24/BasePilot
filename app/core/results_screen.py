'''What the two battle results screens share (:mod:`app.core.hv_results`, the Home Village's,
and :mod:`app.core.bb_results`, the Builder Base's): both are laid out around the window's
middle and scale with its height, light the stars won, and animate in, so they are read
until two reads agree.
'''
import re
import time

import cv2

_STAR_LIT = 0.6  # share of a star's box over V 170: a won star (live: 1.00 won, 0.00 not)
_SETTLE_EVERY = 0.4  # s between two reads
_SETTLE_TIMEOUT = 6.0  # s
_SETTLE_MIN = 2.0  # s after the screen first shows: the numbers count up from 0 (live: 0 % read at first sight)


def crop(frame, box):
    '''``box``, ((x0, x1) from the middle, (y0, y1)) in screen heights, cut out of ``frame``.'''
    (h, w) = frame.shape[:2]
    ((x0, x1), (y0, y1)) = box
    return frame[max(0, int(y0 * h)):min(h, int(y1 * h)), max(0, int(w / 2 + x0 * h)):min(w, int(w / 2 + x1 * h))]


def digits(text):
    '''The number the digits of ``text`` make, or None when it holds none.'''
    found = re.sub(r'\D', '', text or '')
    return int(found) if found else None


def lit_stars(frame, stars, min_half_px = 0):
    '''How many of ``stars``, each ((x from the middle, y), half side) in screen heights, are
    lit: at least :data:`_STAR_LIT` of the star's box at V >= 170. ``min_half_px`` keeps a box
    from shrinking to nothing in a small window.'''
    (h, w) = frame.shape[:2]
    lit = 0
    for ((dx, y), half) in stars:
        (cx, cy, r) = (int(w / 2 + dx * h), int(y * h), max(min_half_px, int(half * h)))
        patch = frame[max(0, cy - r):cy + r, max(0, cx - r):cx + r]
        if patch.size and (cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[..., 2] >= 170).mean() >= _STAR_LIT:
            lit += 1
    return lit


def settled_result(capture, wait, read, monotonic = time.monotonic):
    '''The results screen once its animation is over: ``read(frame)`` every
    :data:`_SETTLE_EVERY` s until two reads agree (after :data:`_SETTLE_MIN`), or the last
    read after :data:`_SETTLE_TIMEOUT`. ``capture()`` gives a frame, ``wait(s)`` is true when
    the run stops.'''
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
