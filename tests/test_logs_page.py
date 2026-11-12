"""Logs page: each visit shows the end of basepilot.log once (every visit used to append the
whole file again under what was already shown)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.qt.pages import logs as logs_page
except ImportError:  # the CI test job installs no Qt
    QApplication = None


@unittest.skipIf(QApplication is None, 'needs PySide6')
class LogsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.log = Path(folder.name) / 'basepilot.log'
        log_path = patch.object(logs_page, 'get_log_path', return_value=self.log)
        log_path.start()
        self.addCleanup(log_path.stop)
        self.page = logs_page.LogsPage()

    def visit(self):
        self.page.show()
        self.page.hide()
        return self.page._log_view.toPlainText()

    def test_each_visit_shows_the_log_once(self):
        self.log.write_text('first\nsecond\n', encoding='utf-8')
        self.assertEqual(self.visit(), 'first\nsecond\n')
        self.assertEqual(self.visit(), 'first\nsecond\n')

    def test_lines_written_while_the_page_is_open_follow(self):
        self.log.write_text('first\n', encoding='utf-8')
        self.page.show()
        with self.log.open('a', encoding='utf-8') as fh:
            fh.write('second\n')
        self.page._tail_log()
        self.page.hide()
        self.assertEqual(self.page._log_view.toPlainText(), 'first\nsecond\n')

    def test_a_long_log_shows_its_end_from_the_start_of_a_line(self):
        self.log.write_bytes(b'0123456789\nabc\ndef\n')  # bytes: the cut is counted in bytes
        for tail in (10, 8):  # 8: the read starts right where the line "abc" does, it stays whole
            with self.subTest(tail=tail), patch.object(logs_page, '_TAIL_BYTES', tail):
                self.assertEqual(self.visit(), 'abc\ndef\n')

    def test_a_rolled_over_log_is_followed_from_its_start(self):
        self.log.write_bytes(b'old one\nold two\n')
        self.page.show()
        self.log.write_bytes(b'new\n')  # the rotating handler started a new, shorter file
        self.page._tail_log()
        self.page.hide()
        self.assertEqual(self.page._log_view.toPlainText(), 'old one\nold two\nnew\n')


if __name__ == '__main__':
    unittest.main()
