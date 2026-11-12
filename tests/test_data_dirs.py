"""The copy of the pre-rebrand data dir (ClashAutoLoot) never overwrites a file the new dir holds,
and runs once: while the new dir had no settings.json it ran at every launch, copying the old
player_list.json and window.json over the newer ones and bringing back what the app deleted."""
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
        self.new.mkdir()
        (self.new / 'settings.json').write_text('{}', encoding='utf-8')
        common._maybe_migrate_legacy_data(self.new)
        self.assertFalse((self.new / 'window.json').exists())

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


if __name__ == '__main__':
    unittest.main()
