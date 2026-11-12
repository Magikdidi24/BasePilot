"""The three template finders (find_template, find_template_with_confidence and
_find_template_matches) on a synthetic screen: where each finds a template, how a region offsets
the answer, and what each returns when the template is missing, the region overflows the screen,
the template is bigger than what is searched or the match falls under the threshold."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.services import vision
from app.services.vision import VisionService

(T_H, T_W) = (40, 30)
TEMPLATE = np.random.default_rng(7).integers(0, 256, (T_H, T_W, 3), dtype=np.uint8)
SPOTS = ((100, 50), (300, 200))  # (left, top) of each copy on the screen
FIRST_CENTER = (100 + T_W // 2, 50 + T_H // 2)
SECOND_CENTER = (300 + T_W // 2, 200 + T_H // 2)


def screen(spots=SPOTS):
    img = np.zeros((400, 600, 3), np.uint8)
    for (left, top) in spots:
        img[top:top + T_H, left:left + T_W] = TEMPLATE
    return img


def resize_scale(c):
    '''The ``scale`` a _resize_template_for_screen call asked for.'''
    return c.args[2] if len(c.args) > 2 else c.kwargs.get('scale', 1)


class TemplateFinderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        (ok, png) = cv2.imencode('.png', TEMPLATE)
        (self.folder / 'tpl.png').write_bytes(png.tobytes())
        for patcher in (patch.object(vision, 'get_template_path', side_effect=lambda name: self.folder / name),
                        patch.object(VisionService, '_template_scale_xy', return_value=(1.0, 1.0))):  # screen at the authored size
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_template_is_found_where_it_is(self):
        img = screen(SPOTS[:1])
        self.assertEqual(VisionService.find_template(img, 'tpl.png'), FIRST_CENTER)
        (x, y, score) = VisionService.find_template_with_confidence(img, 'tpl.png')
        self.assertEqual((x, y), FIRST_CENTER)
        self.assertIsInstance(score, float)
        self.assertAlmostEqual(score, 1.0, places=4)
        [(left, top, w, h, score)] = VisionService._find_template_matches(img, 'tpl.png', 0.9)
        self.assertEqual((left, top, w, h), (100, 50, T_W, T_H))
        self.assertAlmostEqual(score, 1.0, places=4)

    def test_a_region_offsets_the_answer(self):
        img = screen()
        region = (250, 150, 200, 150)  # holds the second copy only
        self.assertEqual(VisionService.find_template(img, 'tpl.png', region=region), SECOND_CENTER)
        self.assertEqual(VisionService.find_template_with_confidence(img, 'tpl.png', region=region)[:2], SECOND_CENTER)
        self.assertEqual([m[:4] for m in VisionService._find_template_matches(img, 'tpl.png', 0.9, region)], [(300, 200, T_W, T_H)])

    def test_every_copy_is_listed_once(self):
        matches = VisionService._find_template_matches(screen(), 'tpl.png', 0.9, max_matches=5)
        self.assertEqual(sorted(m[:2] for m in matches), list(SPOTS))
        self.assertEqual(sorted(VisionService.find_all_template_centers(screen(), 'tpl.png')), [FIRST_CENTER, SECOND_CENTER])

    def test_under_the_threshold(self):
        img = screen(SPOTS[:1])
        self.assertEqual(VisionService.find_template(img, 'tpl.png', threshold=1.01), (None, None))
        (x, y, score) = VisionService.find_template_with_confidence(img, 'tpl.png', threshold=1.01)
        self.assertEqual((x, y), (None, None))
        self.assertAlmostEqual(score, 1.0, places=4)  # the best score all the same
        self.assertEqual(VisionService._find_template_matches(img, 'tpl.png', 1.01), [])

    def test_the_template_is_sized_for_the_screen_unless_told_not_to(self):
        img = screen(SPOTS[:1])
        with patch.object(VisionService, '_resize_template_for_screen', side_effect=lambda tpl, scr, scale=1: tpl) as resize:
            self.assertEqual(VisionService.find_template(img, 'tpl.png'), FIRST_CENTER)
            self.assertEqual(VisionService.find_template(img, 'tpl.png', scale_template=False), FIRST_CENTER)
            VisionService.find_template_with_confidence(img, 'tpl.png', scale=1.1)
            VisionService._find_template_matches(img, 'tpl.png', 0.9, scale=0.9)
        self.assertEqual([resize_scale(c) for c in resize.call_args_list], [1, 1.1, 0.9])
        self.assertTrue(all(c.args[1] is img for c in resize.call_args_list))

    def test_a_missing_template_is_logged(self):
        img = screen()
        with self.assertLogs('VisionService', 'ERROR') as logs:
            self.assertEqual(VisionService.find_template(img, 'nope.png'), (None, None))
            self.assertEqual(VisionService.find_template_with_confidence(img, 'nope.png'), (None, None, 0))
            self.assertEqual(VisionService._find_template_matches(img, 'nope.png', 0.8), [])
        self.assertEqual(len(logs.output), 3)
        self.assertTrue(all('Template not found: ' in line and line.endswith('nope.png') for line in logs.output), logs.output)

    def test_a_region_past_the_screen_edge_finds_nothing(self):
        img = screen()
        for region in ((500, 0, 200, 100), (0, 300, 100, 101)):  # past the right edge, past the bottom
            with self.subTest(region=region):
                with self.assertLogs('VisionService', 'WARNING') as logs:
                    self.assertEqual(VisionService.find_template(img, 'tpl.png', region=region), (None, None))
                self.assertEqual(logs.output, [f'WARNING:VisionService:Region {region} out of bounds for image size 600x400'])
                with self.assertNoLogs('VisionService', 'WARNING'):  # only find_template warns
                    self.assertEqual(VisionService.find_template_with_confidence(img, 'tpl.png', region=region), (None, None, 0))
                    self.assertEqual(VisionService._find_template_matches(img, 'tpl.png', 0.8, region), [])

    def test_a_region_the_size_of_the_template_still_finds_it(self):
        img = screen(SPOTS[:1])
        region = (100, 50, T_W, T_H)
        self.assertEqual(VisionService.find_template(img, 'tpl.png', region=region), FIRST_CENTER)
        self.assertEqual(VisionService.find_template_with_confidence(img, 'tpl.png', region=region)[:2], FIRST_CENTER)
        self.assertEqual([m[:2] for m in VisionService._find_template_matches(img, 'tpl.png', 0.9, region)], [SPOTS[0]])

    def test_a_template_bigger_than_the_search_finds_nothing_quietly(self):
        img = screen()
        region = (0, 0, T_W - 1, 300)
        with self.assertNoLogs('VisionService', 'WARNING'):
            self.assertEqual(VisionService.find_template(img, 'tpl.png', region=region), (None, None))
            self.assertEqual(VisionService.find_template_with_confidence(img, 'tpl.png', region=region), (None, None, 0))
            self.assertEqual(VisionService._find_template_matches(img, 'tpl.png', 0.8, region), [])

    def test_a_failure_inside_is_logged_with_the_finder_name(self):
        with self.assertLogs('VisionService', 'ERROR') as logs:
            self.assertEqual(VisionService.find_template(None, 'tpl.png'), (None, None))
            self.assertEqual(VisionService.find_template_with_confidence(None, 'tpl.png'), (None, None, 0))
            self.assertEqual(VisionService._find_template_matches(None, 'tpl.png', 0.8), [])
        self.assertEqual([line.split(': ')[0] for line in logs.output],
                         ['ERROR:VisionService:Error in find_template', 'ERROR:VisionService:Error in find_template_with_confidence',
                          'ERROR:VisionService:Error in _find_template_matches (tpl.png)'])


if __name__ == '__main__':
    unittest.main()
