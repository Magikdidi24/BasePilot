"""The Settings page, built offscreen: each card's Save writes the whole profile and each Reset
brings the saved values back (a temporary data dir and app store, never the user's)."""
import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QPushButton

    from app.ui.qt.pages.settings import SettingsPage
except ImportError:
    QApplication = None

from app.utils import profile_settings_store as store


@unittest.skipIf(QApplication is None, 'needs PySide6')
class SettingsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {'LOCALAPPDATA': tmp.name, 'HOME': tmp.name})  # the profile's settings.json
        env.start()
        self.addCleanup(env.stop)
        self.app_settings = QSettings(os.path.join(tmp.name, 'app.ini'), QSettings.Format.IniFormat)
        with patch('PySide6.QtCore.QSettings', return_value=self.app_settings):  # the App card's store
            self.page = SettingsPage()
        self.addCleanup(self.app_settings.sync)

    def buttons(self, text):
        return [b for b in self.page.findChildren(QPushButton) if b.text() == text]

    def test_every_save_writes_the_whole_profile(self):
        page = self.page
        saves = self.buttons('Save')
        self.assertEqual(len(saves), 3)  # quake & walls, loot filter, clan
        for (i, save) in enumerate(saves):
            with self.subTest(card=i):
                page._wall_threshold.setValue(4 + i)
                page._upgrade_order.setCurrentIndex(1)
                page._attack_min_gold.setValue(100 * (i + 1))
                page._clan_request_interval.setValue(40 + i)
                save.click()
                saved = store.load_profile_settings()
                self.assertEqual((saved.wall_upgrade_threshold_m, saved.upgrade_order, saved.attack_min_gold_k, saved.clan_request_interval_m),
                                 (4 + i, store.UPGRADE_ORDER_CHEAPEST, 100 * (i + 1), 40 + i))
        page._upgrade_order.setCurrentIndex(0)
        saves[0].click()
        self.assertEqual(store.load_profile_settings().upgrade_order, store.UPGRADE_ORDER_PRICIEST)

    def test_every_reset_brings_the_saved_values_back(self):
        page = self.page
        store.save_profile_settings(store.ProfileSettings(wall_upgrade_threshold_m=9, upgrade_order=store.UPGRADE_ORDER_CHEAPEST,
                                                          attack_max_skips=7, clan_donate_count=3))
        resets = self.buttons('Reset')
        self.assertEqual(len(resets), 3)
        for (i, reset) in enumerate(resets):
            with self.subTest(card=i):
                page._wall_threshold.setValue(1)
                page._upgrade_order.setCurrentIndex(0)
                page._attack_max_skips.setValue(1)
                page._clan_donate_count.setValue(1)
                reset.click()
                self.assertEqual((page._wall_threshold.value(), page._upgrade_order.currentIndex(), page._attack_max_skips.value(),
                                  page._clan_donate_count.value()), (9, 1, 7, 3))


if __name__ == '__main__':
    unittest.main()
