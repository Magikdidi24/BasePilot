"""OCR name search (multi-account switch), what the OCR helpers read without the OCR models,
and how a read line becomes words and a chip's fraction."""
import unittest
from unittest.mock import patch

import numpy as np

from app.core import upgrade_menu
from app.services import ppocr
from app.services import vision as vision_module
from app.services.vision import OcrWordBox, VisionService

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
        point = VisionService.find_word_match(FRAME, 'Chief_42', **NAME_SEARCH)[0]
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


def match(raw, name):
    """The account switch's name search (NAME_SEARCH) on one read of the account list."""
    return VisionService._ocr_query_matches(raw, name, case_sensitive=False, **NAME_SEARCH)


class FuzzyNameTests(unittest.TestCase):
    def test_a_misread_letter_still_finds_the_name(self):
        # "King_Bob." read "King_B0b.": 0.86 alphanumerics to alphanumerics, 0.75 against the raw read
        self.assertTrue(match('King_B0b.', 'king_bob'))
        self.assertTrue(match('Chief_4Z', 'chief_42'))  # a letter for a digit is a misread too
        self.assertTrue(match('bobl1', 'bob11'))  # among repeated digits too
        self.assertTrue(match('xx_slayer_g9', 'xx_slayer_99'))

    def test_a_sibling_account_is_not_taken_for_the_name(self):
        # accounts numbered alike differ by a digit only: 0.8 is no misread, it is the other account
        for (raw, name) in (('Farm_2', 'farm_1'), ('Farm2', 'farm1'), ('Acc.02', 'acc.01'), ('KingFarm2l', 'kingfarm1'),
                            ('Farm21', 'farm12'), ('Acc10', 'acc01')):
            with self.subTest(raw=raw):
                self.assertFalse(match(raw, name))


class AccountNumberTests(OcrTestCase):
    """Accounts numbered alike, the number glued to the name or after a separator: the switch
    never takes one for another (it skips instead). A name that is a whole word of another
    one ("Bob" in "Bob 2") cannot be told apart (docs/two-accounts.md)."""
    def test_a_longer_number_is_another_account(self):
        for (raw, name) in (('Farm_12', 'farm_1'), ('Farm_1', 'farm_12'), ('Bob2', 'bob'), ('Farm12', 'farm1'),
                            ('Bob_2', 'bob'), ('Farm.2', 'farm'), ('Bob-1', 'bob'), ('Farm_1_2', 'farm_1')):
            with self.subTest(raw=raw, name=name):
                self.assertFalse(match(raw, name))

    def test_the_name_itself_still_matches(self):
        for (raw, name) in (('Farm_1', 'farm_1'), ('Farm_1.', 'farm_1'), ('Chief_42!', 'chief_42'), ('12Bob', 'bob'),
                            ('12.Bob', 'bob'), ('KingBob', 'kingbob')):
            with self.subTest(raw=raw, name=name):
                self.assertTrue(match(raw, name))

    def test_a_word_of_a_spaced_name_is_not_the_name(self):
        self.assertFalse(match('Farm', 'farm 1'))  # "Farm 1" reads as the words "Farm" and "1"

    def find(self, row, name):
        """Where the name search taps for ``name`` on one row, 10 px a character from x 100."""
        with patch.object(ppocr, 'read_lines', return_value=[line(row, 100, 40, 100 + 10 * len(row), 60)]):
            vision_module._OCR_CACHE.update(frame=None, reads={})
            return VisionService.find_word_match(FRAME, name, **NAME_SEARCH)[0]

    def test_a_spaced_name_is_found_on_consecutive_words(self):
        self.assertEqual(self.find('Farm 1', 'Farm 1'), (130, 50))
        self.assertEqual(self.find('Level 12 Farm 1', 'Farm 1'), (220, 50))  # the middle of "Farm 1"
        self.assertEqual(self.find('King Bob 2', 'King Bob 2'), (150, 50))

    def test_a_name_the_ocr_splits_differently_is_found(self):
        self.assertEqual(self.find('Chief 42', 'Chief_42'), (140, 50))  # the underscore read as a blank
        self.assertEqual(self.find('KingBob 2', 'King Bob 2'), (145, 50))  # a blank lost

    def test_a_run_of_words_is_never_taken_for_a_part_of_the_name(self):
        for (row, name) in (('Bob 2', 'King Bob 2'), ('Bob 2', 'Mr Bob 2'), ('Farm 12', 'The Farm 12'),
                            ('King Bob 2', 'A King Bob 2'), ('Farm 1 2', 'Farm_1')):  # other accounts' names
            with self.subTest(row=row, name=name):
                self.assertEqual(self.find(row, name), (None, None))

    def test_the_name_misread_beats_another_account_holding_a_part_of_it(self):
        lines = [line('Bob 2', 100, 40, 150, 60), line('Mr Bab 2', 100, 90, 180, 110)]  # the right account, a letter misread
        with patch.object(ppocr, 'read_lines', return_value=lines):
            vision_module._OCR_CACHE.update(frame=None, reads={})
            (x, y) = VisionService.find_word_match(FRAME, 'Mr Bob 2', **NAME_SEARCH)[0]
        self.assertEqual(y, 100)  # its row, not the "Bob 2" one

    def test_a_name_with_a_lone_symbol_is_found(self):
        self.assertEqual(self.find('Bob - 2', 'Bob - 2'), (135, 50))

    def test_a_spaced_name_is_not_found_on_another_account(self):
        for (row, name) in (('Farm 2', 'Farm 1'), ('King Bob', 'King Bob 2'), ('King Rob 3', 'King Bob 2')):
            with self.subTest(row=row, name=name):
                self.assertEqual(self.find(row, name), (None, None))

    def test_the_exact_name_beats_a_longer_word_holding_it(self):
        words = [OcrWordBox(left=100, top=40, width=80, height=20, text='KingBob', confidence=99.0),
                 OcrWordBox(left=100, top=90, width=40, height=20, text='Bob', confidence=80.0)]
        with patch.object(VisionService, 'find_words_ocr', return_value=words):
            self.assertEqual(VisionService.find_word_match(FRAME, 'Bob', **NAME_SEARCH)[:2], (words[1].center, True))

    def test_a_near_name_is_told_apart_and_the_nearest_length_wins(self):
        # no "Bob" as itself: a level badge read into it ("12Bob") before another account
        # holding it ("KingBob"), and the search says neither is the name itself
        words = [OcrWordBox(left=100, top=40, width=80, height=20, text='KingBob', confidence=99.0),
                 OcrWordBox(left=100, top=90, width=50, height=20, text='12Bob', confidence=80.0)]
        with patch.object(VisionService, 'find_words_ocr', return_value=words):
            (point, exact, rank) = VisionService.find_word_match(FRAME, 'Bob', **NAME_SEARCH)
            self.assertEqual((point, exact), (words[1].center, False))
            self.assertEqual(rank, (3, -2))  # the name inside a word, two characters over
        with patch.object(VisionService, 'find_words_ocr', return_value=[]):
            self.assertEqual(VisionService.find_word_match(FRAME, 'Bob', **NAME_SEARCH), ((None, None), False, None))


class MissingModelsTests(OcrTestCase):
    """Without the OCR models every read comes back empty, never an error."""

    @patch.object(ppocr, '_unavailable', True)
    def test_no_words_no_name_no_glyphs_no_line(self):
        self.assertFalse(ppocr.available())
        self.assertEqual(VisionService.find_words_ocr(FRAME), [])
        self.assertEqual(VisionService.find_word_match(FRAME, 'Chief_42', **NAME_SEARCH)[0], (None, None))
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
