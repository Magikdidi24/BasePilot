"""Clan assist backs out of a panel without pressing an Okay while a gem is on screen: the
bot's rule for every popup, a gem means a purchase is on offer."""
import unittest
from unittest.mock import Mock

import numpy as np

from app.core.clan import ClanAssistant, ClanOptions
from app.utils.profile_settings_store import ProfileSettings

try:
    from app.ui.qt.bot_controller import _clan_options
except ImportError:  # no PySide6 (the Linux CI)
    _clan_options = None

FRAME = np.zeros((1200, 1920, 3), np.uint8)
OKAY = (960, 900)
EMPTY = (100, 600)


def assistant(on_screen):
    """A ClanAssistant whose screen shows the templates of ``on_screen`` (name -> center)."""
    vision = Mock()
    vision.find_template.side_effect = lambda frame, name, **kw: on_screen.get(name, (None, None))
    window = Mock(**{'screenshot.return_value': FRAME})
    config = Mock(**{'get_point.return_value': EMPTY})
    stop = Mock(**{'is_set.return_value': False, 'wait.return_value': False})
    return ClanAssistant(window, Mock(), vision, config, stop, ClanOptions())


class EscapeTests(unittest.TestCase):
    def test_an_okay_is_pressed_when_no_gem_shows(self):
        clan = assistant({'okay.png': OKAY})
        clan._escape_subpanel()
        clan.input.click.assert_called_once()
        self.assertEqual(clan.input.click.call_args.args[:2], OKAY)

    def test_no_okay_while_a_gem_shows(self):
        clan = assistant({'okay.png': OKAY, 'gemicon.png': (900, 700)})
        clan._escape_subpanel()
        clan.input.click.assert_called_once()
        self.assertEqual(clan.input.click.call_args.args[:2], EMPTY)  # backed out on empty ground

    def test_the_x_is_still_used_while_a_gem_shows(self):
        for x_art in ('exit.png', 'closex.png'):  # the clan panels' X and the October dialogs'
            with self.subTest(x_art):
                clan = assistant({'okay.png': OKAY, x_art: (1500, 200), 'gemicon.png': (900, 700)})
                clan._escape_subpanel()
                self.assertEqual(clan.input.click.call_args.args[:2], (1500, 200))

    def test_a_panel_with_only_the_october_x_is_closed_by_it(self):
        clan = assistant({'closex.png': (1500, 200)})
        clan._escape_subpanel()
        self.assertEqual(clan.input.click.call_args.args[:2], (1500, 200))  # not a tap on empty ground

    def test_no_okay_after_a_price_veto(self):
        clan = assistant({'okay.png': OKAY})  # the gem beside Send was seen, not this one
        clan._escape_subpanel(allow_okay=False)
        self.assertEqual(clan.input.click.call_args.args[:2], EMPTY)


class ChatPointTests(unittest.TestCase):
    def test_the_chat_point_is_clicked_only_at_the_aspect_it_was_picked_on(self):
        frame = np.zeros((1200, 1920, 3), np.uint8)  # 16:10
        for (picked_on, expected) in (('16_10', (960, 600)), (None, (960, 600)), ('16_9', None)):
            with self.subTest(picked_on=picked_on):
                clan = assistant({})
                clan.options = ClanOptions(chat_point=(0.5, 0.5), chat_point_aspect=picked_on)
                self.assertEqual(clan._chat_click_point(frame), expected)


@unittest.skipIf(_clan_options is None, 'needs PySide6')
class ClanOptionsTests(unittest.TestCase):
    def test_the_chat_point_keeps_the_aspect_it_was_picked_on(self):
        profile = ProfileSettings(clan_chat_point=[0.5, 0.25], clan_chat_point_aspect='16_9')
        options = _clan_options(profile, donate=True, request=False)
        self.assertEqual((options.chat_point, options.chat_point_aspect), ((0.5, 0.25), '16_9'))


if __name__ == '__main__':
    unittest.main()
