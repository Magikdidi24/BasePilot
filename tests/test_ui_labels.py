import shutil
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.core.bot import Bot
from app.services.vision import CONTROL_LABELS, VisionService

FRAME = np.zeros((731, 1299, 3), dtype=np.uint8)


def word(text, left, top=600, width=None, height=20):
    return SimpleNamespace(text=text, left=left, top=top, width=width or 12 * len(text), height=height)


class LabelTests(unittest.TestCase):
    def test_adjacent_words_form_one_label_and_far_buttons_do_not(self):
        segs = VisionService._label_segments([word('Home', 100), word('Return', 20), word('Battle', 400)])
        self.assertEqual([[w.text for w in s] for s in segs], [['Return', 'Home'], ['Battle']])

    @patch.object(VisionService, 'find_words_ocr')
    def test_battle_does_not_match_ranked_battle(self, ocr):
        ocr.return_value = [word('Ranked', 20), word('Battle', 100)]
        self.assertEqual(VisionService.find_label(FRAME, 'Battle'), (None, None))
        ocr.return_value = [word('Ranked', 20), word('Battle', 100), word('Battle', 400)]
        self.assertEqual(VisionService.find_label(FRAME, 'Battle'), (436, 610))

    @patch.object(VisionService, 'find_words_ocr')
    def test_ocr_typo_still_matches_and_later_passes_are_tried(self, ocr):
        ocr.side_effect = [[], [], [word('Retum', 20), word('Home', 92)]]
        self.assertEqual(VisionService.find_label(FRAME, 'Return Home'), (80, 610))
        self.assertEqual([(c.kwargs['preprocess'], c.kwargs['white_text']) for c in ocr.call_args_list],
                         [(False, False), (True, True), (True, False)])

    @patch.object(VisionService, 'find_words_ocr')
    def test_two_line_label_and_stray_glyphs(self, ocr):
        ocr.return_value = [word('Return', 20, top=600), word('Home', 32, top=624)]
        self.assertEqual(VisionService.find_label(FRAME, 'Return Home'), (56, 622))
        ocr.return_value = [word("Vattack'l", 20)]
        self.assertIsNotNone(VisionService.find_label(FRAME, 'Attack')[0])
        ocr.return_value = [word('Attack', 20), word('Log', 100)]
        self.assertIsNone(VisionService.find_label(FRAME, 'Attack')[0])

    @patch.object(VisionService, 'find_words_ocr', return_value=None)
    def test_missing_tesseract_is_a_miss(self, _ocr):
        self.assertEqual(VisionService.find_label(FRAME, 'Battle'), (None, None))

    @patch.object(VisionService, 'find_label', return_value=(5, 6))
    @patch.object(VisionService, 'find_template')
    def test_control_prefers_art_and_reads_label_only_when_allowed(self, tpl, label):
        tpl.return_value = (1, 2)
        self.assertEqual(VisionService.find_control(FRAME, 'attack.png'), (1, 2))
        label.assert_not_called()
        tpl.return_value = (None, None)
        self.assertEqual(VisionService.find_control(FRAME, 'attack.png', ocr=False), (None, None))
        label.assert_not_called()
        self.assertEqual(VisionService.find_control(FRAME, 'attack.png'), (5, 6))
        label.assert_called_once_with(FRAME, 'Battle', region=None)
        self.assertEqual(VisionService.find_control(FRAME, 'okay.png'), (None, None))
        label.assert_called_once()

    def test_no_spending_control_has_a_text_fallback(self):
        for name in ('okay.png', 'use.png', 'upgrademore.png', 'addwall.png', 'rankedattackconfirm.png'):
            self.assertNotIn(name, CONTROL_LABELS)


