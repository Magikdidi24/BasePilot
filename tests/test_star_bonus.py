"""The Star Bonus dialog on a live 1227x767 client (Builder Base): its Okay, drawn at 0.9
(0.75 at the bot's scale), is tapped once its title is read; the crop leaves the names
out (x 270-980, y 120-700)."""
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.core.bot import Bot
from app.services import ppocr
from app.services.vision import VisionService
from tests.helpers import canvas

FIXTURES = Path(__file__).parent / 'fixtures'
HAVE_OCR = ppocr.available()


def make_bot():
    bot = Bot.__new__(Bot)
    bot.input = Mock()
    bot.vision = VisionService()
    return bot


def dialog():
    return canvas(('gpg767_bb_star_bonus_dialog.png', 270, 120))


@unittest.skipUnless(HAVE_OCR, 'needs the OCR models in app/data/ocr')
class StarBonusTests(unittest.TestCase):
    def test_its_okay_is_tapped(self):
        bot = make_bot()
        self.assertTrue(bot._dismiss_star_bonus(dialog()))
        (x, y) = bot.input.click.call_args.args[:2]
        self.assertTrue(abs(x - 615) < 15 and abs(y - 588) < 15, (x, y))

    def test_an_okay_without_the_title_is_left_alone(self):
        frame = dialog()
        frame[120:320] = 0  # no "Star Bonus" title: some other dialog's Okay
        bot = make_bot()
        self.assertFalse(bot._dismiss_star_bonus(frame))
        bot.input.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
