"""player_list.json: the saved list loads back, and a hand-edited or broken file never raises
(a temporary file, never the user's)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.utils import player_list_store as store
from app.utils.player_list_store import PlayerEntry


class PlayerListLoadTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'player_list.json'
        where = patch.object(store, 'get_player_list_path', return_value=self.path)
        where.start()
        self.addCleanup(where.stop)

    def test_a_saved_list_loads_back(self):
        players = [PlayerEntry(name='Farm_1'), PlayerEntry(name='Farm_2', enabled=False)]
        store.save_players(players)
        self.assertEqual(store.load_players(), players)

    def test_a_file_saved_with_a_bom_is_read(self):
        self.path.write_text('\ufeff[{"name": "Farm_1"}]', encoding='utf-8')  # Notepad's "UTF-8 with BOM"
        self.assertEqual(store.load_players(), [PlayerEntry(name='Farm_1')])

    def test_entries_without_a_name_are_skipped(self):
        self.path.write_text('[{"name": "   "}, {"name": 5}, {}, "Farm_2", {"name": " Farm_1 ", "enabled": false}]', encoding='utf-8')
        self.assertEqual(store.load_players(), [PlayerEntry(name='Farm_1', enabled=False)])

    def test_an_unreadable_file_gives_an_empty_list(self):
        for (label, data) in (('not json', b'not json'), ('not UTF-8', b'[{"name": "Farm\xe9"}]'),
                              ('an int of over 4300 digits', b'[{"name": "Farm_1", "n": 1' + b'0' * 5000 + b'}]')):
            with self.subTest(label):
                self.path.write_bytes(data)
                self.assertEqual(store.load_players(), [])


if __name__ == '__main__':
    unittest.main()
