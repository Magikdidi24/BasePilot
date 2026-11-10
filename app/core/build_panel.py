'''October 2026 Build panel: free builders and researchers, the card list, and the
upgrade dialog, for the Home Village and the Builder Base.

The panel opens from the Build button (bottom right) on its first tab, "Buildings &
Heroes"; the second tab, "Army Upgrades", is the laboratory. Each card shows a name and
a time, and under them the cost with its resource icon (red cost = not affordable).
Tapping a card opens "Upgrade X to Level N?" with two buttons: Confirm with a magic item
(Hammer / Book of ...) and Confirm with the resource price. Without a free builder the
resource button opens "All builders are busy!", whose only button spends gems.

A gem must never be spent:
- start only when a regular builder / researcher is free: the chip count above Build is
  > 0 and its face is not the goblin (the goblin is the gem-paid extra slot);
- tap only the dialog's lime resource button: the card's resource icon on it, no gem icon,
  never the grey magic-item Confirm next to it;
- close any gem prompt the moment it shows up.

Geometry is measured on live 16:10 frames. The panel and the chips are anchored to the
right edge and scale with the screen height, so x offsets are in units of the height.
'''
import difflib
import re
import time
from dataclasses import dataclass
from statistics import median

import cv2
import numpy as np

from app.core.upgrade_menu import (
    RESOURCE_DARK,
    RESOURCE_ELIXIR,
    RESOURCE_GOLD,
    UpgradeRow,
    _parse_fraction_chip,
)
from app.core.upgrade_policy import UpgradePolicy, choose_upgrade
from app.core.village_state import read_hud_triplet_stable
from app.utils.logger import setup_logger

logger = setup_logger('BuildPanel')

TAB_BUILDINGS = 0
TAB_ARMY = 1
_TAB_TITLES = {TAB_BUILDINGS: 'Buildings & Heroes', TAB_ARMY: 'Army Upgrades'}

# Chips above the Build button, offsets from its center in 2560-wide reference px.
_BUILDER_TEXT = (-117, -195, 113, 59)  # x, y, w, h of the "0/6" text
_LAB_TEXT = (8, -185, 100, 47)  # "1/2"; lower than the builder one: the star-lab icon dips into a taller box
_BUILDER_FACE = (-91, -245, 80, 80)
_LAB_FACE = (25, -245, 80, 80)
# Panel, as (left, right) distances from the right edge in screen heights, and y fractions.
_LIST_X = (0.515, 0.010)
_LIST_Y = (0.075, 0.875)
_TITLE_Y = (0.0, 0.075)
_TABS_Y = (0.90, 0.995)
_NAME_MAX_X = 0.21  # names end before this distance from the right edge; times and costs sit right of it
_LEVEL_BADGE_X = 0.45  # the card icons (level badges, OCR junk) sit left of this distance from the right edge
_COST_MAX_X = 0.05  # cost digits start left of this distance from the right edge; the resource icon and the stopwatch right of it
_MIN_COST = 100
_MAX_COST = 40000000
_RED_COST = 0.08  # share of red pixels in the cost box that marks it unaffordable
_GEM_ICON = 'gemicon.png'
_CLOSE_TEMPLATES = ('closex.png', 'exit.png')
_CLOSE_MIN = 0.72
_FAILED_COOLDOWN = 1800  # s: a card whose start failed is left alone this long, so the next pass tries another


@dataclass(frozen = True)
class Chip:
    free: int
    total: int
    goblin: bool  # the chip shows the goblin face: only the gem-paid slot is free

    @property
    def regular_free(self):
        return 0 if self.goblin else self.free


def _x_from_right(frame, dist):
    (h, w) = frame.shape[:2]
    return int(w - dist * h)


def _region(frame, x0, y0, x1, y1):
    (h, w) = frame.shape[:2]
    (x0, y0) = (max(0, int(x0)), max(0, int(y0)))
    (x1, y1) = (min(w, int(x1)), min(h, int(y1)))
    return (x0, y0, max(1, x1 - x0), max(1, y1 - y0))


