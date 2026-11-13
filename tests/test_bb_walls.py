"""Builder Base walls: the Home Village's wall pass on the Builder Base's Build panel (it
opens on Buildings & Heroes, its title read; no tab art), a tap that a selection ate going
again (Build, Battle), the pass's own threshold, and the Run page's switch (and the per-profile
store the page keeps its choices in). Live 1227x767 crops: the panel alone and the bottom half of
the home screen (no names in them)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from app.config import Config
from app.services import ppocr
from app.core.upgrade_menu import RESOURCE_ELIXIR, RESOURCE_GOLD
from app.services.vision import VisionService
from app.utils import profile_settings_store as store
from tests.helpers import QtTestCase, bare_bot, canvas


HOME = canvas(('gpg767_builder_base_home_bottom.jpg', 0, 383))
PANEL = canvas(('gpg767_panel_bb_buildings.png', 824, 0))


def make_bot(frames=()):
    bot = bare_bot()
    shots = list(frames)
    bot.window.screenshot.side_effect = lambda: shots.pop(0) if len(shots) > 1 else shots[0]
    bot.vision = VisionService()
    bot.config = Config()
    bot._update_config_size = Mock()
    return bot


@unittest.skipUnless(ppocr.available(), 'needs the OCR models in app/data/ocr')
class PanelTests(unittest.TestCase):
    def test_the_builder_base_panel_opens_on_buildings_and_heroes(self):
        bot = make_bot([PANEL])
        self.assertTrue(bot._open_build_panel(HOME))
        self.assertEqual(bot.input.click.call_count, 1)  # Build only: no tab to tap

    def test_a_build_tap_a_selection_ate_goes_again(self):
        bot = make_bot([HOME] * 6 + [PANEL])
        self.assertTrue(bot._open_build_panel(HOME))
        self.assertEqual(bot.input.click.call_count, 2)  # Build, eaten; Build again
        (x1, y1) = bot.input.click.call_args_list[0].args[:2]
        (x2, y2) = bot.input.click.call_args_list[1].args[:2]
        self.assertTrue(abs(x1 - x2) < 30 and abs(y1 - y2) < 30)

    def test_no_panel_after_two_taps_skips_the_pass(self):
        bot = make_bot([HOME])
        self.assertFalse(bot._open_build_panel(HOME))
        self.assertEqual(bot.input.click.call_count, 2)


def gate_bot(**kw):
    bot = make_bot([HOME])
    bot._walls_enabled = True
    bot._bb_wall_threshold = 1000000
    bot._wall_upgrade_threshold = 3000000  # the Home Village's: not this pass's
    bot._status_callback = None
    for (k, v) in kw.items():
        setattr(bot, k, v)
    return bot


class GateTests(unittest.TestCase):
    @patch('app.core.bot.storages_full', return_value=(False, False))
    def test_the_builder_base_threshold_decides(self, _full):
        bot = gate_bot()
        bot._read_hud_triplet_stable = Mock(return_value=(400000, 1400000, 278))  # Builder Base: gold, elixir, gems
        self.assertEqual(bot._should_upgrade_walls(bot._bb_wall_threshold), {RESOURCE_ELIXIR})
        self.assertEqual(bot._should_upgrade_walls(), set())  # 3M: the Home Village's

    @patch('app.core.bot.find_close', return_value=None)
    def test_walls_until_the_loot_is_under_the_threshold(self, _close):
        bot = gate_bot(_should_upgrade_walls=Mock(side_effect=[{RESOURCE_ELIXIR}, {RESOURCE_ELIXIR}, set()]),
                       _upgrade_walls=Mock(return_value=True))
        bot._bb_maybe_upgrade_walls()
        self.assertEqual(bot._upgrade_walls.call_count, 2)
        bot._should_upgrade_walls.assert_called_with(1000000)
        self.assertEqual(getattr(bot, '_wall_retry_at', 0), 0)

    @patch('app.core.bot.find_close', return_value=None)
    def test_a_pass_that_buys_nothing_backs_off(self, _close):
        bot = gate_bot(_should_upgrade_walls=Mock(return_value={RESOURCE_GOLD}), _upgrade_walls=Mock(return_value=None))
        bot._bb_maybe_upgrade_walls()
        bot._bb_maybe_upgrade_walls()
        self.assertEqual(bot._upgrade_walls.call_count, 1)
        self.assertEqual(bot._should_upgrade_walls.call_count, 1)  # backed off: not even re-checked

    def test_off_unless_switched_on(self):
        bot = gate_bot(_walls_enabled=False, _should_upgrade_walls=Mock())
        bot._bb_maybe_upgrade_walls()
        bot._should_upgrade_walls.assert_not_called()

    @patch('app.core.bot.find_close', return_value=(1203, 27))
    def test_the_panel_left_open_is_closed(self, _close):
        bot = gate_bot(_should_upgrade_walls=Mock(return_value={RESOURCE_GOLD}), _upgrade_walls=Mock(return_value=None))
        bot._bb_maybe_upgrade_walls()
        self.assertEqual(bot.input.click.call_args.args[:2], (1203, 27))


class BattleTapTests(unittest.TestCase):
    def test_a_battle_tap_a_selection_ate_goes_again(self):
        bot = make_bot([HOME])
        bot._scroll_point = Mock(return_value=(600, 400))
        waits = {'attack.png': [(75, 734)], 'findnow.png': [(None, None), (900, 600)]}
        bot._wait_for_image = Mock(side_effect=lambda name, **kw: waits[name].pop(0) if name in waits else (None, None))
        bot._find_template_once = Mock(return_value=(75, 734))  # still home
        self.assertFalse(bot._bb_attack_once())  # no troop cards here: the test stops at them
        self.assertEqual([c.args[:2] for c in bot.input.click.call_args_list], [(75, 734), (75, 734), (900, 600)])


class SettingsTests(unittest.TestCase):
    def test_the_builder_base_threshold_is_kept(self):
        with tempfile.TemporaryDirectory() as d, patch.object(store, 'get_settings_path', return_value=Path(d) / 'settings.json'):
            store.save_profile_settings(store.ProfileSettings(bb_wall_threshold_k=1500))
            self.assertEqual(store.load_profile_settings().bb_wall_threshold_k, 1500)
            (Path(d) / 'settings.json').write_text(json.dumps({'bb_wall_threshold_k': 10 ** 9}), encoding='utf-8')
            self.assertEqual(store.load_profile_settings().bb_wall_threshold_k, store.BB_WALL_THRESHOLD_K_MAX)
            self.assertEqual(store.ProfileSettings().bb_wall_threshold_k, 0)  # full storages only, by default


try:
    from PySide6.QtWidgets import QApplication
    from app.ui.qt.pages.run import RunPage
except ImportError:  # no PySide6
    QApplication = None


@unittest.skipIf(QApplication is None, 'needs PySide6')
class RunPageTests(QtTestCase):
    def test_the_builder_base_switch_upgrades_walls(self):
        settings = self.temp_settings()
        controller = Mock()
        controller.is_running.return_value = False
        with patch('app.ui.qt.pages.run.QSettings', return_value=settings):
            page = RunPage(controller, lambda name: None)
        page._village_group.button(1).click()  # Builder Base
        self.assertTrue(page._bb_upgrade_walls.isEnabled())
        page._bb_upgrade_walls.setChecked(True)
        with patch('app.ui.qt.pages.run.check_game_window_aspect_for_start', return_value=True):
            page.start_bot()
        kwargs = controller.start.call_args.kwargs
        self.assertEqual((kwargs['builder_base'], kwargs['upgrade_walls']), (True, True))
        self.assertTrue(settings.value('run/bbUpgradeWalls', type=bool))

    def test_the_run_page_keeps_its_choices_per_profile(self):
        settings = self.temp_settings()
        controller = Mock(**{'is_running.return_value': False})
        for (profile, ui_store) in (('', 'UI'), ('alt', 'UI-alt')):  # the main window's store names
            with (self.subTest(profile=profile), patch.dict(os.environ, {'BASEPILOT_PROFILE': profile}),
                  patch('app.ui.qt.pages.run.QSettings', return_value=settings) as opened):
                RunPage(controller, lambda name: None)
                self.assertEqual(opened.call_args_list[0], call('BasePilot', ui_store))  # its own store (a new one then copies the main one's)


if __name__ == '__main__':
    unittest.main()
