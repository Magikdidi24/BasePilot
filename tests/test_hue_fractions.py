"""The colour shares the storage bars and the clan's price veto read: the share of a patch's
pixels in a hue range, saturated and bright enough. Characterisation tests on synthetic patches."""
import unittest

import cv2
import numpy as np

from app.services.vision import VisionService as V


def patch_of(*hsv_colours):
    """A patch whose equal vertical stripes have these HSV colours (OpenCV H 0-179)."""
    stripes = [np.full((10, 10, 3), c, np.uint8) for c in hsv_colours]
    return cv2.cvtColor(np.hstack(stripes), cv2.COLOR_HSV2BGR)


class HueFractionTests(unittest.TestCase):
    def test_yellow(self):
        self.assertAlmostEqual(V.yellow_fraction(patch_of((30, 255, 255), (0, 0, 0))), 0.5)
        self.assertEqual(V.yellow_fraction(patch_of((30, 255, 150)), val_floor=200), 0.0)  # the gold bar's check
        self.assertEqual(V.yellow_fraction(patch_of((35, 255, 255)), hue_hi=30), 0.0)
        self.assertAlmostEqual(V.yellow_fraction(patch_of((30, 79, 255), (30, 80, 255))), 0.5)  # the saturation floor

    def test_pink(self):
        self.assertAlmostEqual(V.pink_fraction(patch_of((150, 255, 255), (60, 255, 255), (128, 255, 255))), 1 / 3)  # 128 < 130
        self.assertAlmostEqual(V.pink_fraction(patch_of((128, 255, 255)), hue_lo=126), 1.0)  # the elixir bar's check

    def test_red_on_both_ends_of_the_hue_circle(self):
        self.assertAlmostEqual(V.red_hue_fraction(patch_of((5, 255, 255), (175, 255, 255), (20, 255, 255), (90, 255, 255))), 0.5)
        self.assertEqual(V.red_hue_fraction(patch_of((5, 39, 255))), 0.0)  # under the default saturation floor

    def test_no_patch_reads_zero(self):
        for read in (V.yellow_fraction, V.pink_fraction, V.red_hue_fraction):
            with self.subTest(read.__name__):
                self.assertEqual(read(None), 0)
                self.assertEqual(read(np.zeros((0, 4, 3), np.uint8)), 0)
                self.assertEqual(read(np.zeros((4, 4), np.uint8)), 0)  # not a colour image


if __name__ == '__main__':
    unittest.main()
