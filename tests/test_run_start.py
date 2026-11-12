"""The Run page's Start: what it hands the controller in each village, switch by switch (a
temporary data dir and UI store, never the user's)."""
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from app.ui.qt.pages.run import RunPage
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, 'needs PySide6')
class StartArgumentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.pages = 0
        env = patch.dict(os.environ, {'LOCALAPPDATA': tmp.name, 'HOME': tmp.name})  # the page reads the profile's settings
        env.start()
        self.addCleanup(env.stop)

    def start(self, builder_base, mode, **boxes):
        '''Start from a fresh page with the given switches; the controller's keyword arguments.'''
        self.pages += 1  # a fresh UI store for each page
        settings = QSettings(os.path.join(self.tmp, f'ui{self.pages}.ini'), QSettings.Format.IniFormat)
        controller = Mock(**{'is_running.return_value': False})
        with patch('app.ui.qt.pages.run.QSettings', return_value=settings):
            page = RunPage(controller, lambda name: None)
        if builder_base:
            page._village_group.button(1).click()
        page._set_auto_upgrade_mode(mode)
        for (name, checked) in boxes.items():
            getattr(page, f'_{name}').setChecked(checked)
        with patch('app.ui.qt.pages.run.check_game_window_aspect_for_start', return_value=True):
            page.start_bot()
        settings.sync()  # nothing left to write when Qt drops it after the cleanup
        kwargs = controller.start.call_args.kwargs
        return {key: kwargs[key] for key in ('builder_base', 'upgrade_walls', 'auto_upgrade', 'auto_donate', 'auto_request',
                                             'stop_when_full', 'multi_run_players')}

    def test_the_home_village_reads_its_own_switches(self):
        self.assertEqual(self.start(False, 'maxer', upgrade_walls=True, bb_upgrade_walls=False, bb_auto_upgrade=False,
                                    auto_donate=True, auto_request=False, stop_when_full=True),
                         dict(builder_base=False, upgrade_walls=True, auto_upgrade='maxer', auto_donate=True, auto_request=False,
                              stop_when_full=True, multi_run_players=None))
        self.assertEqual(self.start(False, 'dry', upgrade_walls=False, bb_upgrade_walls=True, bb_auto_upgrade=True,
                                    auto_donate=False, auto_request=True, stop_when_full=False),
                         dict(builder_base=False, upgrade_walls=False, auto_upgrade='dry', auto_donate=False, auto_request=True,
                              stop_when_full=False, multi_run_players=None))

    def test_the_builder_base_reads_its_own_and_never_the_clan(self):
        self.assertEqual(self.start(True, 'rusher', upgrade_walls=False, bb_upgrade_walls=True, bb_auto_upgrade=True,
                                    auto_donate=True, auto_request=True, stop_when_full=True),
                         dict(builder_base=True, upgrade_walls=True, auto_upgrade='rusher', auto_donate=False, auto_request=False,
                              stop_when_full=True, multi_run_players=None))
        self.assertEqual(self.start(True, 'maxer', upgrade_walls=True, bb_upgrade_walls=False, bb_auto_upgrade=False,
                                    auto_donate=True, auto_request=True, stop_when_full=False),
                         dict(builder_base=True, upgrade_walls=False, auto_upgrade='off', auto_donate=False, auto_request=False,
                              stop_when_full=False, multi_run_players=None))


if __name__ == '__main__':
    unittest.main()