def list_region(frame):
    h = frame.shape[0]
    return _region(frame, _x_from_right(frame, _LIST_X[0]), h * _LIST_Y[0], _x_from_right(frame, _LIST_X[1]), h * _LIST_Y[1])


def _anchored(frame, config, bx, by, box):
    # 16:10 reference px, scaled by the height like the HUD itself: config.scale_scalar
    # divides by 1440 on a 16:9 window and would put every box ~11% too far.
    s = lambda v: int(round(v * frame.shape[0] / 1600))
    (dx, dy, w, h) = box
    return _region(frame, bx + s(dx), by + s(dy), bx + s(dx + w), by + s(dy + h))


def read_chips(vision, config, frame):
    '''``(builders, lab)`` :class:`Chip` from the home screen, each None when unreadable.'''
    (h, w) = frame.shape[:2]
    (bx, by) = vision.find_template(frame, 'build.png', region = _region(frame, w // 2, h // 2, w, h))
    if not bx:
        return (None, None)
    chips = []
    for (text, face, top) in ((_BUILDER_TEXT, _BUILDER_FACE, 6), (_LAB_TEXT, _LAB_FACE, 2)):
        (x, y, rw, rh) = _anchored(frame, config, bx, by, text)
        parsed = _parse_fraction_chip(frame, (x / w, y / h, rw / w, rh / h), max_total = top)
        if parsed is None:
            chips.append(None)
            continue
        goblin = vision.find_template(frame, 'goblinface.png', region = _anchored(frame, config, bx, by, face))[0] is not None
        chips.append(Chip(parsed[0], parsed[1], goblin))
    return tuple(chips)


def panel_tab(vision, frame):
    '''TAB_BUILDINGS / TAB_ARMY from the panel title, or None when no panel is open.'''
    region = _region(frame, _x_from_right(frame, _LIST_X[0]), 0, frame.shape[1], frame.shape[0] * _TITLE_Y[1])
    for tab, title in _TAB_TITLES.items():
        if vision.find_label(frame, title, region = region)[0] is not None:
            return tab
    return None


def find_tab(vision, frame, index):
    '''Center of the index-th tab, found by its "free/total" count, or None.'''
    h = frame.shape[0]
    region = _region(frame, _x_from_right(frame, _LIST_X[0] + 0.01), h * _TABS_Y[0], frame.shape[1], h * _TABS_Y[1])
    words = []
    for white in (True, False):  # the selected tab is lighter: its count may read only in one polarity
        words += vision.find_words_ocr(frame, region, white_text = white, roi_upscale = 2 if h < 1000 else 1,
                                       tesseract_config = '--psm 11 -c tessedit_char_whitelist=0123456789/') or []
    # "1/2" often reads as "2" or "/": digits or a slash mark a tab (the anvil and lock tabs have none)
    counts = []
    for w in sorted((w for w in words if re.search('[0-9/]', w.text)), key = lambda b: b.left):
        if not counts or w.left - counts[-1].left > 0.05 * h:
            counts.append(w)
    return counts[index].center if index < len(counts) else None


def _lines(words):
    '''Words grouped into text lines, top to bottom, each sorted left to right. A word joins
    the line whose median center is nearest when each of the two centers lies inside the
    other's band (the line's: its median height). The whole line is the yardstick, not its
    first word: a 4 px "=" read off a stopwatch once narrowed it and left the "3" under it
    on a line of its own, read as a cost. A sliver's band is floored at the typical word
    height: a 4 px leftover of a "New" tag must stay on its cost line, or that line loses
    the word that keeps a new building out of the candidates; tall junk still stays out.'''
    lines = []
    center = lambda b: b.top + b.height / 2
    typical = median(t.height for t in words) if words else 0
    for w in sorted(words, key = center):
        off = lambda line: abs(median(map(center, line)) - center(w))
        line = min(lines, key = off, default = None)
        if line is not None and off(line) <= 0.5 * min(median(t.height for t in line), max(w.height, typical)):
            line.append(w)
        else:
            lines.append([w])
    return [sorted(line, key = lambda b: b.left) for line in lines]


def _digits(text):
    t = text.replace('O', '0').replace('o', '0')
    return t if t.isdigit() else None


def _number(tokens):
    '''Thousands-separated digits read as separate tokens ("2", "480", "000") → int.'''
    groups = [_digits(t.text) for t in tokens]
    if not groups or None in groups:
        return None
    value = int(''.join(groups))
    return value if _MIN_COST <= value <= _MAX_COST else None


def _ocr_cost(vision, frame, box):
    '''Digits-only re-read of a cost the general pass garbled ("10 000" read "to ooo"). Two
    page modes; when both read a cost they must agree: on small text one of them drops the
    narrow "1" or reads "5" as "3", and a cost read too low must not come out of here.'''
    (x0, y0, x1, y1) = box
    h = y1 - y0
    region = _region(frame, x0 - 3 * h, y0 - 0.4 * h, x1 + 0.2 * h, y1 + 0.4 * h)
    costs = set()
    for psm in (7, 8):
        words = vision.find_words_ocr(frame, region, white_text = True, roi_upscale = 2,
                                      tesseract_config = f'--psm {psm} -c tessedit_char_whitelist=0123456789') or []
        costs.add(_number(sorted(words, key = lambda b: b.left)))
    costs.discard(None)
    return costs.pop() if len(costs) == 1 else None


def _checked_reread(vision, frame, box, column):
    '''The digit re-read of a cost column the general pass could not parse, kept only when
    it fits what that pass saw: as many digits as the column has characters when a group is
    garbled ("1s20" "000" for 1 520 000), else the clean groups as its tail. With the
    padding around the box, a re-read drops or adds a glyph (1 000 or 190 000 for "10 000"),
    and a cost read too low gets first claim in the policy.'''
    cost = _ocr_cost(vision, frame, box)
    if cost is None:
        return None
    groups = [_digits(t.text) for t in column]
    if None in groups:
        return cost if len(str(cost)) == sum(len(t.text) for t in column) else None
    return cost if str(cost).endswith(''.join(groups)) else None


def _box(tokens):
    x0 = min(t.left for t in tokens)
    y0 = min(t.top for t in tokens)
    x1 = max(t.left + t.width for t in tokens)
    y1 = max(t.top + t.height for t in tokens)
    return (x0, y0, x1, y1)


def _hsv_patch(frame, x0, y0, x1, y1):
    patch = frame[max(0, int(y0)):max(0, int(y1)), max(0, int(x0)):max(0, int(x1))]
    return cv2.cvtColor(patch, cv2.COLOR_BGR2HSV) if patch.size else None


def _redness(frame, box):
    hsv = _hsv_patch(frame, *box)
    if hsv is None:
        return 0.0
    (hh, s, v) = (hsv[..., 0], hsv[..., 1], hsv[..., 2])
    return float((((hh <= 8) | (hh >= 172)) & (s >= 120) & (v >= 120)).mean())


def _resource(frame, box):
    '''Resource icon right of a cost box.'''
    (x0, y0, x1, y1) = box
    h = y1 - y0
    return _icon(frame, (x1 + 0.2 * h, y0, x1 + 1.4 * h, y1), 0.2)


def _icon(frame, box, min_share):
    '''Gold, elixir (pink, or purple in the Builder Base) or dark elixir by colour inside
    ``box``; None when none of them covers ``min_share`` of it (a gem, a lock).'''
    hsv = _hsv_patch(frame, *box)
    if hsv is None:
        return None
    (hh, s, v) = (hsv[..., 0], hsv[..., 1], hsv[..., 2])
    shares = {
        RESOURCE_GOLD: ((hh >= 8) & (hh <= 35) & (s >= 90) & (v >= 150)).mean(),  # Builder Base gold is paler
        RESOURCE_ELIXIR: ((hh >= 120) & (hh <= 175) & (s >= 100) & (v >= 110)).mean(),
        RESOURCE_DARK: (v <= 60).mean()}
    (best, share) = max(shares.items(), key = lambda kv: kv[1])
    return best if share >= min_share else None


def parse_cards(vision, frame):
    '''Cards of the open panel tab as :class:`UpgradeRow`. Running upgrades and locked
    research come back without a cost; new buildings ("New" under the name) are left
    out, since tapping them starts placing a building on the map.'''
    (h, w) = frame.shape[:2]
    words = vision.find_words_ocr(frame, list_region(frame), white_text = True, roi_upscale = 2 if h < 1000 else 1) or []
    name_max = _x_from_right(frame, _NAME_MAX_X)
    badge_max = _x_from_right(frame, _LEVEL_BADGE_X)
    cost_max = _x_from_right(frame, _COST_MAX_X)
    rows = []
    pending = None  # (name tokens, line) of the last card name, waiting for its cost line
    for line in _lines(words):
        # Over the card icons OCR reads junk ("ont", "66"); running upgrades have no icon
        # and start their name there, so only real words count on that side.
        names = [t for t in line if t.left < name_max and any(ch.isalpha() for ch in t.text)
                 and len(t.text) >= (2 if t.left >= badge_max else 4)]
        costs = [t for t in line if name_max - 0.05 * h <= t.left < cost_max]
        is_new = any(t.text.lower() == 'new' for t in line if t.left < name_max)
        # A cost line shows a clean group of 3 digits at least, as every cost does ("4 000",
        # "10 ooo"); a glyph or two alone are an icon read as digits (a builder's face on a
        # running bar read "4 3"), not a cost to re-read.
        if pending is not None and any(len(_digits(t.text) or '') >= 3 for t in costs) and not (names and not is_new):
            (name_tokens, name_line) = pending
            pending = None
            if is_new:
                logger.debug('Build panel: skipping new building %r', ' '.join(t.text for t in name_tokens))
                continue
            # The cost is every token of the cost column, garbled groups too ("1s20" for
            # "1 520"): _number then fails and the digit re-read covers the whole cost; on
            # the clean groups alone it re-read a cost cut short (320 000 for 1 520 000).
            box = _box(costs)
            cost = _number(costs) or _checked_reread(vision, frame, box, costs)
            red = _redness(frame, box) >= _RED_COST
            rows.append(_row(name_tokens, cost if not red else None, _resource(frame, box), (not red) if cost else None))
            continue
        if names:
            if pending is not None:
                rows.append(_row(pending[0], None, None, None))  # a running upgrade: name and time only
            pending = (names, line)
    if pending is not None:
        rows.append(_row(pending[0], None, None, None))
    return rows


def _row(name_tokens, cost, resource, affordable):
    (x0, y0, x1, y1) = _box(name_tokens)
    return UpgradeRow(label = ' '.join(t.text for t in name_tokens), section = '', cost = cost, resource = resource,
                      affordable = affordable, center = ((x0 + x1) // 2, (y0 + y1) // 2), line_y = (y0 + y1) // 2)


def gem_prompt_visible(vision, frame):
    '''A dialog button with the gem icon is up (builders busy, missing resources...).'''
    (h, w) = frame.shape[:2]
    return vision.find_template(frame, _GEM_ICON, region = _region(frame, 0.15 * w, 0.2 * h, 0.85 * w, 0.9 * h))[0] is not None


def find_close(vision, frame):
    '''The red X of the dialog or prompt on top, or None. Every template is tried at the
    bot's scale before any other: the X of a dialog open over the Build panel must win
    over the panel's own X behind it, drawn smaller (exit.png at 0.8).'''
    (h, w) = frame.shape[:2]
    region = _region(frame, 0, 0, w, 0.6 * h)

    def best_at(scale):
        best = (None, None, 0.0)
        for name in _CLOSE_TEMPLATES:
            hit = vision.find_template_with_confidence(frame, name, threshold = _CLOSE_MIN, region = region, scale = scale)
            if hit[0] is not None and hit[2] > best[2]:
                best = hit
        return best[:2] if best[0] is not None else None
    return vision.with_scale_fallback(best_at)


def find_confirm_button(vision, frame, resource = None):
    '''Center of the green resource button of an open upgrade dialog, or None: lime,
    button-shaped, a resource icon at its right end (``resource`` when given), no gem.
    The price on it is lime on lime and does not OCR, so shape and icon identify it;
    the magic-item Confirm next to it is grey.'''
    (h, w) = frame.shape[:2]
    (rx, ry, rw, rh) = _region(frame, 0.08 * w, 0.62 * h, 0.94 * w, 0.98 * h)
    hsv = cv2.cvtColor(frame[ry:ry + rh, rx:rx + rw], cv2.COLOR_BGR2HSV)
    lime = ((hsv[..., 0] >= 33) & (hsv[..., 0] <= 48) & (hsv[..., 1] >= 90) & (hsv[..., 2] >= 170)).astype(np.uint8)
    lime = cv2.morphologyEx(lime, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    (n, _labels, stats, _centroids) = cv2.connectedComponentsWithStats(lime)
    for i in sorted(range(1, n), key = lambda k: -stats[k, cv2.CC_STAT_AREA]):
        (x, y, bw, bh, area) = (int(v) for v in stats[i])
        if not (0.08 * w <= bw <= 0.35 * w and 0.04 * h <= bh <= 0.18 * h and area >= 0.5 * bw * bh):
            continue
        (x, y) = (x + rx, y + ry)
        if vision.find_template(frame, _GEM_ICON, region = _region(frame, x - 0.1 * bw, y - 0.3 * bh, x + 1.2 * bw, y + 1.3 * bh))[0] is not None:
            continue
        got = _icon(frame, (x + 0.7 * bw, y, x + 1.1 * bw, y + bh), 0.08)
        if got is None or (resource is not None and got != resource):
            continue
        return (x + bw // 2, y + bh // 2)
    return None


def dialog_title_ok(vision, frame):
    '''The dialog on top is an upgrade one ("Upgrade X to Level N?", "Upgrade to level N?").'''
    (h, w) = frame.shape[:2]
    # left of the panel: its "Suggested upgrades" header must not read as a dialog title
    words = vision.find_words_ocr(frame, _region(frame, 0.12 * w, 0, 0.66 * w, 0.18 * h), white_text = True) or []
    return any(difflib.SequenceMatcher(None, t.text.lower()[:7], 'upgrade').ratio() >= 0.8 for t in words)


def wall_upgrade_button(vision, frame, resources = (RESOURCE_ELIXIR, RESOURCE_GOLD)):
    '''``(point, resource)`` of the selected wall's own Upgrade button paid with one of
    ``resources``, elixir before gold, or None. Each resource button is a tile with the price and its icon on top of a
    hammer; the Wall Ring and Upgrade More tiles have no hammer. The selection must be a
    wall: a building's bottom bar has the same hammer button.'''
    (h, w) = frame.shape[:2]
    region = _region(frame, 0, 0.45 * h, w, h)
    # the tiles do not always scale like the HUD (1.1 of the bot's template scale at 1227x767)
    hammers = vision.with_scale_fallback(lambda scale: vision.find_all_template_centers(
        frame, 'wallhammer.png', threshold = 0.75, region = region, max_matches = 6, scale = scale))
    if not hammers:
        return None
    top = min(y for (_x, y) in hammers)
    # left of the panel, whose own "Wall x 2" cards must not vouch for a selected building
    names = vision.find_words_ocr(frame, _region(frame, 0, top - 0.3 * h, 0.66 * w, top - 0.04 * h), white_text = True) or []
    if not any(re.sub('[^a-z]', '', t.text.lower()).startswith('wall') for t in names):
        return None
    tiles = {}
    for (x, y) in sorted(hammers):
        hsv = _hsv_patch(frame, x - 0.045 * h, y - 0.042 * h, x + 0.075 * h, y - 0.02 * h)  # price row above the hammer
        if hsv is None:
            continue
        (hh, sat, val) = (hsv[..., 0], hsv[..., 1], hsv[..., 2])
        # only the two wall resources count: the digits' dark outline would read as dark elixir
        gold = ((hh >= 8) & (hh <= 35) & (sat >= 120) & (val >= 150)).mean()
        elixir = ((hh >= 120) & (hh <= 175) & (sat >= 100) & (val >= 110)).mean()
        red = (((hh <= 7) | (hh >= 173)) & (sat >= 120) & (val >= 120)).mean()
        if red >= 0.03 or max(gold, elixir) < 0.04:
            continue  # red price (not affordable) or no resource icon
        tiles.setdefault(RESOURCE_GOLD if gold > elixir else RESOURCE_ELIXIR, (x, y))
    for resource in (RESOURCE_ELIXIR, RESOURCE_GOLD):
        if resource in tiles and resource in resources:
            return (tiles[resource], resource)
    return None


def _chip_text(chip):
    if chip is None:
        return '?'
    return f'{chip.free}/{chip.total}' + (' (goblin only)' if chip.goblin and chip.free else '')


class BuildPanelUpgrader:
    '''Starts one building upgrade and one research per pass from the Build panel.'''

    def __init__(self, window, input_service, vision, config, stop_event):
        self.window = window
        self.input = input_service
        self.vision = vision
        self.config = config
        self.stop_event = stop_event
        self._failed = {}  # card label -> time.monotonic() of its failed start

    def _frame(self):
        frame = self.window.screenshot()
        if frame is None or frame.size == 0:
            return None
        self.config.set_target_size_from_frame(frame)
        return frame

    def _wait(self, seconds):
        if self.stop_event.wait(seconds):
            raise InterruptedError()

    def _poll(self, probe, timeout, interval = 0.35):
        '''First non-None ``probe(frame)`` within ``timeout`` seconds.'''
        polls = max(1, int(timeout / interval))
        for i in range(polls):
            if i:
                self._wait(interval)
            frame = self._frame()
            if frame is not None:
                found = probe(frame)
                if found is not None:
                    return found
        return None

    def run_pass(self, mode, reserve_builders = 0, order = None, builder_base = False, research = True):
        '''One builder upgrade and/or one research. Returns a short note for the log/UI.'''
        frame = self._frame()
        if frame is None:
            return 'no capture'
        (builders, lab) = read_chips(self.vision, self.config, frame)
        build = builders is not None and builders.regular_free > reserve_builders
        study = research and lab is not None and lab.regular_free > 0
        state = f'builders {_chip_text(builders)}, lab {_chip_text(lab)}'
        logger.info('Build panel: %s', state)
        if not (build or study):
            return f'nothing free ({state})'
        if builder_base:
            hud = (_MAX_COST, _MAX_COST, 0)  # no dark elixir; the red/white cost says what is affordable
        else:
            hud = read_hud_triplet_stable(self._frame, self.stop_event.wait)
            if hud is None:
                return 'HUD unreadable'
        policy = UpgradePolicy(mode = mode, reserve_builders = reserve_builders, order = order or UpgradePolicy.order,
                               gold_attack_buffer = 0 if builder_base else UpgradePolicy.gold_attack_buffer)
        notes = []
        if build:
            notes.append(self._one(TAB_BUILDINGS, hud, builders.regular_free, policy, mode))
        if study:
            lab_policy = UpgradePolicy(mode = mode, reserve_builders = 0, order = policy.order, gold_attack_buffer = policy.gold_attack_buffer)
            notes.append(self._one(TAB_ARMY, hud, lab.regular_free, lab_policy, mode))
        return ', '.join(notes)

    def _one(self, tab, hud, free, policy, mode):
        what = 'upgrade' if tab == TAB_BUILDINGS else 'research'
        pick = None
        try:
            if not self._open(tab):
                return f'{what}: panel not opened'
            frame = self._frame()
            rows = parse_cards(self.vision, frame) if frame is not None else []
            now = time.monotonic()
            rows = [r for r in rows if now - self._failed.get(r.label, -_FAILED_COOLDOWN) >= _FAILED_COOLDOWN]
            pick = choose_upgrade(rows, hud, free, policy)
            logger.info('Build panel %s: %d cards, pick %s', what, len(rows), pick and (pick.label, pick.cost, pick.resource))
            if pick is None:
                return f'{what}: nothing affordable'
            if mode == 'dry':
                return f'{what}: would start {pick.label} ({pick.cost})'
            result = self._start(pick)
            if result != 'started':
                self._failed[pick.label] = time.monotonic()
        finally:
            self._close_panel()
        if result == 'started':
            frame = self._frame()
            chip = read_chips(self.vision, self.config, frame)[tab] if frame is not None else None
            if chip is not None and chip.free >= free:
                logger.warning('Build panel: %s of %s not confirmed (chip still %s)', what, pick.label, _chip_text(chip))
                result = 'started (not confirmed by the chip)'
        return f'{what}: {result} {pick.label} ({pick.cost})'

    def _open(self, tab):
        frame = self._frame()
        if frame is None:
            return False
        (h, w) = frame.shape[:2]
        (bx, by) = self.vision.find_template(frame, 'build.png', region = _region(frame, w // 2, h // 2, w, h))
        if not bx:
            logger.info('Build panel: Build button not found')
            return False
        self.input.click(bx, by, pause = 0.5, rand = False)
        if self._poll(lambda f: panel_tab(self.vision, f), 4) is None:
            return False
        if tab != TAB_BUILDINGS:
            point = find_tab(self.vision, self._frame(), tab)
            if point is None:
                logger.info('Build panel: tab %d not found', tab)
                return False
            self.input.click(*point, pause = 0.5, rand = False)
            if self._poll(lambda f: True if panel_tab(self.vision, f) == tab else None, 3) is None:
                return False
        self._wait(0.6)  # cards render a beat after the title
        return True

    def _start(self, pick):
        '''Card → its upgrade dialog → resource Confirm.'''
        self.input.click(*pick.center, pause = 0.5, rand = False)
        return self.confirm(pick.resource, pick.label)

    def confirm(self, resource, label):
        '''An upgrade dialog is opening: tap its resource button and make sure no gem
        prompt follows. "started", or why not (every dialog is closed again then).'''

        def dialog(frame):
            if gem_prompt_visible(self.vision, frame):
                return 'gem'
            if not dialog_title_ok(self.vision, frame):
                return None
            return find_confirm_button(self.vision, frame, resource)
        found = self._poll(dialog, 3.5)
        if found == 'gem' or found is None:
            self._close_dialogs()
            return 'gem prompt closed, not started:' if found == 'gem' else 'no Confirm button, not started:'
        self.input.click(*found, pause = 0.6, rand = False)
        clear = 0
        for _ in range(8):
            frame = self._frame()
            if frame is None:
                break
            if gem_prompt_visible(self.vision, frame):
                logger.warning('Build panel: gem prompt after Confirm (%s) — closing it', label)
                self._close_dialogs()
                return 'gem prompt closed, not started:'
            # two clear frames: the gem prompt can open a beat after the dialog closes
            clear = clear + 1 if not dialog_title_ok(self.vision, frame) else 0
            if clear >= 2:
                logger.info('Build panel: started %s (%s)', label, resource)
                return 'started'
            self._wait(0.4)
        self._close_dialogs()
        return 'dialog did not close, not started:'

    def _close_dialogs(self):
        for _ in range(3):
            frame = self._frame()
            point = find_close(self.vision, frame) if frame is not None else None
            if point is None:
                return
            self.input.click(*point, pause = 0.5, rand = False)

    def _close_panel(self):
        '''Taps on the X on top (the panel's own last) until the Build button is back, on
        empty ground only when no X shows (an open panel or a selected building swallows
        the next tap, including the next Attack). With the panel open the HUD shifts left
        and 'empty' can land on a button (the box at 1227x767).'''
        self._close_dialogs()
        for _ in range(3):
            frame = self._frame()
            if frame is None:
                return
            (h, w) = frame.shape[:2]
            if self.vision.find_template(frame, 'build.png', region = _region(frame, w // 2, h // 2, w, h))[0]:
                return
            self.input.click(*(find_close(self.vision, frame) or self.config.get_point('empty')), pause = 0.4, rand = False)
