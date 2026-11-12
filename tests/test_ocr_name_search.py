"""OCR name search (multi-account switch), what the OCR helpers read without the OCR models,
and how a read line becomes words and a chip's fraction."""
import unittest
from unittest.mock import patch

import numpy as np

from app.core import upgrade_menu
from app.services import ppocr
from app.services import vision as vision_module
from app.services.vision import VisionService

FRAME = np.zeros((120, 400, 3), dtype=np.uint8)
# What Bot._switch_account_and_load_home has _wait_for_player_name read the account list with.
NAME_SEARCH = dict(match_alnum_only=True, fuzzy_min_ratio=0.8)


def line(text, x0, y0, x1, y1, prob=0.95):
    """A read :class:`ppocr.Line`, its characters spread evenly over its box."""
    step = (x1 - x0) / len(text)
    return ppocr.Line((x0, y0, x1, y1), tuple(ppocr.Char(c, x0 + i * step, x0 + (i + 1) * step, prob) for (i, c) in enumerate(text)))


# An account-list row: a level badge, then the name with its underscore lost.
ACCOUNT_ROW = [line('Level', 20, 40, 70, 60), line('Chief42', 100, 40, 180, 60, 0.91)]


class OcrTestCase(unittest.TestCase):
    def setUp(self):
        vision_module._OCR_CACHE.update(frame=None, reads={})  # a read of FRAME by another test


class NameSearchTests(OcrTestCase):
    @patch.object(VisionService, 'find_words_ocr', wraps=VisionService.find_words_ocr)
    @patch.object(ppocr, 'read_lines', return_value=ACCOUNT_ROW)
    def test_name_search_options_reach_the_word_ocr(self, _engine, ocr):
        point = VisionService.find_word_on_screen(FRAME, 'Chief_42', **NAME_SEARCH)
        self.assertEqual(ocr.call_args.kwargs, dict(region=None, query='Chief_42', **NAME_SEARCH))
        self.assertEqual(point, (140, 50))  # "Chief42" matches "Chief_42" only through match_alnum_only or fuzzy_min_ratio

    @patch.object(ppocr, 'read_lines', return_value=[line('Return Home', 100, 40, 210, 60)])
    def test_words_split_on_spaces_with_their_own_boxes(self, _engine):
        words = VisionService.find_words_ocr(FRAME)
        self.assertEqual([(w.text, w.left, w.width, w.top, w.height) for w in words], [('Return', 100, 60, 40, 20), ('Home', 170, 40, 40, 20)])
        self.assertAlmostEqual(words[0].confidence, 95.0)

    @patch.object(ppocr, 'read_lines', return_value=[line('Gold 705 559', 10, 20, 130, 40), line('x 1 190 256', 10, 60, 120, 80)])
    def test_numbers_are_the_digit_runs_of_the_words_holding_a_digit(self, _engine):
        groups = VisionService.extract_grouped_numbers_in_region(FRAME, (0, 0, 400, 120))
        self.assertEqual([g.text for g in groups], ['705559', '1190256'])  # "Gold" and "x" read no digit


class MissingModelsTests(OcrTestCase):
    """Without the OCR models every read comes back empty, never an error."""

    @patch.object(ppocr, '_unavailable', True)
    def test_no_words_no_name_no_glyphs_no_line(self):
        self.assertFalse(ppocr.available())
        self.assertEqual(VisionService.find_words_ocr(FRAME), [])
        self.assertEqual(VisionService.find_word_on_screen(FRAME, 'Chief_42', **NAME_SEARCH), (None, None))
        self.assertEqual(VisionService.find_chars_ocr(FRAME), [])
        self.assertEqual(VisionService.find_label(FRAME, 'Return Home'), (None, None))
        self.assertEqual(VisionService.extract_top_right_hud_numbers(FRAME), [])
        self.assertIsNone(ppocr.read_line(FRAME))


class ChipFractionTests(unittest.TestCase):
    def test_reads_of_a_chip(self):
        wide = (0, 0, 8, 12)
        narrow = (0, 0, 4, 12)  # a 1: under half as wide as tall
        self.assertEqual(upgrade_menu._fraction('1/6', None, 6), (1, 6))
        self.assertEqual(upgrade_menu._fraction('0 / 6', None, 6), (0, 6))
        self.assertEqual(upgrade_menu._fraction('16', None, 6), (1, 6))  # the slash lost
        self.assertEqual(upgrade_menu._fraction('116', None, 6), (1, 6))  # the slash read as a 1
        self.assertIsNone(upgrade_menu._fraction('/2', None, 2))  # the free count lost
        self.assertEqual(upgrade_menu._fraction('/2', [narrow, wide, wide], 2), (1, 2))  # but its glyph is a 1
        self.assertEqual(upgrade_menu._fraction('7/2', [narrow, wide, wide], 2), (1, 2))  # whatever was read
        self.assertIsNone(upgrade_menu._fraction('8/8', None, 6))  # no village has 8 builders
        self.assertIsNone(upgrade_menu._fraction('', None, 6))


if __name__ == '__main__':
    unittest.main()
