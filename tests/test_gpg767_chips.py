"""The chips above Build in GPG's default 1227x767 window (16:10 on a 1920x1200 screen)."""
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.config import Config
from app.core import build_panel as bp
from app.core import upgrade_menu
from app.services.vision import VisionService

FIXTURES = Path(__file__).parent / 'fixtures'
# the text boxes read_chips anchors on the Build button at this size
BUILDERS = (1096, 603, 54, 28)
LAB = (1156, 607, 48, 23)


def canvas(*parts):
    """Live 1227x767 crops (no player name in them) pasted back where they were taken."""
    frame = np.zeros((767, 1227, 3), np.uint8)
    for (name, y, x) in parts:
        img = cv2.imread(str(FIXTURES / f'{name}.png'))
        frame[y:y + img.shape[0], x:x + img.shape[1]] = img
    Config().set_target_size_from_frame(frame)
    return frame


class ChipTests(unittest.TestCase):
    def test_lab_one_of_two(self):
        # Tesseract reads this small 1 as a V (dropped by the digit whitelist) or merges it
        # into the slash: every pass used to read the lab chip as "2" alone
        (builders, lab) = bp.read_chips(VisionService, Config(), canvas(('gpg767_chips_hv', 560, 1000)))
        self.assertEqual((builders.free, builders.total, builders.goblin), (0, 6, False))
        self.assertIsNotNone(lab)
        self.assertEqual((lab.free, lab.total, lab.goblin, lab.regular_free), (1, 2, True, 0))

    def test_only_a_whole_narrow_glyph_is_a_one(self):
        frame = canvas(('gpg767_chips_hv', 560, 1000))
        narrow = lambda box: [w < upgrade_menu._ONE_MAX_ASPECT * h for (_x, _y, w, h) in upgrade_menu._chip_glyphs(frame, box)]
        self.assertEqual(narrow(LAB), [True, False, False])  # 1 / 2
        self.assertEqual(narrow(BUILDERS), [False, False, False])  # 0 / 6
        # a box that cuts the 0 of 0/6 leaves an arc as narrow as a 1: no glyphs at all then
        self.assertIsNone(upgrade_menu._chip_glyphs(frame, (1112, 603, 38, 28)))

    def test_no_shape_read_on_dimmed_ink(self):
        # While a dialog's dark overlay fades in or out, the glyph whites sit near the 190 white
        # floor and only bits of the strokes stay. In this copy (960x600, half a pixel off, x0.76)
        # the 0 and the 6 of the busy builders' 0/6 came out as narrow as a 1: read "1/1"
        frame = cv2.warpAffine(canvas(('gpg767_chips_hv', 560, 1000)), np.float32([[1, 0, 0.5], [0, 1, 0.5]]), (1227, 767))
        frame = (cv2.resize(frame, (960, 600), interpolation=cv2.INTER_AREA) * 0.76).astype(np.uint8)
        Config().set_target_size_from_frame(frame)
        self.assertIsNone(upgrade_menu._chip_glyphs(frame, (858, 472, 42, 22)))
        (builders, _lab) = bp.read_chips(VisionService, Config(), frame)
        self.assertTrue(builders is None or builders.free == 0, builders)


if __name__ == '__main__':
    unittest.main()
