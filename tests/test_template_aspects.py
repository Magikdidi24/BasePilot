"""Both aspects carry the same templates: one added for 16:10 only (or 16:9 only) breaks
that window shape silently. The known exceptions are listed here, each with its reason."""
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.config import Config
from app.services.vision import VisionService

TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'
FIXTURES = Path(__file__).parent / 'fixtures'

# breturnhome1920.png: a 1920x1080 redraw of Builder Base's Return Home. reload.png: the old
# reconnect dialog's button; the dialogs are found by their titles (OCR) at both aspects.
ONLY_16_9 = {'breturnhome1920.png', 'reload.png'}
ONLY_16_10 = {'test.png'}  # unused


class TemplateAspectTests(unittest.TestCase):
    def test_both_aspects_have_the_same_templates(self):
        wide = {p.name for p in (TEMPLATES / '16_9').glob('*.png')}
        tall = {p.name for p in (TEMPLATES / '16_10').glob('*.png')}
        self.assertEqual(wide - tall, ONLY_16_9, 'a template of 16:9 only: add its 16:10 version (or list it here)')
        self.assertEqual(tall - wide, ONLY_16_10, 'a template of 16:10 only: add its 16:9 version (or list it here)')

    def test_both_aspects_have_their_data(self):
        for aspect in ('16_9', '16_10'):
            self.assertTrue((TEMPLATES / aspect / 'data.json').is_file(), aspect)


@patch('app.utils.common.user_template_dirs', return_value=[])  # the bundled art, not a drop-in
class ClanTemplatesAt1610Tests(unittest.TestCase):
    """The 16:10 clan templates are the 16:9 art x 1600/1440 (the UI scales with the window
    height), checked on a live 1227x767 client: an account in no clan, its button showing
    the default shield (live: 0.83 on the button, 0.93 on the close tab)."""

    def frame(self, name, x, y):
        frame = np.zeros((767, 1227, 3), np.uint8)
        crop = cv2.imread(str(FIXTURES / name))
        frame[y:y + crop.shape[0], x:x + crop.shape[1]] = crop
        Config().set_target_size_from_frame(frame)
        return frame

    def test_the_menu_button_and_its_close_tab(self, _dirs):
        vision = VisionService()
        home = self.frame('gpg767_clan_button.png', 0, 300)
        (x, y) = vision.find_template(home, 'clanmenu.png', threshold=0.8)
        self.assertTrue(x and 17 <= x <= 105 and 340 <= y <= 427, (x, y))  # on the button
        self.assertEqual(vision.find_template(home, 'clanexit.png', threshold=0.8), (None, None))  # the menu is closed
        menu = self.frame('gpg767_clan_menu_tabs.png', 400, 180)
        (x, y) = vision.find_template(menu, 'clanexit.png', threshold=0.8)
        self.assertTrue(x and abs(x - 465) <= 6 and abs(y - 353) <= 6, (x, y))


if __name__ == '__main__':
    unittest.main()
