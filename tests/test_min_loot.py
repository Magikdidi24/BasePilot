"""Minimum loot before a Home Village attack: the fields on the Run page (Home Village only,
the same profile values as Settings), and the Next button the loot filter presses."""
import os
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.config import Config
from app.core.bot import Bot
from app.core.loot_filter import LootFilter
from app.services.vision import VisionService
from app.utils.common import get_template_path
from app.utils.profile_settings_store import ProfileSettings

try:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.qt.pages.run import RunPage
except ImportError:  # the CI test job installs no Qt
    QApplication = None


def make_bot():
    bot = Bot.__new__(Bot)
    bot.stop_event = Mock()
    bot.stop_event.is_set.return_value = False
    bot.stop_event.wait.return_value = False
    bot.window = Mock()
    bot.window.screenshot.return_value = np.zeros((767, 1227, 3), np.uint8)
    bot.input = Mock()
    bot.vision = VisionService
    bot._update_config_size = Mock()
    return bot


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
class RunPageMinLootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.profile = ProfileSettings(attack_min_gold_k=400, attack_min_elixir_k=0, attack_max_skips=7)
        load = patch('app.ui.qt.pages.run.load_profile_settings', side_effect=lambda: self.profile)
        save = patch('app.ui.qt.pages.run.save_profile_settings', side_effect=self.saved)
        load.start()
        self.save = save.start()
        self.addCleanup(load.stop)
        self.addCleanup(save.stop)
        self.page = RunPage(Mock(), lambda page: None)

    def saved(self, profile):
        self.profile = profile

    def test_the_fields_show_and_save_the_profile_minimums(self):
        self.assertEqual((self.page._min_gold.value(), self.page._min_elixir.value()), (400, 0))
        self.assertEqual(self.page._min_elixir.text(), 'any')
        self.page._min_elixir.setValue(300)
        self.assertEqual((self.profile.attack_min_gold_k, self.profile.attack_min_elixir_k), (400, 300))
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
