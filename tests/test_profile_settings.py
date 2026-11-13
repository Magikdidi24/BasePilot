"""The profile's settings.json: every field brought into range on save and on load, a hand-edited
or broken file read as the nearest valid settings (a temporary file, never the user's)."""
import json
import tempfile
import unittest
from dataclasses import asdict, fields
from pathlib import Path
from unittest.mock import patch

from app.utils import profile_settings_store as store
from app.utils.profile_settings_store import ProfileSettings

# Out of range, of the wrong type or spelled loosely, field by field.
WILD = dict(earthquake_method='Random placement', wall_upgrade_threshold_m=10 ** 6, reserve_builders=-3,
            upgrade_order=' Cheapest ', clan_dry_run=0, clan_chat_point=[0.5, 2], clan_chat_point_aspect=' 16_9 ',
            clan_donate_troop='EDRAGS', clan_donate_count='x', clan_min_elixir_k=-1, clan_donate_interval_m=-4,
            clan_request_interval_m=10 ** 6, attack_min_gold_k=10 ** 9, attack_min_elixir_k=-5, attack_min_dark_k='7',
            attack_max_skips=10 ** 6, bb_wall_threshold_k=-1)
TAMED = ProfileSettings(earthquake_method=store.EARTHQUAKE_METHOD_RANDOM, wall_upgrade_threshold_m=store.WALL_UPGRADE_THRESHOLD_M_MAX,
                        reserve_builders=0, upgrade_order='cheapest', clan_dry_run=False, clan_chat_point=None,
                        clan_chat_point_aspect='16_9', clan_donate_troop='edrags', clan_donate_count=store.CLAN_DONATE_COUNT_DEFAULT,
                        clan_min_elixir_k=0, clan_donate_interval_m=store.CLAN_DONATE_INTERVAL_M_MIN,
                        clan_request_interval_m=store.CLAN_REQUEST_INTERVAL_M_MAX, attack_min_gold_k=store.ATTACK_MIN_LOOT_K_MAX,
                        attack_min_elixir_k=0, attack_min_dark_k=7, attack_max_skips=store.ATTACK_MAX_SKIPS_MAX,
                        bb_wall_threshold_k=0)


class ProfileSettingsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'settings.json'
        where = patch.object(store, 'get_settings_path', return_value=self.path)
        where.start()
        self.addCleanup(where.stop)

    def test_save_brings_every_field_into_range(self):
        store.save_profile_settings(ProfileSettings(**WILD))
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), asdict(TAMED))
        self.assertEqual(store.load_profile_settings(), TAMED)

    def test_a_hand_edited_file_is_brought_into_range(self):
        self.path.write_text(json.dumps(WILD), encoding='utf-8')
        self.assertEqual(store.load_profile_settings(), TAMED)

    def test_every_field_is_saved_and_loaded(self):
        values = dict(earthquake_method=store.EARTHQUAKE_METHOD_LEARN, wall_upgrade_threshold_m=7, reserve_builders=2,
                      upgrade_order=store.UPGRADE_ORDER_CHEAPEST, clan_dry_run=False, clan_chat_point=[0.25, 0.75],
                      clan_chat_point_aspect='16_9', clan_donate_troop='edrags', clan_donate_count=4, clan_min_elixir_k=900,
                      clan_donate_interval_m=15, clan_request_interval_m=45, attack_min_gold_k=300, attack_min_elixir_k=200,
                      attack_min_dark_k=3, attack_max_skips=12, bb_wall_threshold_k=1500)
        self.assertEqual(set(values), {f.name for f in fields(ProfileSettings)})  # a new field must join this test
        for f in fields(ProfileSettings):
            self.assertNotEqual(values[f.name], f.default, f.name)  # a field dropped on the way would read as its default
        settings = ProfileSettings(**values)
        store.save_profile_settings(settings)
        self.assertEqual(store.load_profile_settings(), settings)

    def test_an_unreadable_file_is_reported_once(self):
        self.path.write_text('not json', encoding='utf-8')
        with self.assertLogs('Settings', 'WARNING') as logs:
            store.load_profile_settings()
            store.load_profile_settings()
        self.assertEqual(len(logs.output), 1)
        self.assertIn('Unreadable settings', logs.output[0])

    def test_missing_fields_take_their_defaults(self):
        self.path.write_text('{"attack_max_skips": 3}', encoding='utf-8')
        self.assertEqual(store.load_profile_settings(), ProfileSettings(attack_max_skips=3))

    def test_an_infinite_or_huge_number_gives_the_default(self):
        # json reads Infinity and 1e999 as float('inf') and NaN as nan, which int() cannot take;
        # float() cannot take an int past 1.8e308
        self.path.write_text('{"attack_min_gold_k": 7, "attack_max_skips": Infinity, "reserve_builders": 1e999, '
                             '"wall_upgrade_threshold_m": -Infinity, '
                             '"clan_min_elixir_k": NaN, "clan_chat_point": [1' + '0' * 309 + ', 0.5]}', encoding='utf-8')
        # the valid field shows each bad one fell back alone, not the whole file
        self.assertEqual(store.load_profile_settings(), ProfileSettings(attack_min_gold_k=7))

    def test_a_file_that_is_not_utf8_gives_the_defaults(self):
        self.path.write_bytes(b'{"upgrade_order": "cheapest\xe9"}')
        self.assertEqual(store.load_profile_settings(), ProfileSettings())

    def test_a_file_saved_with_a_bom_is_read(self):
        self.path.write_text('\ufeff{"attack_max_skips": 3}', encoding='utf-8')  # Notepad's "UTF-8 with BOM"
        self.assertEqual(store.load_profile_settings(), ProfileSettings(attack_max_skips=3))

    def test_a_broken_or_absent_file_gives_the_defaults(self):
        self.assertEqual(store.load_profile_settings(), ProfileSettings())
        huge = '{"attack_max_skips": 1' + '0' * 5000 + '}'  # json refuses ints of over 4300 digits
        for text in ('not json', '[1, 2]', huge):
            with self.subTest(text[:30]):
                self.path.write_text(text, encoding='utf-8')
                self.assertEqual(store.load_profile_settings(), ProfileSettings())


if __name__ == '__main__':
    unittest.main()
