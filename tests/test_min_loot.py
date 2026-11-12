"""Minimum loot before a Home Village attack: the fields on the Run page (Home Village only,
the same profile values as Settings), and the Next button the loot filter presses."""
import os
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.config import Config
from app.core.loot_filter import LootFilter
from app.services.vision import VisionService
from app.utils.common import get_template_path
from app.utils.profile_settings_store import ProfileSettings
from tests.helpers import QtTestCase, bare_bot

try:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.qt.pages.run import RunPage
except ImportError:  # the CI test job installs no Qt
    QApplication = None


def make_bot():
    bot = bare_bot(np.zeros((767, 1227, 3), np.uint8))
    bot.vision = VisionService
    bot._update_config_size = Mock()
    return bot


class DarkMinimumTests(unittest.TestCase):
    def test_a_base_short_of_dark_elixir_is_skipped(self):
        from app.core.loot_filter import meets
        lf = LootFilter(min_gold=500000, min_elixir=500000, min_dark=5000)
        self.assertTrue(lf.enabled)
        self.assertTrue(meets((800000, 700000, 6000), lf))
        self.assertFalse(meets((800000, 700000, 3000), lf))
        self.assertTrue(meets((800000, 700000, 3000), LootFilter(min_gold=500000, min_elixir=500000)))  # off by default
        self.assertTrue(LootFilter(min_dark=2000).enabled)
        self.assertIn('dark >= 5,000', lf.summary())

    def test_the_profile_keeps_the_dark_minimum(self):
        import tempfile
        from pathlib import Path
        from app.utils import profile_settings_store as store
        with tempfile.TemporaryDirectory() as d, patch.object(store, 'get_settings_path', return_value=Path(d) / 'settings.json'):
            store.save_profile_settings(replace(store.load_profile_settings(), attack_min_dark_k=12))
            self.assertEqual(store.load_profile_settings().attack_min_dark_k, 12)


class NextButtonTests(unittest.TestCase):
    def test_the_16_10_next_button_at_its_scale_or_another(self):
        frame = np.zeros((767, 1227, 3), np.uint8)
        Config().set_target_size_from_frame(frame)
        template = cv2.imread(str(get_template_path('nextbase.png')))
        self.assertIsNotNone(template)  # a 16:10 Next: without it the filter attacked every base
        for scale in (1.0, 0.9, 1.1):
            art = VisionService._resize_template_for_screen(template, frame, scale)
            frame[:] = 0
            frame[600:600 + art.shape[0], 1000:1000 + art.shape[1]] = art
            (x, y) = make_bot()._next_base_point(frame)
            self.assertTrue(abs(x - (1000 + art.shape[1] // 2)) <= 3 and abs(y - (600 + art.shape[0] // 2)) <= 3, scale)
        self.assertIsNone(make_bot()._next_base_point(np.zeros((767, 1227, 3), np.uint8)))

    def test_a_poor_base_is_skipped_with_next_then_a_rich_one_attacked(self):
        bot = make_bot()
        bot._loot_filter = LootFilter(min_gold=500000, min_elixir=500000, max_skips=5)
        bot._status_callback = None
        bot._state_callback = None
        reads = [(120000, 90000, 0), (120000, 90000, 0), (800000, 700000, 4000)]  # poor, poor again (confirmed), rich
        with patch.object(bot, '_read_base_loot', side_effect=reads), \
                patch.object(bot, '_next_base_point', return_value=(1100, 650)), \
                patch.object(bot, '_wait_for_next_base', return_value=True):
            bot._skip_low_loot_bases()
        self.assertEqual([c.args[:2] for c in bot.input.click.call_args_list], [(1100, 650)])
        self.assertEqual(bot._bases_skipped, 1)


@unittest.skipIf(QApplication is None, 'needs PySide6')
class RunPageMinLootTests(QtTestCase):
    def setUp(self):
        super().setUp()
        self.profile = ProfileSettings(attack_min_gold_k=400, attack_min_elixir_k=0, attack_max_skips=7)
        load = patch('app.ui.qt.pages.run.load_profile_settings', side_effect=lambda: self.profile)
        save = patch('app.ui.qt.pages.run.save_profile_settings', side_effect=self.saved)
        load.start()
        self.save = save.start()
        self.addCleanup(load.stop)
        self.addCleanup(save.stop)
        with patch('app.ui.qt.pages.run.QSettings', return_value=self.temp_settings()):  # not the user's UI store
            self.page = RunPage(Mock(), lambda page: None)

    def saved(self, profile):
        self.profile = profile

    def test_the_fields_show_and_save_the_profile_minimums(self):
        self.assertEqual((self.page._min_gold.value(), self.page._min_elixir.value(), self.page._min_dark.value()), (400, 0, 0))
        self.assertEqual(self.page._min_elixir.text(), 'any')
        self.page._min_elixir.setValue(300)
        self.page._min_dark.setValue(5)
        self.assertEqual((self.profile.attack_min_gold_k, self.profile.attack_min_elixir_k, self.profile.attack_min_dark_k), (400, 300, 5))
        self.assertEqual(self.profile.attack_max_skips, 7)  # the rest of the profile kept

    def test_settings_edits_show_up_on_the_run_page(self):
        self.profile = replace(self.profile, attack_min_gold_k=1000)
        self.page._load_min_loot()
        self.assertEqual(self.page._min_gold.value(), 1000)

    def test_home_village_only(self):
        self.page._village_group.button(1).click()  # Builder Base
        self.assertTrue(self.page._attack_card.isHidden())
        self.page._village_group.button(0).click()
        self.assertFalse(self.page._attack_card.isHidden())


if __name__ == '__main__':
    unittest.main()
