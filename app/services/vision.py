import difflib
import math
import re
from dataclasses import dataclass
import cv2
import numpy as np
from typing import Dict, Tuple
from app.config import ASPECT_BASELINE, ASPECT_16_10, ASPECT_16_9, Config, resolve_aspect_key
from app.services import ppocr
from app.utils.common import get_template_path
from app.utils.logger import setup_logger

logger = setup_logger('VisionService')

@dataclass(frozen = True)
class OcrWordBox:
    '''A single word bounding box in **screen** coordinates (matches `screen_img`).'''
    # [recovered from bytecode: decompiler collapsed these fields into the docstring]
    left: int
    top: int
    width: int
    height: int
    text: str
    confidence: float
    line: int = -1  # the text line it was read on (its index in the read), -1 unknown

    @property
    def center(self):
        return (self.left + self.width // 2, self.top + self.height // 2)


_NUMBERS_HUD_ROI_AT_BASELINE: Dict[str, Tuple[int, int]] = {
    ASPECT_16_9: (550, 350),
    ASPECT_16_10: (600, 400) }
_NUMBERS_REF_LINE_HEIGHT_PX = 30
# Blank between two characters, in median digit widths, that means they belong to
# different numbers rather than to the same one.
_NUMBER_RUN_GAP_WIDTHS = 2.0
HUD_TOP_RIGHT_NUMBERS_ROI_UPSCALE = 3
# In a HUD number, the letters the line model can read for a digit (live: "i16" for "116").
_HUD_DIGIT_LOOKALIKES = str.maketrans({'i': '1', 'I': '1', 'l': '1', '|': '1', '!': '1', 'O': '0', 'o': '0'})

@dataclass(frozen = True)
class GroupedNumber:
    '''Merged numeric string on one text line (see :meth:`VisionService.extract_grouped_numbers_in_region`).'''
    # [recovered from bytecode: decompiler collapsed these fields into the docstring]
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float

    @property
    def center(self):
        return (self.left + self.width // 2, self.top + self.height // 2)






BOTTOM_HALF_BOT_TEMPLATES = frozenset({
    'bstar.png',
    'attack.png',
    'bbstar.png',
    'addwall.png',
    'attack2.png',
    'findnow.png',
    'settings.png',
    'endbattle.png',
    'surrender.png',
    'babydragon.png',
    'farmbattle.png',
    'removewall.png',
    'addwallfake.png',
    'upgrademore.png',
    'builder.png',
    'gbuilder.png',
    'mbuilder.png',
    'battlemachine.png',
    'flyingmachine.png',
    'removewallfake.png'})
# The builder chips moved to the bottom right in the Oct 2026 HUD (see BOTTOM_HALF_BOT_TEMPLATES).
TOP_HALF_BOT_TEMPLATES = frozenset({
    'fullecart.png',
    'fullecart2.png',
    'fullecart3.png'})
# Coarse-to-fine matching (VisionService._match_best)
_C2F_MIN_SIDE = 24  # px: shorter template side below which halving loses the pattern (boat/nboat at 20 px did)
_C2F_MIN_POSITIONS = 4096  # below this many candidate positions a direct match is as cheap
_C2F_PEAKS = 8  # coarse peaks re-scored at full resolution (a few microseconds each)
_C2F_PAD = 4  # px of slack around each coarse peak (halving rounds positions)
# Template scales tried after a miss at the bot's own (height-proportional) one, nearest
# first (VisionService.with_scale_fallback): some art is not drawn to the HUD's scale.
# GPG's 1227x767 window: the Build panel's X matches exit.png at 0.8 (0.99, 0.58 at the
# bot's scale), a selected wall's Upgrade tiles match wallhammer.png at 1.1 (0.97, 0.72).
FALLBACK_TEMPLATE_SCALES = (0.9, 1.1, 0.8)
# Button art is redrawn by game updates (Oct 2026: "Attack!" became "Battle"); the
# label text rarely changes, so these controls fall back to reading it.
# Never add confirm/Okay buttons here: a text match must not be able to spend anything.
# Find a Match is left out on purpose: the farming and ranked buttons share that label.
CONTROL_LABELS = {
    'attack.png': 'Battle',
    'attack2.png': 'Attack',
    'returnhome.png': 'Return Home',
    'returnhome2.png': 'Return Home',
    'breturnhome.png': 'Return Home',
    'chestclaim.png': 'Claim Reward',
    'surrender.png': 'Surrender',
    'endbattle.png': 'End Battle',
    'findnow.png': 'Find Now',
    'savedrecipes.png': 'Saved Recipes',
    # the tab shows the next free builder's face (goblin, not this one, when five are busy);
    # the label is the panel title, tapping it is a no-op once the tab is already open
    'buildings_tab.png': 'Buildings & Heroes'}
# OCR reads of the last frame (VisionService._ocr_lines), per region and settings: the
# readers looking at one poll's frame share them. Holding the frame keeps its id from being reused.
_OCR_CACHE = {'frame': None, 'reads': {}}
_WHITE_TEXT_BRIGHTNESS_FLOOR = 190
_TOP_CENTER_MENU_SQUARE_SIDE_AT_BASELINE: Dict[str, int] = {
    ASPECT_16_9: 1000,
    ASPECT_16_10: 1000 }

class VisionService:
    '''Handles image recognition and processing.'''
    @staticmethod
    def _template_scale_xy(screen_img):
        '''Scale from authored ref (:attr:`Config.ref_width` / ``ref_height``) to screenshot size.'''
        (h, w) = screen_img.shape[:2]
        cfg = Config()
        return (w / cfg.ref_width, h / cfg.ref_height)

    
    @staticmethod
    def _resize_template_for_screen(template, screen_img, scale = 1):
        '''Resize reference PNG templates to match the current capture, times ``scale``.'''
        (sx, sy) = VisionService._template_scale_xy(screen_img)
        (sx, sy) = (sx * scale, sy * scale)
        if abs(sx - 1) < 0.001 and abs(sy - 1) < 0.001:
            return template
        (t_h, t_w) = template.shape[:2]
        new_w = max(1, int(round(t_w * sx)))
        new_h = max(1, int(round(t_h * sy)))
        interp = cv2.INTER_AREA if min(sx, sy) < 1 else cv2.INTER_CUBIC
        return cv2.resize(template, (new_w, new_h), interpolation = interp)

    
    @staticmethod
    def with_scale_fallback(find):
        '''``find(scale)`` at the bot's own template scale (1), then at each of
:data:`FALLBACK_TEMPLATE_SCALES` while it misses (None or empty): the first hit, else the
last miss. A hit at the bot's scale costs no extra match; thresholds stay the caller's.'''
        for scale in (1,) + FALLBACK_TEMPLATE_SCALES:
            found = find(scale)
            if found:
                break
        return found

    
    @staticmethod
    def bottom_half_region(screen_img):
        '''ROI (x, y, w, h) covering the bottom half of the screenshot.'''
        (h, w) = screen_img.shape[:2]
        y0 = h // 2
        return (0, y0, w, h - y0)

    
    @staticmethod
    def top_half_region(screen_img):
        '''ROI (x, y, w, h) covering the top half of the screenshot.'''
        (h, w) = screen_img.shape[:2]
        y1 = h // 2
        return (0, 0, w, y1)

    
    @staticmethod
    def right_half_region(screen_img):
        '''ROI (x, y, w, h) covering the right half of the screenshot.'''
        (h, w) = screen_img.shape[:2]
        x0 = w // 2
        return (x0, 0, w - x0, h)

    
    @staticmethod
    def top_right_quadrant_region(screen_img):
        '''ROI (x, y, w, h) covering the top-right quarter of the screenshot.'''
        (h, w) = screen_img.shape[:2]
        x0 = w // 2
        y1 = h // 2
        return (x0, 0, w - x0, y1)

    
    @staticmethod
    def _match_best(img, tpl):
        '''``(score, (x, y))`` of the best TM_CCOEFF_NORMED match, as matchTemplate + minMaxLoc
gives it, 4-7x faster on captures. Coarse-to-fine: a half-resolution search ranks the
best few spots and only those are scored at full resolution, exactly. Kept in colour:
several templates (full-storage icons) differ from other art only by colour, and a
grayscale coarse pass picked wrong spots above the threshold at 1080p/1440p. Templates
under 24 px or small search areas are matched directly.'''
        (th, tw) = tpl.shape[:2]
        (ih, iw) = img.shape[:2]
        if min(th, tw) < _C2F_MIN_SIDE or (ih - th + 1) * (iw - tw + 1) < _C2F_MIN_POSITIONS:
            (_, max_val, _, max_loc) = cv2.minMaxLoc(cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED))
            return (max_val, max_loc)
        small_img = cv2.resize(img, (iw // 2, ih // 2), interpolation = cv2.INTER_AREA)
        small_tpl = cv2.resize(tpl, (tw // 2, th // 2), interpolation = cv2.INTER_AREA)
        coarse = cv2.matchTemplate(small_img, small_tpl, cv2.TM_CCOEFF_NORMED)
        (best_val, best_loc) = (-1.0, (0, 0))
        (sw, sh) = (max(1, tw // 4), max(1, th // 4))
        for _ in range(_C2F_PEAKS):
            (_, _, _, (cx, cy)) = cv2.minMaxLoc(coarse)
            x0 = max(0, 2 * cx - _C2F_PAD)
            y0 = max(0, 2 * cy - _C2F_PAD)
            window = img[y0:min(ih, 2 * cy + th + _C2F_PAD), x0:min(iw, 2 * cx + tw + _C2F_PAD)]
            (_, val, _, loc) = cv2.minMaxLoc(cv2.matchTemplate(window, tpl, cv2.TM_CCOEFF_NORMED))
            if val > best_val:
                (best_val, best_loc) = (val, (x0 + loc[0], y0 + loc[1]))
            coarse[max(0, cy - sh):cy + sh + 1, max(0, cx - sw):cx + sw + 1] = -2  # next peak elsewhere
        return (best_val, best_loc)

    @staticmethod
    def find_template(screen_img, template_name, threshold = 0.8, region = None, *, scale_template = True):
        '''
Finds a single occurrence of a template in the screen image.
Returns (center_x, center_y) or (None, None).
'''
        
        try:
            template_path = str(get_template_path(template_name))
            template = cv2.imread(template_path)
            if template is None:
                logger.error(f'''Template not found: {template_path}''')
                return (None, None)
            if scale_template:
                template = VisionService._resize_template_for_screen(template, screen_img)
            if region:
                (x, y, w, h) = region
                (h_screen, w_screen) = screen_img.shape[:2]
                if x + w > w_screen or y + h > h_screen:
                    logger.warning(f'''Region {region} out of bounds for image size {w_screen}x{h_screen}''')
                    return (None, None)
                search_img = screen_img[y:y + h, x:x + w]
                (offset_x, offset_y) = (x, y)  # [fix: x/y offsets were swapped -> every region search returned wrong coords]
            else:
                search_img = screen_img
                (offset_x, offset_y) = (0, 0)
            (t_h, t_w) = template.shape[:2]
            (s_h, s_w) = search_img.shape[:2]
            if t_w > s_w or t_h > s_h:
                return (None, None)
            (max_val, max_loc) = VisionService._match_best(search_img, template)
            if max_val < threshold:
                return (None, None)
            center_x = offset_x + max_loc[0] + t_w // 2
            center_y = offset_y + max_loc[1] + t_h // 2
            return (center_x, center_y)
        except Exception:
            e = None
            logger.error(f'''Error in find_template: {e}''')
            e = None
            del e
            return (None, None)
            e = None
            del e


    
    @staticmethod
    def find_template_with_confidence(screen_img, template_name, threshold = 0, region = None, *, scale = 1):
        '''
Finds a template and returns (center_x, center_y, confidence).
Confidence is 0.0-1.0 from cv2.matchTemplate TM_CCOEFF_NORMED.
Returns (None, None, confidence) if not found above threshold.
``scale`` multiplies the bot's template scale (see :meth:`with_scale_fallback`).
'''
        
        try:
            template_path = str(get_template_path(template_name))
            template = cv2.imread(template_path)
            if template is None:
                logger.error(f'''Template not found: {template_path}''')
                return (None, None, 0)
            template = VisionService._resize_template_for_screen(template, screen_img, scale)
            if region:
                (x, y, w, h) = region
                (h_screen, w_screen) = screen_img.shape[:2]
                if x + w > w_screen or y + h > h_screen:
                    return (None, None, 0)
                search_img = screen_img[y:y + h, x:x + w]
                (offset_x, offset_y) = (x, y)  # [fix: x/y offsets were swapped -> every region search returned wrong coords]
            else:
                search_img = screen_img
                (offset_x, offset_y) = (0, 0)
            (t_h, t_w) = template.shape[:2]
            (s_h, s_w) = search_img.shape[:2]
            if t_w > s_w or t_h > s_h:
                return (None, None, 0)
            (max_val, max_loc) = VisionService._match_best(search_img, template)
            if max_val < threshold:
                return (None, None, float(max_val))
            center_x = offset_x + max_loc[0] + t_w // 2
            center_y = offset_y + max_loc[1] + t_h // 2
            return (center_x, center_y, float(max_val))
        except Exception:
            e = None
            logger.error(f'''Error in find_template_with_confidence: {e}''')
            e = None
            del e
            return (None, None, 0)
            e = None
            del e


    
    @staticmethod
    def find_all_template_centers(screen_img, template_name, threshold = 0.8, region = None, *, max_matches = 12, suppress_pad_frac = 0.5, scale = 1):
        '''All non-overlapping template hits as ``(center_x, center_y)`` centers.'''
        matches = VisionService._find_template_matches(screen_img, template_name, threshold, region, max_matches = max_matches, suppress_pad_frac = suppress_pad_frac, scale = scale)
        return [ (int(left) + int(tw) // 2, int(top) + int(th) // 2) for left, top, tw, th, _score in matches ]
        _score = None
        th = None
        tw = None
        top = None
        left = None

    
    @staticmethod
    def _template_best_match(screen_img, template_name, region = None):
        '''Best ``TM_CCOEFF_NORMED`` score and match center ``(x, y)``, or ``(0.0, None, None)``.'''
        
        try:
            template_path = str(get_template_path(template_name))
            template = cv2.imread(template_path)
            if template is None:
                logger.error(f'''Template not found: {template_path}''')
                return (0, None, None)
            template = VisionService._resize_template_for_screen(template, screen_img)
            if region:
                (x, y, w, h) = region
                (h_screen, w_screen) = screen_img.shape[:2]
                if x + w > w_screen or y + h > h_screen:
                    return (0, None, None)
                search_img = screen_img[y:y + h, x:x + w]
                (offset_x, offset_y) = (x, y)  # [fix: x/y offsets were swapped -> every region search returned wrong coords]
            else:
                search_img = screen_img
                (offset_x, offset_y) = (0, 0)
            (t_h, t_w) = template.shape[:2]
            (s_h, s_w) = search_img.shape[:2]
            if t_w > s_w or t_h > s_h:
                return (0, None, None)
            (max_val, max_loc) = VisionService._match_best(search_img, template)
            center_x = offset_x + max_loc[0] + t_w // 2
            center_y = offset_y + max_loc[1] + t_h // 2
            return (float(max_val), center_x, center_y)
        except Exception:
            e = None
            logger.error(f'''Error in _template_best_match ({template_name}): {e}''')
            e = None
            del e
            return (0, None, None)
            e = None
            del e


    
    @staticmethod
    def find_active_over_disabled_template(screen_img, active_template, disabled_template, region = None, threshold = 0.8):
        '''
Match active vs disabled (grayed/red) UI variants of the same control.

Each PNG is matched once via ``minMaxLoc`` (single best peak in ``region``). Among
active and disabled scores that meet ``threshold``, only the **highest** score is
considered; the active center is returned when that winner is the active template,
otherwise ``(None, None)`` (disabled/grayed control).

Falls back to ``find_template`` when the disabled PNG is missing (e.g. 16:10 pack).
'''
        disabled_path = get_template_path(disabled_template)
        if not disabled_path.exists():
            return VisionService.find_template(screen_img, active_template, threshold = threshold, region = region)
        (active_score, ax, ay) = VisionService._template_best_match(screen_img, active_template, region = region)
        (disabled_score, dx, dy) = VisionService._template_best_match(screen_img, disabled_template, region = region)
        best_score = -1
        best_is_active = False
        best_x = None
        best_y = None
        for score, x, y, is_active in ((active_score, ax, ay, True), (disabled_score, dx, dy, False)):
            if not score >= threshold:
                continue
            if x is None:
                continue
            if y is None:
                continue
            if not score > best_score:
                continue
            best_score = score
            best_is_active = is_active
            (best_x, best_y) = (x, y)  # [recovered: pycdc reversed STORE_FAST_STORE_FAST pairs]
        if not best_is_active or best_x is None or best_y is None:  # [recovered: decompiler dropped the `not` — a disabled control counted as active]
            return (None, None)
        return (best_x, best_y)

    

    

    
    @staticmethod
    def yellow_fraction(bgr, *, hue_lo = 18, hue_hi = 40, sat_floor = 80, val_floor = 80):
        '''
Fraction of pixels in yellow hue (OpenCV H 0–179) with saturation and value
at least ``sat_floor`` / ``val_floor``.
'''
        if bgr is None or bgr.size == 0 or bgr.ndim != 3:
            return 0
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        sf = max(0, min(255, int(sat_floor)))
        vf = max(0, min(255, int(val_floor)))
        mask = cv2.inRange(hsv, (int(hue_lo), sf, vf), (int(hue_hi), 255, 255))
        total = int(bgr.shape[0]) * int(bgr.shape[1])
        if total > 0:
            return float(cv2.countNonZero(mask)) / float(total)
        return 0

    
    @staticmethod
    def pink_fraction(bgr, *, hue_lo = 130, hue_hi = 175, sat_floor = 80, val_floor = 80):
        '''
Fraction of pixels in pink/magenta hue (OpenCV H 0–179) with saturation and value
at least ``sat_floor`` / ``val_floor``.
'''
        if bgr is None or bgr.size == 0 or bgr.ndim != 3:
            return 0
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        sf = max(0, min(255, int(sat_floor)))
        vf = max(0, min(255, int(val_floor)))
        mask = cv2.inRange(hsv, (int(hue_lo), sf, vf), (int(hue_hi), 255, 255))
        total = int(bgr.shape[0]) * int(bgr.shape[1])
        if total > 0:
            return float(cv2.countNonZero(mask)) / float(total)
        return 0

    
    @staticmethod
    def find_active_hgoldfull(screen_img, region = None, *, template_threshold = 0.85, yellow_threshold = 0.5, max_matches = 8):
        '''
Locate a full gold storage hero-bar icon via ``hgoldfull.png`` template matching
plus per-hit yellow color verification.
'''
        matches = VisionService._find_template_matches(screen_img, 'hgoldfull.png', template_threshold, region, max_matches = max_matches)
        if not matches:
            return (None, None)
        (frame_h, frame_w) = screen_img.shape[:2]
        for left, top, tw, th, _score in sorted(matches, key = (lambda m: m[4]), reverse = True):
            x0 = max(0, min(int(left), frame_w))
            y0 = max(0, min(int(top), frame_h))
            x1 = max(0, min(int(left) + int(tw), frame_w))
            y1 = max(0, min(int(top) + int(th), frame_h))
            crop = screen_img[y0:y1, x0:x1]
            if VisionService.yellow_fraction(crop) < yellow_threshold:
                continue
            sorted(matches, key = (lambda m: m[4]), reverse = True)
            return (int(left) + int(tw) // 2, int(top) + int(th) // 2)
        return (None, None)

    
    @staticmethod
    def find_active_helixirfull(screen_img, region = None, *, template_threshold = 0.85, pink_threshold = 0.5, max_matches = 8):
        '''
Locate a full elixir storage hero-bar icon via ``helixirfull.png`` template matching
plus per-hit pink color verification.
'''
        matches = VisionService._find_template_matches(screen_img, 'helixirfull.png', template_threshold, region, max_matches = max_matches)
        if not matches:
            return (None, None)
        (frame_h, frame_w) = screen_img.shape[:2]
        for left, top, tw, th, _score in sorted(matches, key = (lambda m: m[4]), reverse = True):
            x0 = max(0, min(int(left), frame_w))
            y0 = max(0, min(int(top), frame_h))
            x1 = max(0, min(int(left) + int(tw), frame_w))
            y1 = max(0, min(int(top) + int(th), frame_h))
            crop = screen_img[y0:y1, x0:x1]
            if VisionService.pink_fraction(crop) < pink_threshold:
                continue
            sorted(matches, key = (lambda m: m[4]), reverse = True)
            return (int(left) + int(tw) // 2, int(top) + int(th) // 2)
        return (None, None)

    

    

    
    @staticmethod
    def red_hue_fraction(bgr, *, sat_floor = 40, val_floor = 40):
        '''
Fraction of pixels whose hue falls in red/orange-red ranges (OpenCV H 0–179),
with saturation and value at least ``sat_floor`` / ``val_floor``.
'''
        if bgr is None or bgr.size == 0 or bgr.ndim != 3:
            return 0
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        sf = max(0, min(255, int(sat_floor)))
        vf = max(0, min(255, int(val_floor)))
        m1 = cv2.inRange(hsv, (0, sf, vf), (10, 255, 255))
        m2 = cv2.inRange(hsv, (170, sf, vf), (180, 255, 255))
        mask = cv2.bitwise_or(m1, m2)
        total = int(bgr.shape[0]) * int(bgr.shape[1])
        if total > 0:
            return float(cv2.countNonZero(mask)) / float(total)
        return 0

    
    @staticmethod
    def _clip_rect_xywh(x, y, w, h, frame_w, frame_h):
        (x2, y2) = (x + w, y + h)  # [recovered: pycdc reversed STORE_FAST_STORE_FAST pairs]
        x0 = max(0, min(int(x), int(frame_w)))
        y0 = max(0, min(int(y), int(frame_h)))
        x1 = max(0, min(int(x2), int(frame_w)))
        y1 = max(0, min(int(y2), int(frame_h)))
        (rw, rh) = (x1 - x0, y1 - y0)  # [recovered: pycdc reversed STORE_FAST_STORE_FAST pairs]
        if rw <= 0 or rh <= 0:
            return None
        return (x0, y0, rw, rh)

    
    @staticmethod
    def _match_template_top_left(screen_img, template_name, threshold, region = None):
        '''
Best ``cv2.matchTemplate`` match: ``(left, top, t_w, t_h, score)``.
``left`` … ``t_h`` are ``None`` when below ``threshold`` or on error (``score`` still set when matching ran).
'''
        
        try:
            template_path = str(get_template_path(template_name))
            template = cv2.imread(template_path)
            if template is None:
                logger.error(f'''Template not found: {template_path}''')
                return (None, None, None, None, 0)
            template = VisionService._resize_template_for_screen(template, screen_img)
            if region:
                (x, y, w, h) = region
                (h_screen, w_screen) = screen_img.shape[:2]
                if x + w > w_screen or y + h > h_screen:
                    return (None, None, None, None, 0)
                search_img = screen_img[y:y + h, x:x + w]
                (offset_x, offset_y) = (x, y)  # [fix: x/y offsets were swapped -> every region search returned wrong coords]
            else:
                search_img = screen_img
                (offset_x, offset_y) = (0, 0)
            (t_h, t_w) = template.shape[:2]
            (s_h, s_w) = search_img.shape[:2]
            if t_w > s_w or t_h > s_h:
                return (None, None, None, None, 0)
            (max_val, max_loc) = VisionService._match_best(search_img, template)
            score = float(max_val)
            if score < threshold:
                return (None, None, None, None, score)
            left = offset_x + max_loc[0]
            top = offset_y + max_loc[1]
            return (left, top, t_w, t_h, score)
        except Exception:
            e = None
            logger.error(f'''Error in _match_template_top_left: {e}''')
            e = None
            del e
            return (None, None, None, None, 0)
            e = None
            del e


    
    @staticmethod
    def _find_template_matches(screen_img, template_name, threshold, region = None, *, max_matches = 2, suppress_pad_frac = 0.5, scale = 1):
        '''Up to ``max_matches`` non-overlapping ``matchTemplate`` hits: ``(left, top, t_w, t_h, score)``.'''
        
        try:
            template_path = str(get_template_path(template_name))
            template = cv2.imread(template_path)
            if template is None:
                logger.error(f'''Template not found: {template_path}''')
                return []
            template = VisionService._resize_template_for_screen(template, screen_img, scale)
            if region:
                (x, y, w, h) = region
                (h_screen, w_screen) = screen_img.shape[:2]
                if x + w > w_screen or y + h > h_screen:
                    return []
                search_img = screen_img[y:y + h, x:x + w]
                offset_y = y
                offset_x = x
            else:
                search_img = screen_img
                (offset_x, offset_y) = (0, 0)
            (t_h, t_w) = template.shape[:2]
            (s_h, s_w) = search_img.shape[:2]
            if t_w > s_w or t_h > s_h:
                return []
            result = cv2.matchTemplate(search_img, template, cv2.TM_CCOEFF_NORMED)
            work = result.copy()
            matches = []
            for _ in range(max(1, int(max_matches))):
                (_, max_val, _, max_loc) = cv2.minMaxLoc(work)
                score = float(max_val)
                if score < threshold:
                    range(max(1, int(max_matches)))
                    return matches
                left = offset_x + int(max_loc[0])
                top = offset_y + int(max_loc[1])
                matches.append((left, top, t_w, t_h, score))
                pad_x = max(0, int(round(t_w * suppress_pad_frac)))
                pad_y = max(0, int(round(t_h * suppress_pad_frac)))
                y0 = max(0, max_loc[1] - pad_y)
                y1 = min(work.shape[0], max_loc[1] + t_h + pad_y)
                x0 = max(0, max_loc[0] - pad_x)
                x1 = min(work.shape[1], max_loc[0] + t_w + pad_x)
                work[y0:y1, x0:x1] = 0
            return matches
        except Exception:
            e = None
            logger.error(f'''Error in _find_template_matches ({template_name}): {e}''')
            e = None
            del e
            return None
            e = None
            del e


    

    

    
    @staticmethod
    def preprocess_bw_ui_text(bgr, *, white_text = False, brightness_floor = None):
        '''
Normalize high-contrast UI text to **black glyphs on white** (single channel, 0 / 255).

``white_text=False`` (default): dark glyphs on a light background (Otsu).
``white_text=True``: light glyphs on dark; only pixels with grayscale >=
``brightness_floor`` (default :data:`_WHITE_TEXT_BRIGHTNESS_FLOOR`) count as ink
(strict, no blur), then mapped to black-on-white.
'''
        if bgr is None or bgr.size == 0:
            return bgr
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        if white_text:
            floor = _WHITE_TEXT_BRIGHTNESS_FLOOR if brightness_floor is None else max(0, min(255, int(brightness_floor)))
            bright = np.where(gray >= floor, np.uint8(255), np.uint8(0))
            binary = cv2.bitwise_not(bright)
            return binary
        (_, binary) = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    
    @staticmethod
    def scaled_top_center_menu_side(screen_w, screen_h, *, aspect_key = None):
        '''
Square side length (px) for :meth:`top_middle_square_roi` / builder-menu OCR, scaled from
the aspect baseline by **width** (``1000`` @ 2560 for both 16:10 and 16:9).
'''
        key = aspect_key or resolve_aspect_key(int(screen_w), int(screen_h))
        if key is None or key not in ASPECT_BASELINE:
            key = ASPECT_16_10
        base_side = int(_TOP_CENTER_MENU_SQUARE_SIDE_AT_BASELINE.get(key, 1000))
        (ref_w, _ref_h) = ASPECT_BASELINE[key]
        sw = max(1, int(screen_w))
        return max(1, int(round(base_side * sw / float(ref_w))))

    
    @staticmethod
    def _ocr_query_matches(raw, query_norm, *, case_sensitive, match_alnum_only, fuzzy_min_ratio):
        if not query_norm:
            return False
        
        def norm_text(s):
            s = s.strip()
            if case_sensitive:
                return s
            return s.lower()

        r = norm_text(raw)
        if query_norm in r:
            return True
        if match_alnum_only:
            ar = re.sub('[^a-z0-9]', '', r.lower())
            aq = re.sub('[^a-z0-9]', '', query_norm.lower())
            if aq and aq in ar:
                return True
            if aq and ar and ar in aq and len(ar) >= max(4, int(0.55 * len(aq))):
                return True
        if not fuzzy_min_ratio is None:
            if match_alnum_only:
                pass
            elif case_sensitive:
                pass
            
            cr = r.lower()
            cq = re.sub('[^a-z0-9]', '', query_norm.lower()) if match_alnum_only else query_norm
            if len(cq) < 3:
                return False
            (lo, hi) = sorted((len(cr), len(cq)))
            if hi and lo / hi < 0.5:
                return False
            ratio = difflib.SequenceMatcher(None, cq, cr).ratio()
            if ratio >= fuzzy_min_ratio:
                return True
        return False

    
    @staticmethod
    def _ocr_username_match_tier(raw, query_norm, *, case_sensitive, match_alnum_only, fuzzy_min_ratio):
        '''
Rank how well ``raw`` matches the username (higher is better).
Used to pick a click target: prefer full name in OCR, then longest token, then confidence.
'''
        if not query_norm:
            return 0
        
        def norm_text(s):
            s = s.strip()
            if case_sensitive:
                return s
            return s.lower()

        r = norm_text(raw)
        ar = re.sub('[^a-z0-9]', '', r.lower()) if match_alnum_only else ''
        aq = re.sub('[^a-z0-9]', '', query_norm.lower()) if match_alnum_only else ''
        if match_alnum_only and aq and aq in ar:
            return 3
        if query_norm in r:
            return 2
        if match_alnum_only and aq and ar and ar in aq and len(ar) >= max(4, int(0.55 * len(aq))):
            return 1
        return 0

    
    @staticmethod
    def _ocr_lines(screen_img, region = None, *, charset = None, single_line = False, roi_upscale = 1):
        '''The lines of text of ``region`` (the whole frame when None) read by
:mod:`app.services.ppocr`, in full-frame coordinates. A frame is read once per region and
settings: the readers looking at one poll's frame share the read. ``roi_upscale`` (> 1)
enlarges the region for the text detector (small text in a small window).'''
        if screen_img is None or getattr(screen_img, 'size', 0) == 0:
            return []
        (fh, fw) = screen_img.shape[:2]
        (x, y, w, h) = (int(v) for v in region) if region is not None else (0, 0, fw, fh)
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > fw or y + h > fh:
            logger.warning('OCR region %s out of bounds for image %dx%d', region, fw, fh)
            return []
        cache = _OCR_CACHE
        if cache['frame'] is not screen_img:
            cache.update(frame = screen_img, reads = {})
        scale = float(roi_upscale) if roi_upscale and roi_upscale > 1 and not single_line else 1.0
        key = (x, y, w, h, charset, bool(single_line), scale)
        lines = cache['reads'].get(key)
        if lines is None:
            crop = screen_img[y:y + h, x:x + w]
            if scale > 1:
                crop = cv2.resize(crop, (int(round(w * scale)), int(round(h * scale))), interpolation = cv2.INTER_CUBIC)
            lines = []
            for line in ppocr.read_lines(crop, allowed = charset, single_line = single_line):
                (x0, y0, x1, y1) = line.box
                lines.append(ppocr.Line((x + int(x0 / scale), y + int(y0 / scale), x + int(round(x1 / scale)), y + int(round(y1 / scale))),
                                        tuple(ppocr.Char(c.text, x + c.left / scale, x + c.right / scale, c.prob) for c in line.chars)))
            cache['reads'][key] = lines
        return lines


    @staticmethod
    def find_chars_ocr(screen_img, region = None, *, charset = None, single_line = False, roi_upscale = 1):
        '''Each character read in ``region`` as an :class:`OcrWordBox` in **full-frame**
coordinates (its line's top and height, its probability 0-100 as the confidence), spaces left
out. ``charset``, ``single_line``, ``roi_upscale``: see :meth:`find_words_ocr`.'''
        chars = []
        for line in VisionService._ocr_lines(screen_img, region, charset = charset, single_line = single_line, roi_upscale = roi_upscale):
            (_x0, y0, _x1, y1) = line.box
            for c in line.chars:
                if c.text.strip():
                    chars.append(OcrWordBox(left = int(round(c.left)), top = y0, width = max(1, int(round(c.right - c.left))),
                                            height = max(1, y1 - y0), text = c.text, confidence = 100.0 * c.prob))
        return chars


    @staticmethod
    def find_words_ocr(screen_img, region = None, *, query = None, case_sensitive = False, match_alnum_only = False, fuzzy_min_ratio = None, charset = None, single_line = False, roi_upscale = 1):
        '''
Locate words via OCR (:mod:`app.services.ppocr`): light text on dark and dark text on light alike.

Args:
    screen_img: BGR screenshot (e.g. from ``WindowService.screenshot()``).
    region: Optional ROI ``(x, y, w, h)`` in screen coordinates.
    query: If set, only return words whose text contains this substring (after normalization).
    case_sensitive: Match behavior when ``query`` is set.
    match_alnum_only: If True with ``query``, also match after stripping non-alphanumeric characters
        and allow substring match either way on the compact strings.
    fuzzy_min_ratio: If set (e.g. ``0.8``), also accept words whose string similarity to the
        query reaches this ratio (SequenceMatcher).
    charset: The characters the text may hold (e.g. :data:`DIGITS`): nothing else is read.
    single_line: Read the whole region as one line of text, without the detector (a cost, a
        counter cut out around its text).
    roi_upscale: Enlarge the region this much for the detector (small text in a small window).

Returns:
    List of ``OcrWordBox`` in full-screen coordinates (each word's line's top and height), the
    word's mean probability (0-100) as the confidence.
'''
        qnorm = None
        if query is not None:
            qnorm = query.strip() if case_sensitive else query.strip().lower()
        words = []
        for (i, line) in enumerate(VisionService._ocr_lines(screen_img, region, charset = charset, single_line = single_line, roi_upscale = roi_upscale)):
            (_x0, y0, _x1, y1) = line.box
            for (text, left, right, prob) in ppocr.words(line):
                if qnorm is not None and not VisionService._ocr_query_matches(text, qnorm, case_sensitive = case_sensitive, match_alnum_only = match_alnum_only, fuzzy_min_ratio = fuzzy_min_ratio):
                    continue
                words.append(OcrWordBox(left = int(round(left)), top = y0, width = max(1, int(round(right - left))),
                                        height = max(1, y1 - y0), text = text, confidence = 100.0 * prob, line = i))
        return words


    DIGITS = '0123456789'
    LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    
    @staticmethod
    def numbers_hud_roi_top_right(screen_w, screen_h):
        '''
Top-right HUD rectangle scaled from the aspect baseline: **600×400** at 16:10 (2560×1600),
**550×350** at 16:9 (2560×1440).

Returns ``(x, y, w, h)`` in screen pixels, anchored to the top-right corner.
'''
        sw = max(1, int(screen_w))
        sh = max(1, int(screen_h))
        key = resolve_aspect_key(sw, sh)
        if key is None or key not in ASPECT_BASELINE:
            key = ASPECT_16_10
        (ref_w, ref_h) = ASPECT_BASELINE[key]
        (base_rw, base_rh) = _NUMBERS_HUD_ROI_AT_BASELINE.get(key, _NUMBERS_HUD_ROI_AT_BASELINE[ASPECT_16_10])
        rw = max(1, int(round(base_rw * sw / float(ref_w))))
        rh = max(1, int(round(base_rh * sh / float(ref_h))))
        x = max(0, sw - rw)
        y = 0
        return (x, y, rw, rh)

    
    @staticmethod
    def top_middle_square_roi(screen_w, screen_h, side = None, *, aspect_key = None):
        '''
A square anchored to the **top center**: ``y = 0``, horizontal centering,
width/height at most ``side`` (clamped to the frame).

``side`` omitted → :meth:`scaled_top_center_menu_side` (~1000 px @ 2560 wide for 16:10 / 16:9).
'''
        sw = max(1, int(screen_w))
        sh = max(1, int(screen_h))
        s = int(side) if not side is None else VisionService.scaled_top_center_menu_side(sw, sh, aspect_key = aspect_key)
        rw = max(1, min(int(s), sw))
        rh = max(1, min(int(s), sh))
        x = max(0, (sw - rw) // 2)
        y = 0
        return (x, y, rw, rh)

    
    @staticmethod
    def ocr_letters_top_center(screen_img, *, side = None):
        '''
**Builder-menu style OCR:** the letter-only words of a :meth:`top_middle_square_roi` (``side``
omitted: the resolution-scaled menu square, ~1000 @ 2560), in **full-frame** coordinates.
'''
        if screen_img is None or screen_img.size == 0:
            return []
        (h_s, w_s) = screen_img.shape[:2]
        roi = VisionService.top_middle_square_roi(w_s, h_s, side = side, aspect_key = resolve_aspect_key(w_s, h_s))
        letter_only = re.compile('^[A-Za-z]+$')
        return [b for b in VisionService.find_words_ocr(screen_img, region = roi, charset = VisionService.LETTERS)
                if letter_only.fullmatch(b.text.strip())]
    @staticmethod
    def _ocr_word_y_center(box):
        return box.top + box.height * 0.5

    
    @staticmethod
    def cluster_ocr_boxes_by_y(boxes, y_tolerance):
        '''
Group OCR boxes that share a text line: union on pairs whose vertical centers
differ by at most ``y_tolerance`` px.
'''
        if not boxes:
            return []
        n = len(boxes)
        cy = [ VisionService._ocr_word_y_center(boxes[i]) for i in range(n) ]
        parent = list(range(n))
        
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        
        def union(i, j):
            (pi, pj) = (find(i), find(j))  # [recovered: pycdc reversed STORE_FAST_STORE_FAST pairs]
            if pi != pj:
                parent[pi] = pj
                return None

        tol = float(y_tolerance)
        for i in range(n):
            for j in range(i + 1, n):
                if not abs(cy[i] - cy[j]) <= tol:
                    continue
                union(i, j)
        range(n)
        groups = { }
        for i in range(n):
            r = find(i)
            groups.setdefault(r, []).append(boxes[i])
        out = list(groups.values())
        for cl in out:
            cl.sort(key = (lambda b: b.left))
        out.sort(key = (lambda cl: VisionService._ocr_word_y_center(cl[0])))
        return out
        i = None

    
    @staticmethod
    def split_cluster_on_gaps(cluster, gap_px):
        '''Split one line of character boxes wherever a horizontal gap exceeds
        ``gap_px``. Returns a list of runs, left to right.

        A line of OCR'd characters is not necessarily one number. Anything bright and
        narrow sharing the line — the "+385,306" loot floater that drifts beside the
        HUD after a raid, a lamp post behind a bar, an icon edge — is read as a digit
        and, merged into the row, silently multiplies the reading by ten or more (live:
        elixir 16,256,996 read as 116,256,996 and acted on). Digits inside a number sit
        1-3 px apart at a 1299-wide capture and 6-8 px across a thousands separator;
        anything that is not part of the number is much further away than that.
        '''
        parts = sorted(cluster or [], key = (lambda b: b.left))
        if len(parts) < 2:
            return [ list(parts) ] if parts else []
        runs = [[parts[0]]]
        for box in parts[1:]:
            prev = runs[-1][-1]
            if box.left - (prev.left + prev.width) > float(gap_px):
                runs.append([])
            runs[-1].append(box)
        return runs

    @staticmethod
    def merge_numeric_cluster(cluster, *, join_separator = ' '):
        '''
Sort left-to-right and union bounding boxes into one :class:`GroupedNumber`.

``join_separator`` defaults to a space (word-level OCR); pass ``""`` when each
:class:`OcrWordBox` already holds a single character (e.g. from
:meth:`find_chars_ocr`) so digits concatenate into one number.
'''
        if not cluster:
            return GroupedNumber('', 0, 0, 0, 0, float('nan'))
        parts = sorted(cluster, key = (lambda b: b.left))
        text = join_separator.join([ p.text.strip() for p in parts if p.text.strip() ])
        text = text.replace('l', '1')
        left = min([ p.left for p in parts ])
        top = min([ p.top for p in parts ])
        right = max([ p.left + p.width for p in parts ])
        bottom = max([ p.top + p.height for p in parts ])
        confs = [ float(p.confidence) for p in parts if not math.isnan(float(p.confidence)) ]  # [recovered: decompiler dropped the `not`, keeping only NaN confidences]
        conf = float(sum(confs) / len(confs)) if confs else float('nan')
        return GroupedNumber(text = text, left = left, top = top, width = max(1, right - left), height = max(1, bottom - top), confidence = conf)
        p = None

    
    @staticmethod
    def extract_grouped_numbers_in_region(screen_img, region, *, roi_upscale = 1, single_line = False, char_clusters_out = None):
        '''
The numbers of ``region``, each a :class:`GroupedNumber` of digits only. In each line of text,
the words holding a digit count (the letters a digit is read as are mapped back, see
:data:`_HUD_DIGIT_LOOKALIKES`), and their digits are cut into runs wherever two are further
apart than :data:`_NUMBER_RUN_GAP_WIDTHS` digit widths: a thousands space stays inside a
number, while a "+385,306" loot floater beside the HUD, a lamp post behind a bar or an icon
edge read as a digit does not join it (live: elixir 16,256,996 read as 116,256,996 once).

``char_clusters_out``: when a list, it is cleared and filled with each run's digits
(:class:`OcrWordBox`, left to right).
'''
        if char_clusters_out is not None:
            char_clusters_out.clear()
        out = []
        for line in VisionService._ocr_lines(screen_img, region, single_line = single_line, roi_upscale = roi_upscale):
            (_x0, y0, _x1, y1) = line.box
            digits = []
            word = []
            for c in line.chars + (ppocr.Char(' ', 0, 0, 0),):
                if c.text.strip():
                    word.append(c)
                    continue
                if any(k.text.isdigit() for k in word):
                    for k in word:
                        t = k.text.translate(_HUD_DIGIT_LOOKALIKES)
                        if len(t) == 1 and t.isdigit():
                            digits.append(OcrWordBox(left = int(round(k.left)), top = y0, width = max(1, int(round(k.right - k.left))),
                                                     height = max(1, y1 - y0), text = t, confidence = 100.0 * k.prob))
                word = []
            if not digits:
                continue
            med_w = float(np.median([d.width for d in digits])) or 1.0
            for run in VisionService.split_cluster_on_gaps(digits, max(3.0, med_w * _NUMBER_RUN_GAP_WIDTHS)):
                if char_clusters_out is not None:
                    char_clusters_out.append(run)
                out.append(VisionService.merge_numeric_cluster(run, join_separator = ''))
        return out


    @staticmethod
    def extract_top_right_hud_numbers(screen_img):
        '''
The numbers of the **top-right HUD** (:meth:`numbers_hud_roi_top_right`), one
:class:`GroupedNumber` per resource bar (see :meth:`_hud_numbers_ppocr`).

Updates :class:`~app.config.Config` capture size / aspect from ``screen_img`` when possible.
'''
        if screen_img is None or screen_img.size == 0:
            return []
        cfg = Config()
        cfg.set_target_size_from_frame(screen_img)
        (h_s, w_s) = screen_img.shape[:2]
        return VisionService._hud_numbers_ppocr(screen_img, VisionService.numbers_hud_roi_top_right(w_s, h_s))


    @staticmethod
    def _hud_numbers_ppocr(screen_img, region, *, roi_upscale = HUD_TOP_RIGHT_NUMBERS_ROI_UPSCALE):
        '''The HUD's number lines read by PP-OCR (:mod:`app.services.ppocr`) as
:class:`GroupedNumber` (digits only). The lines are found in the white ink of the region
(:meth:`preprocess_bw_ui_text`): digit-tall ink grouped by row. Each row is cut from the colour
frame, a little wider than its ink on the left where a 1 can still be missing, and read whole.'''
        if not ppocr.available():
            return []
        (rx, ry, rw, rh) = region
        work = screen_img[ry:ry + rh, rx:rx + rw]
        if work.size == 0:
            return []
        scale = float(roi_upscale) if roi_upscale and roi_upscale > 1 else 1.0
        if scale > 1:
            work = cv2.resize(work, (max(1, int(round(work.shape[1] * scale))), max(1, int(round(work.shape[0] * scale)))), interpolation = cv2.INTER_LINEAR)
        mono = VisionService.preprocess_bw_ui_text(work, white_text = True)
        (offset_x, offset_y) = (rx, ry)
        (n, _labels, stats, _centroids) = cv2.connectedComponentsWithStats((mono == 0).astype(np.uint8), connectivity = 8)
        blobs = [tuple(int(v) for v in stats[i][:4]) for i in range(1, n) if stats[i][3] >= 4]
        if not blobs:
            return []
        tall = float(np.median([b[3] for b in blobs if b[2] <= b[3]] or [b[3] for b in blobs]))
        glyphs = sorted((b for b in blobs if 0.6 * tall <= b[3] <= 1.6 * tall and b[2] <= 1.5 * b[3]), key = lambda b: b[1] + b[3] / 2)
        rows = []
        for b in glyphs:
            middle = b[1] + b[3] / 2
            if rows and abs(middle - rows[-1][0]) <= 0.5 * tall:
                rows[-1][1].append(b)
            else:
                rows.append([middle, [b]])
        (fh, fw) = screen_img.shape[:2]
        groups = []
        for (_middle, row) in rows:
            # A bar's number is right-aligned against its icon: from the rightmost glyph,
            # left while the gaps stay a number's (digits and thousands spaces); the bar's
            # stripes and scenery further left are not part of it (live: "2-11 320 116").
            row = sorted(row, key = lambda b: b[0])
            runs = [[row[0]]]
            for b in row[1:]:
                if b[0] - (runs[-1][-1][0] + runs[-1][-1][2]) > 0.9 * tall:
                    runs.append([])
                runs[-1].append(b)
            run = next((r for r in reversed(runs) if len(r) >= 2), None)  # a lone glyph is a bit of an icon
            if run is None:
                continue
            (x0, y0) = (run[0][0] / scale + offset_x, min(b[1] for b in run) / scale + offset_y)
            (x1, y1) = (max(b[0] + b[2] for b in run) / scale + offset_x, max(b[1] + b[3] for b in run) / scale + offset_y)
            line = y1 - y0
            crop = screen_img[max(0, int(y0 - 0.35 * line)):min(fh, int(y1 + 0.35 * line)),
                              max(0, int(x0 - 0.4 * line)):min(fw, int(x1 + 0.35 * line))]
            text = (ppocr.read_line(crop) or '').translate(_HUD_DIGIT_LOOKALIKES)
            digits = re.sub('\\D', '', text)
            if digits:
                groups.append(GroupedNumber(text = digits, left = int(x0), top = int(y0), width = max(1, int(x1 - x0)),
                                            height = max(1, int(line)), confidence = float('nan')))
        return groups
    @staticmethod
    def parse_loot_amount_from_grouped_text(text):
        '''
Parse a HUD resource quantity from OCR text (digits only; commas and spaces ignored).

Used with :meth:`extract_top_right_hud_numbers` clusters: HUD shows gold / elixir / dark
elixir left‑to‑right in the OCR ROI — take clusters sorted by horizontal center for the triplet.
'''
        digits = re.sub('\\D', '', (text or '').strip())
        if not digits:
            return None
        
        try:
            return int(digits)
        except ValueError:
            return None


    
    @staticmethod
    def parse_hud_resources_triplet(groups):
        '''
From :meth:`extract_top_right_hud_numbers` clusters, derive ``(gold, elixir, dark_elixir)``:
the home HUD stacks the three resource bars vertically (gold, elixir, dark top to bottom),
so the three **topmost** rows are taken in vertical order — one number per row, the
rightmost when a row decodes more than one. Returns ``None`` if fewer than three rows
are available.
'''
        # The HUD numbers are right-aligned, so a horizontal sort orders them by digit
        # count (7-digit elixir would land before 6-digit gold) — vertical order is the
        # only stable assignment.
        scored = []
        for g in groups:
            v = VisionService.parse_loot_amount_from_grouped_text(g.text)
            if v is None:
                continue
            cy = float(g.top) + float(g.height) * 0.5
            scored.append((cy, float(g.left) + float(g.width), v, float(g.height)))
        scored.sort(key = (lambda t: t[0]))
        if not scored:
            return None
        # One row, one number. Each bar's number is right-aligned against its resource
        # icon, so when a row yields more than one number the rightmost is the resource
        # and whatever else was on the line — a loot floater fading after a raid, a
        # piece of scenery behind the bar — is to the left of it and is not.
        row_tol = max(4.0, float(np.median([ t[3] for t in scored ])) * 0.6)
        rows = []
        for entry in scored:
            if rows and abs(entry[0] - rows[-1][0]) <= row_tol:
                if entry[1] > rows[-1][1]:
                    rows[-1] = entry
                continue
            rows.append(entry)
        if len(rows) < 3:
            return None
        return (rows[0][2], rows[1][2], rows[2][2])

    
    @staticmethod
    def _ocr_confidence_key(w):
        if math.isnan(w.confidence):
            return -1
        return float(w.confidence)

    
    @staticmethod
    def find_word_on_screen(screen_img, word_or_phrase, region = None, **kwargs):
        '''
Returns the center ``(x, y)`` of the best OCR match for ``word_or_phrase``, or
``(None, None)`` if not found.

Among all tokens that pass filters, picks by: (1) **full alnum name inside OCR token**,
(2) plain substring, (3) long name fragment, (4) fuzzy; then **longest** OCR token,
then OCR confidence — so a short side label does not beat the full username.
Extra kwargs are forwarded (e.g. ``min_confidence``, ``preprocess``).
'''
        matches = VisionService.find_words_ocr(screen_img, region = region, query = word_or_phrase, **kwargs)  # [recovered: pycdc dropped the **kwargs merge -> the name search ran without white_text, match_alnum_only or fuzzy_min_ratio]
        if not matches:
            return (None, None)
        case_sensitive = bool(kwargs.get('case_sensitive', False))
        match_alnum_only = bool(kwargs.get('match_alnum_only', False))
        fuzzy_min_ratio = kwargs.get('fuzzy_min_ratio')
        qnorm = word_or_phrase.strip() if case_sensitive else word_or_phrase.strip().lower()
        
        def pick_key(w):
            tier = VisionService._ocr_username_match_tier(w.text, qnorm, case_sensitive = case_sensitive, match_alnum_only = match_alnum_only, fuzzy_min_ratio = fuzzy_min_ratio)
            if match_alnum_only:
                alen = len(re.sub('[^a-z0-9]', '', w.text.lower()))
            else:
                alen = len(w.text.strip())
            return (tier, alen, VisionService._ocr_confidence_key(w))

        best = max(matches, key = pick_key)
        return best.center

    @staticmethod
    def _label_segments(words):
        '''Group OCR words into same-line runs. A gap wider than ~1.5 glyph heights starts
a new run, so neighbouring buttons ("Ranked Battle" beside "Battle") stay separate labels;
words the detector found on one line of text stay together whatever the gap (the "&" of
"Buildings & Heroes" reads as no character, and leaves its blank between the words).'''
        segments = []
        for w in sorted(words, key = lambda b: b.left):
            yc = w.top + w.height / 2
            line = getattr(w, 'line', -1)
            best = None
            for seg in segments:
                last = seg[-1]
                h = max(last.height, w.height)
                gap = w.left - (last.left + last.width)
                same_line = line >= 0 and getattr(last, 'line', -1) == line
                if abs(last.top + last.height / 2 - yc) <= 0.6 * h and -0.5 * h <= gap and (same_line or gap <= 1.5 * h):
                    # nearest run, not the first one created: a wide junk token must not
                    # adopt a word that sits right after its real neighbour
                    if best is None or abs(gap) < best[0]:
                        best = (abs(gap), seg)
            if best is None:
                segments.append([w])
            else:
                best[1].append(w)
        return segments

    @staticmethod
    def _label_key(text):
        '''Letters/digits only, lowercased, with the usual OCR confusions folded
(rn→m, vv→w, 0→o, 1→l, 5→s) so "Retum Home" compares equal to "Return Home".'''
        key = re.sub('[^a-z0-9]', '', text.lower()).replace('rn', 'm').replace('vv', 'w')
        return key.translate(str.maketrans('015', 'ols'))

    @staticmethod
    def _stacked(upper, lower):
        '''True when segment ``lower`` sits right under ``upper`` and overlaps it horizontally
(two-line button labels such as "Return / Home").'''
        (ux0, ux1) = (min(w.left for w in upper), max(w.left + w.width for w in upper))
        (lx0, lx1) = (min(w.left for w in lower), max(w.left + w.width for w in lower))
        h = max(w.height for w in upper + lower)
        gap = min(w.top for w in lower) - max(w.top + w.height for w in upper)
        overlap = min(ux1, lx1) - max(ux0, lx0)
        return -0.3 * h <= gap <= h and overlap > 0.3 * min(ux1 - ux0, lx1 - lx0)

    @staticmethod
    def find_label(screen_img, label, region = None, *, min_ratio = 0.85):
        '''Center of a control whose whole label reads ``label`` (case and punctuation
ignored, OCR confusions folded, fuzzy ratio >= ``min_ratio`` or the label plus at most two
stray border glyphs), or ``(None, None)``. Labels may wrap onto two lines. The region is read
once per frame (:meth:`_ocr_lines`): the labels looked up on one poll share that read.'''
        want = VisionService._label_key(label)
        words = VisionService.find_words_ocr(screen_img, region) or []
        segs = VisionService._label_segments(words)
        candidates = segs + [a + b for a in segs for b in segs if a is not b and VisionService._stacked(a, b)]
        for seg in candidates:
            got = VisionService._label_key(''.join(b.text for b in seg))
            # The run's first word must hold the label's start: "Vattack'l" is "Attack"
            # with border noise, but "d" + "Battle" is End Battle misread, not Battle.
            if not got or want[:3] not in VisionService._label_key(seg[0].text):
                continue
            # Extra letters only as button-border noise ("Vattack'l"), or one misread glyph
            # per ten: "Attacker" and "Attacks" are other text, not the Attack! button.
            extra = got.replace(want, '', 1) if want in got else None
            if (extra is not None and len(extra) <= 2 and set(extra) <= set('vlij')) or (len(got) - len(want) <= len(want) // 10 and difflib.SequenceMatcher(None, got, want).ratio() >= min_ratio):
                x0 = min(b.left for b in seg)
                y0 = min(b.top for b in seg)
                x1 = max(b.left + b.width for b in seg)
                y1 = max(b.top + b.height for b in seg)
                return ((x0 + x1) // 2, (y0 + y1) // 2)
        return (None, None)
    @staticmethod
    def find_control(screen_img, template_name, threshold = 0.8, region = None, *, ocr = True):
        ''':meth:`find_template`, then (when ``ocr``) the control's label from
:data:`CONTROL_LABELS` — for buttons whose art a game update redrew.'''
        (x, y) = VisionService.find_template(screen_img, template_name, threshold = threshold, region = region)
        label = CONTROL_LABELS.get(template_name)
        if x or not ocr or label is None:
            return (x, y)
        (lx, ly) = VisionService.find_label(screen_img, label, region = region)
        if lx is not None:
            logger.info('%s not matched; found its label %r by OCR at (%d, %d)', template_name, label, lx, ly)
        return (lx, ly)
