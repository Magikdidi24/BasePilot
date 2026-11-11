"""Both aspects carry the same templates: one added for 16:10 only (or 16:9 only) breaks
that window shape silently. The known exceptions are listed here, each with its reason."""
import unittest
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'

# Captured on 16:9 windows only; on 16:10 they are captured in the app (Settings -> Clan
# assist -> Capture templates), or their screens are handled without them.
ONLY_16_9 = {
    'breturnhome1920.png', 'claim_btn.png', 'clanexit.png', 'clanmenu.png', 'clannotify.png', 'dailyreward_x.png',
    'donate.png', 'needgold_x.png', 'reload.png', 'requesttroops.png', 'send.png',
} | {'donatetroop.png'} | {f'donatetroop{i}.png' for i in range(2, 14)}
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


if __name__ == '__main__':
    unittest.main()
