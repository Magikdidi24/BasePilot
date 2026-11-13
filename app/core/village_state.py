'''Home-village state snapshot for the auto-maxer's idle gate and the UI status panel.

Reads everything the home screen shows about "is there anything productive to do":
free builders and laboratory research slots (the x/6 and x/2 chips above the Build
button), and full gold/elixir storages (the left end of each HUD bar coloured). The chip
fields are Optional — a chip that is absent or unreadable yields ``None``, never a guess,
so the caller can be conservative. TH-agnostic by construction: villages without a lab (or
with fewer builders) simply read as ``None`` / smaller totals.

The Pet House has NO home-screen indicator (verified on live TH15 frames before the
October 2026 UI: a busy pet upgrade showed neither as a HUD chip nor as a row of the old
builder popup), so pet state is not tracked here — pets remain a manual job and never
block idling.
'''
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from app.services.vision import VisionService
from app.utils.logger import setup_logger

logger = setup_logger('VillageState')
# No village holds this much. A bigger number is the HUD reader gaining a digit: live,
# elixir read as 49,796,363 against a real 9,796,363 in the second after a purchase, and
# as 411,251,572 and 116,737,862 in the run log. The corruption is systematic while the
# resource bar animates, so two consecutive reads can agree on it and pass the stability
# check below. Set above the largest storage set in the game today (a maxed Town Hall 17
# holds a little under 25M of either) and well below a spurious extra digit. Rejecting a
# real read by mistake costs one cycle: callers treat it as an unreadable HUD, which
# falls back to the full-storage flags of the bars rather than doing anything rash.
_IMPLAUSIBLE_HUD_MAIN = 30000000


@dataclass(frozen = True)
class VillageState:
    builders: Optional[Tuple[int, int]]  # (free, total) from the builder chip
    lab: Optional[Tuple[int, int]]  # (free, total) research slots from the lab chip
    gold_full: bool  # the left end of the gold bar coloured (~96%+)
    elixir_full: bool
    captured_at: float  # time.monotonic() of the frame

    @property
    def free_builders(self):
        return self.builders[0] if self.builders else None

    @property
    def storages_full(self):
        '''Both main storages at cap — farming would earn (almost) nothing.
        Dark elixir is not read: DE overflow alone never blocks idling.'''
        return self.gold_full and self.elixir_full

    @property
    def lab_idle(self):
        '''True when the lab chip is readable and shows a free research slot.'''
        return bool(self.lab) and self.lab[0] > 0

    def summary(self):
        # A storage reads full from ~96% up (the left end of its bar coloured), not
        # at exactly 100%, so phrase it honestly as "~full".
        b = f'{self.builders[0]}/{self.builders[1]}' if self.builders else '?'
        l = f'{self.lab[0]}/{self.lab[1]}' if self.lab else '?'
        s = '~full' if self.storages_full else ('gold ~full' if self.gold_full else ('elixir ~full' if self.elixir_full else 'filling'))
        return f'builders {b} free, lab {l} free, storages {s}'


# October 2026 HUD: the gold and elixir bars sit at the top right and fill from right to
# left. Just right of a bar's left cap (live 16:10: x 1528-1540 of 1920, cap at ~1526), in
# screen heights from the right edge, plus each bar's y band.
_BAR_LEFT_END_X = (0.3267, 0.3167)
_GOLD_BAR_Y = (0.0383, 0.0483)
_ELIXIR_BAR_Y = (0.0967, 0.1067)


def is_october_hud(frame):
    from app.core.build_panel import find_build_button  # build_panel imports this module
    return find_build_button(VisionService, frame)[0] is not None


