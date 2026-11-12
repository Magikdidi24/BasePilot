"""Clan assist backs out of a panel without pressing an Okay while a gem is on screen: the
bot's rule for every popup, a gem means a purchase is on offer."""
import unittest
from unittest.mock import Mock

import numpy as np

from app.core.clan import ClanAssistant, ClanOptions

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

    def test_no_okay_after_a_price_veto(self):
        clan = assistant({'okay.png': OKAY})  # the gem beside Send was seen, not this one
        clan._escape_subpanel(allow_okay=False)
        self.assertEqual(clan.input.click.call_args.args[:2], EMPTY)


if __name__ == '__main__':
    unittest.main()
