"""OCR name search (multi-account switch), and what the OCR helpers read without Tesseract."""
import math
import unittest
from unittest.mock import patch

import numpy as np
import pytesseract

from app.services import ocr_backend
from app.services.vision import VisionService

FRAME = np.zeros((120, 400, 3), dtype=np.uint8)
# What Bot._switch_account_and_load_home has _wait_for_player_name read the account list with.
NAME_SEARCH = dict(min_confidence=70, tesseract_config='--psm 11', match_alnum_only=True, fuzzy_min_ratio=0.8, white_text=True)


def tesseract_words(*words):
    """pytesseract's Output.DICT for ``(text, left, top, width, height, conf)`` word boxes."""
    keys = ('text', 'left', 'top', 'width', 'height', 'conf')
    return {key: [w[i] for w in words] for (i, key) in enumerate(keys)}


# An account-list row: a level badge, then the name with its underscore lost.
ACCOUNT_ROW = tesseract_words(('Level', 20, 40, 50, 20, 95), ('Chief42', 100, 40, 80, 20, 91))


class NameSearchTests(unittest.TestCase):
    @patch.object(VisionService, 'find_words_ocr', wraps=VisionService.find_words_ocr)
    @patch.object(ocr_backend, 'image_to_data', return_value=ACCOUNT_ROW)
    def test_name_search_options_reach_the_word_ocr(self, _backend, ocr):
        point = VisionService.find_word_on_screen(FRAME, 'Chief_42', **NAME_SEARCH)
        self.assertEqual(ocr.call_args.kwargs, dict(region=None, query='Chief_42', **NAME_SEARCH))
        self.assertEqual(point, (140, 50))  # "Chief42" matches "Chief_42" only through match_alnum_only or fuzzy_min_ratio


class MissingTesseractTests(unittest.TestCase):
    """pytesseract raises TesseractNotFoundError when no tesseract binary is on the path."""

    @patch.object(VisionService, '_tesseract_missing_logged', False)
    @patch.object(ocr_backend, 'image_to_data', side_effect=pytesseract.TesseractNotFoundError)
    def test_no_words_and_no_name(self, _backend):
        with self.assertLogs('VisionService', 'ERROR'):  # reported once, then every read is empty
            self.assertEqual(VisionService.find_words_ocr(FRAME), [])
            self.assertEqual(VisionService.find_word_on_screen(FRAME, 'Chief_42', **NAME_SEARCH), (None, None))

    @patch.object(VisionService, '_tesseract_missing_logged', True)  # already reported
    @patch.object(ocr_backend, 'image_to_boxes', side_effect=pytesseract.TesseractNotFoundError)
    def test_no_glyphs(self, _backend):
        self.assertEqual(VisionService.find_chars_ocr(FRAME), [])

    @patch.object(ocr_backend, 'image_to_data', side_effect=pytesseract.TesseractNotFoundError)
    def test_glyph_confidence_is_nan(self, _backend):
        conf = VisionService._tesseract_single_glyph_confidence_psm10(np.zeros((20, 20), np.uint8), 2, 2, 12, 16)
        self.assertIsInstance(conf, float)
        self.assertTrue(math.isnan(conf))


if __name__ == '__main__':
    unittest.main()