def storages_full(frame):
    '''``(gold_full, elixir_full)`` on the home screen of either village (the Builder Base's
    bars sit at the same place): a storage is full when the left end of its bar is coloured
    (~96%+). The old full-storage icons matched any filled stretch of the October 2026 bars,
    so they read "full" at 10M of 14M.'''
    if not is_october_hud(frame):
        # Not the home screen (a panel moves the bars, a dialog covers them): unknown, and
        # "full" is the claim that triggers spending, so it is not made blind. The old HUD's
        # full-storage icons are gone from the game; their templates match any bar now.
        return (False, False)
    (h, w) = frame.shape[:2]
    (x0, x1) = (int(w - _BAR_LEFT_END_X[0] * h), int(w - _BAR_LEFT_END_X[1] * h))
    gold = frame[int(_GOLD_BAR_Y[0] * h):int(_GOLD_BAR_Y[1] * h), x0:x1]
    elixir = frame[int(_ELIXIR_BAR_Y[0] * h):int(_ELIXIR_BAR_Y[1] * h), x0:x1]
    # The empty stretch of a bar is translucent: grass behind it passes the default yellow
    # test (H 34-36). The real fill is H 22-27 and bright. Elixir is magenta in the Home
    # Village (H ~150) and violet in the Builder Base (H 132-135, live GPG), close to the
    # default floor of 130: 126 leaves it room, and the empty end showed no pixel from 126
    # up on any of 444 saved home frames of either village.
    return (VisionService.yellow_fraction(gold, hue_hi = 30, val_floor = 200) >= 0.6,
            VisionService.pink_fraction(elixir, hue_lo = 126) >= 0.6)


def read_village_state(frame, config = None, goblin_slots = None):
    '''Parse a home-screen frame → :class:`VillageState`. Chip reads are OCR — callers
    that gate behavior on them should tolerate ``None`` (busy frames misread; the
    idle gate re-reads on its next wake anyway). On the October 2026 HUD the chips sit
    above the Build button; the free ones counted are the regular builders / researchers
    (:attr:`app.core.build_panel.Chip.regular_free`): the goblin (paid in gems) is never
    free for the bot (``goblin_slots``: see :func:`app.core.build_panel.read_chips`).'''
    if frame is None or frame.size == 0:
        return None
    (gold_full, elixir_full) = storages_full(frame)
    if is_october_hud(frame):
        from app.config import Config
        from app.core.build_panel import read_chips  # build_panel imports this module
        chips = read_chips(VisionService, config or Config(), frame, goblin_slots)
        (builders, lab) = ((c.regular_free, c.total) if c is not None else None for c in chips)
    else:
        (builders, lab) = (None, None)  # not the home screen: no chip to read
    state = VillageState(
        builders = builders,
        lab = lab,
        gold_full = gold_full,
        elixir_full = elixir_full,
        captured_at = time.monotonic())
    logger.debug('village state: %s', state.summary())
    return state


def read_hud_triplet_stable(capture, wait, attempts = 4):
    '''Top-right HUD (gold, elixir, dark) with consecutive-frame agreement. Single
    reads get corrupted by animations/popups crossing the HUD (live repro: elixir
    read as "115M" — 9 digits against a ~21M cap), but corruption is stochastic:
    two identical consecutive parses are trustworthy. Returns the triplet or
    ``None`` when no two consecutive reads agree.'''
    prev = None
    for i in range(max(2, attempts)):
        if i and wait(0.35):
            return None
        frame = capture()
        if frame is None or getattr(frame, 'size', 0) == 0:
            continue
        triplet = VisionService.parse_hud_resources_triplet(VisionService.extract_top_right_hud_numbers(frame))
        if triplet is None:
            prev = None
            continue
        if triplet == prev:
            (gold, elixir, _dark) = triplet
            if gold > _IMPLAUSIBLE_HUD_MAIN or elixir > _IMPLAUSIBLE_HUD_MAIN:
                logger.warning('HUD read gold=%s elixir=%s is impossibly large — treating it as unreadable', gold, elixir)
                prev = None
                continue
            return triplet
        prev = triplet
    return None


def read_village_state_stable(capture, wait, attempts = 3, goblin_slots = None):
    '''Multi-frame :func:`read_village_state`: the translucent HUD chips flicker against
    the animated village, so single-frame chip reads drop out (live repro). Merges up
    to ``attempts`` frames — first readable value per field wins; the full-storage flags
    OR across frames. ``capture()`` → frame or None; ``wait(seconds)`` → True to abort
    (stop-event semantics).'''
    merged = None
    for i in range(max(1, attempts)):
        if i and wait(0.4):
            return merged
        state = read_village_state(capture(), goblin_slots = goblin_slots)
        if state is None:
            continue
        if merged is None:
            merged = state
        else:
            merged = VillageState(
                builders = merged.builders or state.builders,
                lab = merged.lab or state.lab,
                gold_full = merged.gold_full or state.gold_full,
                elixir_full = merged.elixir_full or state.elixir_full,
                captured_at = state.captured_at)
        if merged.builders and merged.lab:
            break
    if merged is not None:
        logger.info('village state: %s', merged.summary())
    return merged
