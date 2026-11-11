"""Stats: sessions summed from the battle history, the CSV export, the Stats page, and the
Home Village raids written to the history."""
import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core import stats
from app.core.bot import Bot

try:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.qt.pages.stats import StatsPage
except ImportError:  # the CI test job installs no Qt
    QApplication = None

RECORDS = [
    {'t': '2026-11-10T09:00:00', 'village': 'home', 'gold': 100000, 'elixir': 50000, 'dark': 500},  # before sessions
    {'t': '2026-11-11T10:05:00', 'session': '2026-11-11T10:00:00', 'village': 'home', 'gold': 300000, 'elixir': 250000, 'dark': 2000},
    {'t': '2026-11-11T10:30:00', 'session': '2026-11-11T10:00:00', 'village': 'home', 'gold': 200000, 'elixir': 150000, 'dark': 1000},
    {'t': '2026-11-11T12:02:00', 'session': '2026-11-11T12:00:00', 'village': 'builder', 'stars': 3, 'damage': 158, 'gold': 142000, 'plan': 'mortar'},
    {'t': '2026-11-11T12:05:00', 'session': '2026-11-11T12:00:00', 'village': 'builder', 'stars': 1, 'damage': 75, 'gold': 30000, 'plan': 'core'},
]


class SessionTests(unittest.TestCase):
    def test_sessions_newest_first_with_their_rates(self):
        (bb, hv, old) = stats.sessions(RECORDS)
        self.assertEqual((bb.village, bb.battles, bb.gold, bb.stars, bb.damage), ('builder', 2, 172000, 2.0, 116.5))
        self.assertAlmostEqual(bb.hours, 5 / 60)
        self.assertEqual((hv.village, hv.battles, hv.gold, hv.elixir, hv.dark, hv.stars), ('home', 2, 500000, 400000, 3000, None))
        self.assertAlmostEqual(hv.per_hour(hv.gold), 1000000)  # 500k over half an hour
        self.assertEqual((old.battles, old.gold), (1, 100000))  # an unstamped record: its day

    def test_damage_of_the_last_builder_battles(self):
        self.assertEqual(stats.builder_damage(RECORDS), [(158, 3), (75, 1)])
        self.assertEqual(stats.builder_damage(RECORDS, last=1), [(75, 1)])

    def test_csv_export(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'b.csv'
            stats.write_csv(RECORDS, path)
            with open(path, encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 5)
        self.assertEqual((rows[3]['village'], rows[3]['damage'], rows[3]['plan']), ('builder', '158', 'mortar'))


class HistoryRecordTests(unittest.TestCase):
    def test_a_home_village_raid_goes_in_the_history(self):
        bot = Bot.__new__(Bot)
        bot._loot_callback = None
        bot._state_callback = None
        bot._reset_loot_session()
        bot._session_id = '2026-11-11T10:00:00'
        with patch('app.core.bot.battle_history.append') as append:
            bot._record_loot((1000000, 900000, 5000))
            bot._record_loot((1300000, 1150000, 7000))
            bot._record_loot((1300000, 1150000, 7000), village='builder')  # the Builder Base: from its results screen
        append.assert_called_once_with({'village': 'home', 'session': '2026-11-11T10:00:00', 'gold': 300000, 'elixir': 250000, 'dark': 2000})


@unittest.skipIf(QApplication is None, 'needs PySide6')
class StatsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_the_page_lists_the_sessions_and_charts_the_battles(self):
        with patch('app.ui.qt.pages.stats.battle_history.load', return_value=RECORDS):
            page = StatsPage()
            page.reload()
        self.assertEqual(page._table.rowCount(), 3)
        self.assertEqual([page._table.item(0, c).text() for c in (1, 2, 3, 8, 9)], ['Builder', '2', '172k', '2.0', '116 %'])
        self.assertEqual(page._chart._battles, [(158, 3), (75, 1)])
        self.assertIn('3 session(s)', page._summary.text())

    def test_an_empty_history(self):
        with patch('app.ui.qt.pages.stats.battle_history.load', return_value=[]):
            page = StatsPage()
            page.reload()
        self.assertEqual(page._table.rowCount(), 0)
        self.assertIn('No battle recorded yet', page._summary.text())


if __name__ == '__main__':
    unittest.main()