class BotFlowTests(unittest.TestCase):
    def setUp(self):
        self.bot = Bot.__new__(Bot)
        self.bot.stop_event = Mock()
        self.bot.stop_event.is_set.return_value = False
        self.bot.stop_event.wait.return_value = False
        self.bot.window = Mock()
        self.bot.window.screenshot.return_value = FRAME
        self.bot.input = Mock()
        self.bot.vision = Mock()
        self.bot.config = SimpleNamespace(aspect_key='16_9')
        self.bot._update_config_size = Mock()
        self.bot._battle_rewards = Mock()
        self.bot._battle_rewards.handle.return_value = False

    def test_return_home_clicks_okay_then_return_home_in_one_wait(self):
        okay = iter([(10, 20)])

        def template(frame, name, **kw):
            if name == 'okay.png':
                return next(okay, (None, None))
            return (300, 650) if name == 'returnhome.png' else (None, None)

        self.bot.vision.find_template.side_effect = template
        self.bot._return_home()
        self.assertEqual([c.args[:2] for c in self.bot.input.click.call_args_list], [(10, 20), (300, 650)])
        self.bot.vision.find_label.assert_not_called()

    @patch('app.core.bot._LABEL_FALLBACK_AFTER', 0)
    def test_redrawn_return_home_is_found_by_its_label(self):
        self.bot.vision.find_template.return_value = (None, None)
        self.bot.vision.find_label.side_effect = lambda f, label, **kw: (640, 690) if label == 'Return Home' else (None, None)
        self.assertEqual(self.bot._wait_for_return_home_or_chest_claim(timeout=5), ('return', 640, 690))

    def test_home_hud_without_builder_chip(self):
        hits = {'attack.png': (100, 650), 'build.png': (1200, 650)}
        self.bot.vision.find_template.side_effect = lambda f, name, **kw: hits.get(name, (None, None))
        self.assertTrue(self.bot._home_hud_visible(FRAME))
        hits['mbuilder.png'] = (600, 40)
        self.assertFalse(self.bot._home_hud_visible(FRAME))
        del hits['mbuilder.png'], hits['build.png']
        self.assertFalse(self.bot._home_hud_visible(FRAME))
        hits['builder.png'] = (500, 40)
        self.assertTrue(self.bot._home_hud_visible(FRAME))


@unittest.skipUnless(shutil.which('tesseract'), 'needs the tesseract binary')
class RealArtLabelTests(unittest.TestCase):
    """The label fallback on the game's real button art, pasted at a 1299x731 capture scale."""

    def frame_with(self, art):
        tpl = cv2.imread(f'templates/{art}')
        s = 1299 / 2560
        tpl = cv2.resize(tpl, (round(tpl.shape[1] * s), round(tpl.shape[0] * s)), interpolation=cv2.INTER_AREA)
        frame = np.full((731, 1299, 3), (60, 90, 40), np.uint8)
        frame[560:560 + tpl.shape[0], 433:433 + tpl.shape[1]] = tpl
        return frame

    def test_labels_on_their_own_buttons_only(self):
        cases = [('16_9/attack.png', 'Battle'), ('16_9/attack2.png', 'Attack'), ('16_9/returnhome.png', 'Return Home'),
                 ('16_10/returnhome2.png', 'Return Home'), ('16_9/chestclaim.png', 'Claim Reward'),
                 ('16_9/surrender.png', 'Surrender'), ('16_9/endbattle.png', 'End Battle')]
        for art, label in cases:
            frame = self.frame_with(art)
            with self.subTest(art=art):
                self.assertIsNotNone(VisionService.find_label(frame, label, region=VisionService.bottom_half_region(frame))[0])
        for art, label in (('16_9/attack2.png', 'Battle'), ('16_9/rankedbattle.png', 'Battle'), ('16_9/attack.png', 'Attack')):
            frame = self.frame_with(art)
            with self.subTest(art=art, label=label):
                self.assertIsNone(VisionService.find_label(frame, label, region=VisionService.bottom_half_region(frame))[0])


if __name__ == '__main__':
    unittest.main()
