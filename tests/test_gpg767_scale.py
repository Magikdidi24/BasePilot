"""GPG's default 1227x767 window: art drawn at another size than the bot's height-proportional
template scale (the Build panel's X, a selected wall's Upgrade tiles)."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from app.config import Config
from app.core import build_panel as bp
from app.core.bot import Bot
from app.core.upgrade_menu import RESOURCE_ELIXIR
from app.services.vision import VisionService
from tests.helpers import canvas


class PanelCloseTests(unittest.TestCase):
    def test_the_open_panel_is_closed_by_its_x(self):
        # exit.png matches the panel's X at 0.9 and 0.8 of the bot's scale, not at it (0.58);
        # the 'empty' point (647, 753) lands on the box button while the panel is open. The
        # panel never goes away here: every tap, the dialog pass's and the close loop's, is its X
        panel = canvas(('gpg767_panel_hv_buildings.png', 824, 0))
        tap = Mock()
        bp.BuildPanelUpgrader(Mock(screenshot=Mock(return_value=panel)), Mock(click=tap), VisionService, Config(), Mock())._close_panel()
        taps = [c.args[:2] for c in tap.call_args_list]
        self.assertTrue(taps)
        self.assertTrue(all(abs(x - 1201) <= 5 and abs(y - 27) <= 5 for (x, y) in taps), taps)

    def test_a_wall_pass_without_a_wall_card_closes_the_panel_by_its_x(self):
        # no Wall card read: the pass leaves the panel open, and its cleanup tap must not be
        # the 'empty' point (the box button while the panel is open)
        bot = Bot.__new__(Bot)
        bot.window = Mock(screenshot=Mock(return_value=canvas(('gpg767_panel_hv_buildings.png', 824, 0))))
        (bot.input, bot.vision, bot.config) = (Mock(), VisionService, Config())
        bot._deselect_wall_ui()
        self.assertEqual(bot.input.click.call_count, 1)
        (x, y) = bot.input.click.call_args.args[:2]
        self.assertTrue(abs(x - 1201) <= 5 and abs(y - 27) <= 5, (x, y))

    def test_nothing_else_in_the_panel_reads_as_an_x(self):
        frame = canvas(('gpg767_panel_hv_buildings.png', 824, 0))
        frame[:60, 1165:] = 0  # the panel's X
        self.assertIsNone(bp.find_close(VisionService, frame))

    def test_a_dialog_x_at_the_bot_scale_wins_over_the_panel_x(self):
        # hv_dialog_lab: the dialog's X matches exit.png at the bot's scale (0.84), the panel's
        # X behind it at 0.8 (0.99); other scales are only tried when every template misses
        hits = {(1, 'exit.png'): (1137, 59, 0.84), (0.8, 'exit.png'): (1202, 27, 0.99)}
        scales = []

        def match(frame, name, threshold=0, region=None, scale=1):
            scales.append(scale)
            hit = hits.get((scale, name))
            return hit if hit and hit[2] >= threshold else (None, None, 0.5)
        vision = Mock(wraps=VisionService, find_template_with_confidence=Mock(side_effect=match))
        self.assertEqual(bp.find_close(vision, np.zeros((767, 1227, 3), np.uint8)), (1137, 59))
        self.assertEqual(set(scales), {1})


class WallTileTests(unittest.TestCase):
    def test_the_selected_wall_is_upgraded_with_elixir(self):
        # "Wall (Level 14)": wallhammer.png matches its Upgrade tiles at 1.1 (0.72 at the bot's
        # scale). The name check's OCR is stubbed: at this size it reads "Wall" only just.
        frame = canvas(('gpg767_wall_grid_hv.png', 380, 525))
        with patch.object(VisionService, 'find_words_ocr', return_value=[SimpleNamespace(text='Wall')]):
            tile = bp.wall_upgrade_button(VisionService, frame)
        self.assertIsNotNone(tile)
        ((x, y), resource) = tile
        self.assertEqual(resource, RESOURCE_ELIXIR)
        self.assertTrue(abs(x - 772) <= 8 and abs(y - 609) <= 8, (x, y))

    def test_no_wall_tile_on_the_panel(self):
        self.assertIsNone(bp.wall_upgrade_button(VisionService, canvas(('gpg767_panel_hv_buildings.png', 824, 0))))


if __name__ == '__main__':
    unittest.main()
