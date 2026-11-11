"""Multi-run account switch on the October 2026 HUD: Settings sit in the profile (its badge
at the top left, then the profile window's Settings tab); the old HUD's gear still works,
and a step that does not show fails the switch with the windows closed. The home screen is
the bottom half of a live 1227x767 Home Village (no names in it)."""
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.config import Config
from app.core.bot import Bot

FIXTURES = Path(__file__).parent / 'fixtures'


def home():
    frame = np.zeros((767, 1227, 3), np.uint8)
    frame[383:767] = cv2.imread(str(FIXTURES / 'gpg767_home_village_bottom.jpg'))
    Config().set_target_size_from_frame(frame)
    return frame


def make_bot(frame):
    bot = Bot.__new__(Bot)
    bot.stop_event = Mock()
    bot.stop_event.is_set.return_value = False
    bot.stop_event.wait.return_value = False
    bot.window = Mock()
    bot.window.screenshot.return_value = frame
    bot.input = Mock()
    bot.vision = Mock()
    bot.vision.find_label.return_value = (None, None)
    bot.config = Config()
    bot._update_config_size = Mock()
    bot._status_callback = None
    return bot


class SettingsTests(unittest.TestCase):
    def test_the_profile_then_its_settings_tab(self):
        bot = make_bot(home())
        labels = iter([(None, None), (1100, 40)])  # the window slides in
        bot.vision.find_label.side_effect = lambda f, label, **kw: next(labels) if label == 'Settings' else (None, None)
        self.assertTrue(bot._open_game_settings())
        self.assertEqual([c.args[:2] for c in bot.input.click.call_args_list], [(61, 72), (1100, 40)])
        region = bot.vision.find_label.call_args.kwargs['region']
        self.assertTrue(region[0] >= 1227 // 3 and region[1] == 0 and region[3] <= 0.25 * 767)  # the tabs: top, right

    @patch('app.core.bot._dump_debug_frame')
    @patch('app.core.bot.find_close', side_effect=[(1190, 40), None])
    def test_no_settings_tab_closes_the_profile(self, _close, dump):
        bot = make_bot(home())
        self.assertFalse(bot._open_game_settings())
        self.assertEqual(bot.input.click.call_args_list[-1].args[:2], (1190, 40))
        self.assertEqual(dump.call_args.args[1], 'profile')

    def test_the_old_hud_gear(self):
        bot = make_bot(np.zeros((767, 1227, 3), np.uint8))  # no Build button: not the October HUD
        bot._wait_for_image = Mock(return_value=(1190, 380))
        self.assertTrue(bot._open_game_settings())
        self.assertEqual(bot._wait_for_image.call_args.args[0], 'settings.png')
        self.assertEqual(bot.input.click.call_args.args[:2], (1190, 380))


class SwitchTests(unittest.TestCase):
    @patch('app.core.bot._dump_debug_frame')
    def test_no_switch_button_fails_the_switch_with_the_windows_closed(self, dump):
        bot = make_bot(home())
        bot._open_game_settings = Mock(return_value=True)
        bot._wait_for_image = Mock(return_value=(None, None))
        bot._close_windows = Mock()
        with self.assertRaises(RuntimeError) as err:
            bot._switch_account_and_load_home('second')
        self.assertIn('changeuser.png', str(err.exception))
        bot._close_windows.assert_called_once()
        self.assertEqual(dump.call_args.args[1], 'settings')

    def test_the_switch_taps_the_name_and_waits_for_home(self):
        bot = make_bot(home())
        bot._open_game_settings = Mock(return_value=True)
        bot._wait_for_image = Mock(return_value=(640, 300))  # the Supercell ID switch
        bot._wait_for_player_name = Mock(return_value=(600, 420))
        bot._wake_home_and_wait_for_attack = Mock(return_value=(75, 734))
        bot._switch_account_and_load_home('second')
        self.assertEqual([c.args[:2] for c in bot.input.click.call_args_list], [(640, 300), (600, 420)])
        self.assertIsNone(bot._loot_prev_resources)  # the next account's loot starts afresh


if __name__ == '__main__':
    unittest.main()
