import os
import unittest
from unittest.mock import patch

from app.utils.player_list_store import PlayerEntry

try:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.qt.pages.players import PlayersPage
except ImportError:  # the CI test job installs no Qt
    QApplication = None


@unittest.skipIf(QApplication is None, 'needs PySide6')
class PlayerOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        load = patch('app.ui.qt.pages.players.load_players', return_value=[])
        save = patch('app.ui.qt.pages.players.save_players')
        load.start()
        self.save = save.start()
        self.addCleanup(load.stop)
        self.addCleanup(save.stop)
        self.page = PlayersPage()
        for name in ('alice', 'bob', 'carol'):
            self.page._add_row(PlayerEntry(name=name, enabled=True))

    def assert_order(self, *names):
        """self._rows, the layout (rows, then its trailing stretch) and the last saved list all follow names."""
        layout = self.page._list_layout
        in_layout = [layout.itemAt(i).widget() for i in range(layout.count())]
        self.assertEqual(
            ([row._name.text() for row in self.page._rows],
             [w._name.text() if w is not None else 'stretch' for w in in_layout],
             [p.name for p in self.save.call_args.args[0]]),
            (list(names), list(names) + ['stretch'], list(names)))

    def test_moving_the_middle_player_up_swaps_it_with_the_first(self):
        self.page._move_row(self.page._rows[1], -1)
        self.assert_order('bob', 'alice', 'carol')

    def test_moving_the_middle_player_down_swaps_it_with_the_last(self):
        self.page._move_row(self.page._rows[1], 1)
        self.assert_order('alice', 'carol', 'bob')

    def test_moving_the_first_up_or_the_last_down_changes_nothing(self):
        saves = self.save.call_count
        self.page._move_row(self.page._rows[0], -1)
        self.page._move_row(self.page._rows[-1], 1)
        self.assertEqual(self.save.call_count, saves)
        self.assert_order('alice', 'bob', 'carol')


if __name__ == '__main__':
    unittest.main()
