"""Build panel cards in GPG's default 1227x767 window (1920x1200 screen), on live crops."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from app.config import Config
from app.core import build_panel as bp
from app.core.upgrade_menu import RESOURCE_DARK, RESOURCE_ELIXIR, RESOURCE_GOLD

FIXTURES = Path(__file__).parent / 'fixtures'


def canvas(name, x, y):
    """A live 1227x767 crop (no player name in it) pasted back at (x, y)."""
    frame = np.zeros((767, 1227, 3), np.uint8)
    img = cv2.imread(str(FIXTURES / f'{name}.png'))
    frame[y:y + img.shape[0], x:x + img.shape[1]] = img
    Config().set_target_size_from_frame(frame)
    return frame


def word(text, left, top, width, height):
    return SimpleNamespace(text=text, left=left, top=top, width=width, height=height)


def _vision():
    from app.services.vision import VisionService
    return VisionService


class CardTests(unittest.TestCase):
    def test_running_upgrades_have_no_cost(self):
        rows = bp.parse_cards(_vision(), canvas('gpg767_panel_hv_buildings', 824, 0))
        # the six running upgrades sit above "Suggested upgrades" (y 345): a time and a stopwatch, no cost
        self.assertEqual([(r.cost, r.resource) for r in rows if r.center[1] < 340 and (r.cost or r.resource)], [])
        self.assertEqual({(r.cost, r.resource) for r in rows if r.cost},
                         {(4000, RESOURCE_DARK), (2480000, RESOURCE_ELIXIR), (1120000, RESOURCE_GOLD)})

    def test_lab_costs_keep_every_digit(self):
        rows = bp.parse_cards(_vision(), canvas('gpg767_panel_hv_lab', 824, 0))
        # top to bottom: Skeleton Spell, Wall Breaker ("1 520 000", once read 320 000), Stone Slammer, Clone Spell
        self.assertEqual([(r.cost, r.resource) for r in rows if r.cost],
                         [(10000, RESOURCE_DARK), (1520000, RESOURCE_ELIXIR), (1400000, RESOURCE_ELIXIR),
                          (1000000, RESOURCE_ELIXIR)])


class CostLineTests(unittest.TestCase):
    """Words shaped like the 767p general pass's (no OCR run here)."""

    def test_a_tiny_token_does_not_split_its_line(self):
        # Barbarian King's running row: the stopwatch reads '=' over '3'; the 4 px high '='
        # must not narrow the line and leave the '3' on a line of its own
        row = [word('=', 1202, 122, 10, 4), word('+t', 1103, 113, 24, 22), word('Barbarian', 843, 120, 98, 13),
               word('King', 949, 120, 40, 16), word('5H', 1141, 122, 18, 10), word('19m', 1165, 122, 26, 10),
               word('3', 1199, 125, 12, 10)]
        lines = bp._lines(row + [word('Laboratory', 843, 166, 111, 13), word('1400', 1099, 186, 48, 13)])
        self.assertEqual([[t.text for t in line] for line in lines],
                         [['Barbarian', 'King', '+t', '5H', '19m', '3', '='], ['Laboratory'], ['1400']])

    def parse(self, words):
        vision = Mock()
        vision.find_words_ocr.side_effect = [words, [], []]  # the general pass, then any digit re-read finds nothing
        return (bp.parse_cards(vision, np.zeros((767, 1227, 3), np.uint8)), vision)

    def test_icon_glyphs_are_no_cost_line(self):
        # under a running upgrade: the builder's face on its bar read "4" "3", the stopwatch "3"
        (rows, vision) = self.parse([word('Barbarian', 843, 120, 98, 13), word('King', 949, 120, 40, 16),
                                     word('4', 1107, 142, 10, 10), word('3', 1137, 142, 12, 10),
                                     word('3', 1199, 142, 12, 10), word('Laboratory', 843, 166, 111, 13)])
        self.assertEqual([(r.cost, r.resource, r.affordable) for r in rows], [(None, None, None)] * 2)
        self.assertEqual(vision.find_words_ocr.call_count, 1)  # no digit re-read around them

    def test_a_garbled_group_is_not_dropped(self):
        # "2 480 000" and "1 120 000" with a group garbled: never 2 000 or 1 120; the digit
        # re-read covers every group, and not the resource icon right of them
        for costs in ([word('2', 1096, 463, 8, 12), word('a8o', 1111, 463, 36, 12), word('000', 1155, 463, 38, 12)],
                      [word('1120', 1107, 463, 40, 12), word('cco', 1155, 463, 38, 12), word('&', 1198, 463, 15, 12)]):
            (rows, vision) = self.parse([word('Blacksmith', 894, 442, 103, 12)] + costs)
            self.assertIsNone(rows[0].cost)
            (x, _y, w, _h) = vision.find_words_ocr.call_args_list[1].args[1]
            self.assertTrue(x <= costs[0].left and 1193 <= x + w < 1198, (x, w))

    def test_a_new_tag_sliver_keeps_the_card_out(self):
        # a "New" tag read as a 4 px sliver 3 px off its cost line: it must stay on that line,
        # or the line reads as the cost of the new building (tapping it places a building)
        (rows, _vision) = self.parse([word('Seeking', 895, 603, 72, 15), word('AiR', 975, 603, 28, 12),
                                      word('Mine', 1011, 603, 44, 12), word('4800', 1137, 623, 76, 12),
                                      word('Nv', 893, 630, 8, 4)])
        self.assertEqual([r.cost for r in rows if r.cost], [])

    def test_a_reread_must_fit_the_column(self):
        # "10 000" read "Jo" "000": the re-read must have 5 digits (1 000 and 190 000 came
        # out of a padded window); "000" alone: the re-read must end with it
        for (column, reread, cost) in ((['Jo', '000'], '1000', None), (['Jo', '000'], '190000', None),
                                       (['Jo', '000'], '10000', 10000), (['000'], '1500', None),
                                       (['000'], '10000', 10000)):
            vision = Mock()
            general = [word('Skeleton', 894, 375, 80, 12)] + [word(t, 1137 + 30 * i, 396, 26, 12) for (i, t) in enumerate(column)]
            vision.find_words_ocr.side_effect = [general, [], [word(reread, 1137, 396, 60, 12)]]
            rows = bp.parse_cards(vision, np.zeros((767, 1227, 3), np.uint8))
            self.assertEqual(rows[0].cost, cost, (column, reread))

    def test_digit_reread_modes_must_agree(self):
        # psm 7 then psm 8 on "1 520 000": one of them dropping a glyph makes no cost
        vision = Mock()
        for (reads, cost) in (((['120000'], ['1520000']), None), ((['1520000'], ['1520000']), 1520000),
                              (([], ['1520000']), 1520000)):
            vision.find_words_ocr.side_effect = [[word(t, 1103, 234, 90, 13) for t in r] for r in reads]
            self.assertEqual(bp._ocr_cost(vision, np.zeros((767, 1227, 3), np.uint8), (1103, 234, 1193, 247)), cost)


if __name__ == '__main__':
    unittest.main()
