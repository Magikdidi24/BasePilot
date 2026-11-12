"""The HUD resource numbers, read by the PP-OCR line model (app/services/ppocr.py) on live GPG
crops. Tesseract read three of these five wrong at 1227x767 (elixir 11 320 116 as 3206, gold
12 122 547 as 1212247, 12 378 152 as 12378182). PNG crops, no player name in them, the gem counts covered."""
import unittest

import cv2

from app.services import ppocr
from app.services.vision import VisionService
from tests.helpers import FIXTURES, WAYDROID, canvas


def triplet(frame):
    return VisionService.parse_hud_resources_triplet(VisionService.extract_top_right_hud_numbers(frame))


@unittest.skipUnless(ppocr.available(), 'needs OpenCV DNN and the model in app/data/ocr')
class HudNumberTests(unittest.TestCase):
    def test_home_village_hud_of_a_1227x767_window(self):
        for (name, want) in (('w0', (10041919, 11320116, 171181)), ('hv_zoom', (10041919, 11320116, 171181)),
                             ('l_home', (12122547, 10365793, 168213)), ('a_back', (12378152, 10621475, 168213))):
            self.assertEqual(triplet(canvas((f'gpg767_hud_{name}.png', 900, 0))), want, name)

    def test_builder_base_hud(self):
        # gold, elixir, then the gems: the Builder Base HUD has no dark elixir. The crop's gem
        # count is covered by the elixir bar's own "974" (a stand-in: the player's gems stay private)
        self.assertEqual(triplet(canvas(('gpg767_hud_bb_home.png', 900, 0))), (651626, 1356974, 974))

    def test_both_bars_of_a_1920x1200_crop(self):
        for (name, want) in (('hud_gold_full.jpg', ['14000000', '12720391']), ('hud_not_full.jpg', ['10922532', '12483084'])):
            frame = canvas((name, 1480, 0), size=WAYDROID)
            self.assertEqual([g.text for g in VisionService.extract_top_right_hud_numbers(frame)], want, name)

    def test_one_line(self):
        crop = cv2.imread(str(FIXTURES / 'gpg767_hud_hv_zoom.png'))[60:94, 135:285]  # the elixir bar's number
        self.assertEqual(''.join(c for c in ppocr.read_line(crop) if c.isdigit()), '11320116')


if __name__ == '__main__':
    unittest.main()
