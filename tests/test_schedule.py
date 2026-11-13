"""Start at set times: the times written on the Run page, when each is due, and the page
pressing Start by itself at that time (settings in a temporary file, not the user's)."""
import unittest
from datetime import datetime, time
from unittest.mock import Mock, patch

from app.core import schedule
from tests.helpers import QtTestCase

try:
    from PySide6.QtWidgets import QApplication
    from app.ui.qt.pages.run import RunPage
except ImportError:  # no PySide6
    QApplication = None


class ParseTests(unittest.TestCase):
    def test_times_and_the_words_that_are_none(self):
        (times, bad) = schedule.parse_times('8:00, 13h30 21.05;08:00  25:00 noon')
        self.assertEqual(times, [time(8, 0), time(13, 30), time(21, 5)])
        self.assertEqual(bad, ['25:00', 'noon'])
        self.assertEqual(schedule.parse_times(''), ([], []))
        self.assertEqual(schedule.format_times(times), '08:00, 13:30, 21:05')


class DueTests(unittest.TestCase):
    times = [time(8, 0), time(23, 55)]

    def test_due_from_its_minute_for_ten_minutes_and_once(self):
        at = datetime(2026, 11, 12, 8, 0)
        self.assertIsNone(schedule.due(datetime(2026, 11, 12, 7, 59, 50), self.times))
        self.assertEqual(schedule.due(datetime(2026, 11, 12, 8, 0, 5), self.times), at)
        self.assertEqual(schedule.due(datetime(2026, 11, 12, 8, 9, 59), self.times), at)  # late: a run was going on
        self.assertIsNone(schedule.due(datetime(2026, 11, 12, 8, 10), self.times))  # too late
        self.assertIsNone(schedule.due(datetime(2026, 11, 12, 8, 3), self.times, last=at))  # it went already
        self.assertEqual(schedule.due(datetime(2026, 11, 13, 8, 1), self.times, last=at), datetime(2026, 11, 13, 8, 0))  # the next day

    def test_across_midnight(self):
        self.assertEqual(schedule.due(datetime(2026, 11, 13, 0, 2), self.times), datetime(2026, 11, 12, 23, 55))

    def test_next_start(self):
        self.assertEqual(schedule.next_start(datetime(2026, 11, 12, 9, 0), self.times), datetime(2026, 11, 12, 23, 55))
        self.assertEqual(schedule.next_start(datetime(2026, 11, 12, 23, 56), self.times), datetime(2026, 11, 13, 8, 0))
        self.assertIsNone(schedule.next_start(datetime(2026, 11, 12, 9, 0), []))


@unittest.skipIf(QApplication is None, 'needs PySide6')
class RunPageScheduleTests(QtTestCase):
    def setUp(self):
        super().setUp()
        self.controller = Mock()
        self.controller.is_running.return_value = False
        self.settings = self.temp_settings()
        self.page = self.make_page()
        self.started = []
        self.page.scheduledStart.connect(self.started.append)

    def make_page(self):
        with patch('app.ui.qt.pages.run.QSettings', return_value=self.settings):
            page = RunPage(self.controller, lambda name: None)
        page.start_bot = Mock(side_effect=lambda: self.controller.is_running.configure_mock(return_value=True))
        return page

    def test_a_set_time_starts_the_run_once(self):
        self.page._times_edit.setText('08:00, 20:30')
        self.page._timed.setChecked(True)
        self.page._check_schedule(datetime(2026, 11, 12, 7, 59))
        self.page.start_bot.assert_not_called()
        self.page._check_schedule(datetime(2026, 11, 12, 8, 0, 10))
        self.page.start_bot.assert_called_once()
        self.assertEqual(self.started, ['08:00'])
        self.controller.is_running.return_value = False  # that run is over already
        self.page._check_schedule(datetime(2026, 11, 12, 8, 4))
        self.page.start_bot.assert_called_once()  # not twice for one time
        self.assertEqual(self.settings.value('schedule/times'), '08:00, 20:30')
        self.assertTrue(self.settings.value('schedule/enabled', type=bool))

    def test_a_run_going_on_puts_the_start_off_until_it_ends(self):
        self.page._times_edit.setText('08:00')
        self.page._timed.setChecked(True)
        self.controller.is_running.return_value = True
        self.page._check_schedule(datetime(2026, 11, 12, 8, 0, 10))
        self.page.start_bot.assert_not_called()
        self.controller.is_running.return_value = False
        self.page._check_schedule(datetime(2026, 11, 12, 8, 6))
        self.page.start_bot.assert_called_once()

    def test_switched_off_or_no_time_starts_nothing(self):
        self.page._times_edit.setText('8:00 noon')
        self.assertEqual(self.page._times_note.text(), 'Not a time: noon')
        self.page._check_schedule(datetime(2026, 11, 12, 8, 0, 10))  # the switch is off
        self.page.start_bot.assert_not_called()
        self.page._times_edit.setText('8:00')
        self.assertEqual(self.page._times_note.text(), 'Off')
        self.page._timed.setChecked(True)
        self.page._update_schedule_note(datetime(2026, 11, 12, 9, 0))
        self.assertEqual(self.page._times_note.text(), 'Next start: tomorrow 08:00')

    def test_the_times_and_the_last_start_come_back_after_a_restart(self):
        self.page._times_edit.setText('21:00')
        self.page._timed.setChecked(True)
        self.page._check_schedule(datetime(2026, 11, 12, 21, 0, 5))
        page = self.make_page()
        self.assertEqual((page._times_edit.text(), page._timed.isChecked()), ('21:00', True))
        self.controller.is_running.return_value = False
        page._check_schedule(datetime(2026, 11, 12, 21, 2))
        page.start_bot.assert_not_called()  # 21:00 went before the restart


if __name__ == '__main__':
    unittest.main()
