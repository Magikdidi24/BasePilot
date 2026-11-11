"""Which village is on screen at Start, so the bot takes the boat when the other one was
picked: the bottom half of both live home screens at 1227x767 (no names in it)."""
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.config import Config
from app.core.bot import Bot
from app.services.vision import VisionService

FIXTURES = Path(__file__).parent / 'fixtures'


def home(name):
    frame = np.zeros((767, 1227, 3), np.uint8)
    frame[383:767] = cv2.imread(str(FIXTURES / name))
    Config().set_target_size_from_frame(frame)
    return frame


def make_bot():
    bot = Bot.__new__(Bot)
    bot.vision = VisionService
    bot._update_config_size = Mock()
    bot.stop_event = Mock()
    bot.stop_event.wait.return_value = False
    bot.stop_event.is_set.return_value = False
    bot.input = Mock()
    bot.config = Mock()
    bot.config.get_point.return_value = [600, 700]
    return bot


class VillageTests(unittest.TestCase):
    def test_the_home_village_while_its_chip_shows_the_goblin(self):
        # all regular builders busy: the chip shows the goblin, builder.png reads 0.59; the
        # Battle and Build buttons with no master builder still tell the Home Village
        self.assertEqual(make_bot()._detect_village_type(home('gpg767_home_village_bottom.jpg')), 'home')

    def test_the_builder_base(self):
        self.assertEqual(make_bot()._detect_village_type(home('gpg767_builder_base_home_bottom.jpg')), 'builder')

    def test_no_village_on_a_battle_screen(self):
        frame = np.zeros((767, 1227, 3), np.uint8)
        bar = cv2.imread(str(FIXTURES / "gpg767_bb_bar.png"))
        frame[640:640 + bar.shape[0], 100:100 + bar.shape[1]] = bar
        Config().set_target_size_from_frame(frame)
        self.assertIsNone(make_bot()._detect_village_type(frame))

    def test_builder_base_picked_on_the_home_village_takes_the_boat(self):
        bot = make_bot()
        bot.window = Mock()
        bot.window.screenshot.return_value = home('gpg767_home_village_bottom.jpg')
        with patch.object(bot, '_go_to_builder_base_with_boat') as boat, patch.object(bot, '_zoom_out_max'):
            bot._ensure_correct_village(builder_base=True)
        boat.assert_called_once()

    def test_home_village_picked_on_the_builder_base_leaves_by_its_boat(self):
        bot = make_bot()
        bot.window = Mock()
        bot.window.screenshot.return_value = home('gpg767_builder_base_home_bottom.jpg')
        with patch.object(bot, '_leave_builder_base_with_nboat') as nboat, patch.object(bot, '_zoom_out_max'):
            bot._ensure_correct_village(builder_base=False)
        nboat.assert_called_once()

    def test_an_unreadable_screen_is_looked_at_again(self):
        bot = make_bot()
        bot.window = Mock()
        bot.window.screenshot.side_effect = [np.zeros((767, 1227, 3), np.uint8), home('gpg767_home_village_bottom.jpg')]
        with patch.object(bot, '_go_to_builder_base_with_boat') as boat, patch.object(bot, '_zoom_out_max'):
            bot._ensure_correct_village(builder_base=True)
        boat.assert_called_once()


if __name__ == '__main__':
    unittest.main()
