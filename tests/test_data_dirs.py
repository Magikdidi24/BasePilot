"""Neither the copy of the pre-rebrand data dir (ClashAutoLoot) nor the seeding of a new
--profile overwrites a file the target dir holds. Both used to run at every launch until a
settings.json existed, copying the old player list (and window pin) over the newer ones; the
legacy copy now runs once, as it also brought back files the app had deleted."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.utils import common


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.old = Path(tmp.name) / 'ClashAutoLoot'
        self.new = Path(tmp.name) / 'BasePilot'
        self.old.mkdir()
        for patcher in (patch.object(common, '_legacy_data_dir', return_value=self.old),
                        patch.object(common, '_migration_checked', False)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_files_the_new_dir_holds_are_kept(self):
        (self.old / 'player_list.json').write_text('old players', encoding='utf-8')
        (self.old / 'window.json').write_text('old window', encoding='utf-8')
        (self.old / 'display_restore.devmode').write_bytes(b'old mode')
        self.new.mkdir()
        (self.new / 'player_list.json').write_text('new players', encoding='utf-8')
        (self.new / 'display_restore.devmode').write_bytes(b'new mode')
        common._maybe_migrate_legacy_data(self.new)
        self.assertEqual((self.new / 'player_list.json').read_text(encoding='utf-8'), 'new players')
        self.assertEqual((self.new / 'display_restore.devmode').read_bytes(), b'new mode')
        self.assertEqual((self.new / 'window.json').read_text(encoding='utf-8'), 'old window')  # missing: copied

    def test_nothing_is_copied_once_the_new_dir_has_its_settings(self):
        (self.old / 'window.json').write_text('old window', encoding='utf-8')
        (self.old / 'display_restore.devmode').write_bytes(b'old mode')
        self.new.mkdir()
        (self.new / 'settings.json').write_text('{}', encoding='utf-8')
        common._maybe_migrate_legacy_data(self.new)
        self.assertFalse((self.new / 'window.json').exists())
        (self.new / 'settings.json').unlink()  # deleted later by hand
        common._migration_checked = False  # the next launch
        common._maybe_migrate_legacy_data(self.new)
        self.assertEqual(sorted(p.name for p in self.new.iterdir()), [common._LEGACY_MIGRATED_MARKER])  # no old display mode back

    def test_the_first_launch_copies_everything(self):
        (self.old / 'settings.json').write_text('{}', encoding='utf-8')
        (self.old / 'window.json').write_text('old window', encoding='utf-8')
        common._maybe_migrate_legacy_data(self.new)  # first launch: the new dir does not exist
        self.assertEqual((self.new / 'window.json').read_text(encoding='utf-8'), 'old window')
        self.assertTrue((self.new / 'settings.json').exists())

    def test_a_later_launch_brings_nothing_back(self):
        (self.old / 'window.json').write_text('old window', encoding='utf-8')
        common._maybe_migrate_legacy_data(self.new)
        (self.new / 'window.json').unlink()  # Settings -> Auto-detect drops the pin
        common._migration_checked = False  # the next launch
        common._maybe_migrate_legacy_data(self.new)
        self.assertFalse((self.new / 'window.json').exists())


class ProfileSeedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.main = Path(tmp.name) / 'BasePilot'
        self.profile = self.main / 'profiles' / 'alt'
        self.main.mkdir()
        seeded = patch.object(common, '_seeded_profiles', set())
        seeded.start()
        self.addCleanup(seeded.stop)

    def test_a_new_profile_starts_from_the_main_settings_but_not_its_pin(self):
        (self.main / 'settings.json').write_text('{"a": 1}', encoding='utf-8')
        (self.main / 'player_list.json').write_text('main players', encoding='utf-8')
        (self.main / 'window.json').write_text('main pin', encoding='utf-8')
        common._seed_profile(self.main, self.profile)
        self.assertEqual((self.profile / 'settings.json').read_text(encoding='utf-8'), '{"a": 1}')
        self.assertEqual((self.profile / 'player_list.json').read_text(encoding='utf-8'), 'main players')
        self.assertFalse((self.profile / 'window.json').exists())

    def test_a_profile_keeps_its_own_player_list(self):
        (self.main / 'player_list.json').write_text('main players', encoding='utf-8')  # main: no settings.json
        self.profile.mkdir(parents=True)
        (self.profile / 'player_list.json').write_text('profile players', encoding='utf-8')
        common._seed_profile(self.main, self.profile)
        self.assertEqual((self.profile / 'player_list.json').read_text(encoding='utf-8'), 'profile players')

    def test_each_file_is_copied_unless_the_profile_has_it(self):
        (self.main / 'settings.json').write_text('{"a": 1}', encoding='utf-8')
        (self.main / 'player_list.json').write_text('main players', encoding='utf-8')
        self.profile.mkdir(parents=True)
        (self.profile / 'player_list.json').write_text('profile players', encoding='utf-8')
        common._seed_profile(self.main, self.profile)
        self.assertEqual((self.profile / 'settings.json').read_text(encoding='utf-8'), '{"a": 1}')
        self.assertEqual((self.profile / 'player_list.json').read_text(encoding='utf-8'), 'profile players')


if __name__ == '__main__':
    unittest.main()
