"""The bot's wait loops: what each one looks at, how long it pauses, when it gives up and what it
logs. Simulated time: the clock only moves when the bot pauses on its stop event."""
import unittest
from unittest.mock import Mock, call, patch

import numpy as np

from app.core.bot import Bot

FRAME = np.zeros((767, 1227, 3), np.uint8)
BOTTOM_HALF = (0, 383, 1227, 384)
RIGHT_HALF = (613, 0, 614, 767)
MISS = (None, None)


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.pauses = []

    def time(self):
        return self.now

    def wait(self, seconds):
        self.pauses.append(seconds)
        self.now += seconds
        return False  # not stopped


class WaitLoopTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        for (target, value) in (('app.core.bot.time.time', self.clock.time), ('app.core.bot.random.uniform', lambda lo, hi: 0.2)):
            patcher = patch(target, new=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        bot = self.bot = Bot.__new__(Bot)
        bot.stop_event = Mock(**{'is_set.return_value': False, 'wait.side_effect': self.clock.wait})
        bot.window = Mock(**{'screenshot.return_value': FRAME})
        bot.input = Mock()
        bot.config = Mock(**{'get_point.return_value': (640, 700)})
        bot.vision = Mock(**{'find_control.return_value': MISS, 'find_template.return_value': MISS,
                             'find_word_on_screen.return_value': MISS})
        bot._battle_rewards = Mock(**{'handle.return_value': False})
        for (name, value) in (('_update_config_size', None), ('_scroll_point', (500, 400)), ('_status', None),
                              ('_frame_shows_supercell_login_prompt', False), ('_scroll_player_list_with_drag', None),
                              ('_dismiss_okay_or_exit_on_frame', False), ('_live_battle_button', MISS),
                              ('_nudge_view_to_reveal_attack', None), ('_home_hud_visible', True),
                              ('_leave_builder_base_with_nboat', None)):
            setattr(bot, name, Mock(return_value=value))


WAITS = {
    'image': lambda bot: bot._wait_for_image('x.png'),
    'any image': lambda bot: bot._wait_for_any_image(['a.png', 'b.png']),
    'player name': lambda bot: bot._wait_for_player_name('Farm_1'),
    'attack': lambda bot: bot._wait_for_attack_with_nudge(),
    'wake home': lambda bot: bot._wake_home_and_wait_for_attack(),
}


class StopTests(WaitLoopTestCase):
    def test_a_stop_before_a_look_raises(self):
        self.bot.stop_event.is_set.return_value = True
        for (name, wait) in WAITS.items():
            with self.subTest(name), self.assertRaises(InterruptedError):
                wait(self.bot)
        self.bot.vision.find_control.assert_not_called()

    def test_a_stop_during_a_pause_ends_the_wait_quietly(self):
        self.bot.stop_event.wait.side_effect = lambda seconds: True
        for frame in (FRAME, None):
            self.bot.window.screenshot.return_value = frame
            for (name, wait) in WAITS.items():
                with self.subTest(name, frame=frame is not None), self.assertNoLogs('BotCore', 'WARNING'):
                    self.assertEqual(wait(self.bot), MISS)


class ImageWaitTests(WaitLoopTestCase):
    def test_the_first_frame_that_shows_the_template_ends_the_wait(self):
        self.bot.vision.find_control.side_effect = [MISS, MISS, (10, 20)]
        self.assertEqual(self.bot._wait_for_image('x.png', region=(1, 2, 3, 4), threshold=0.7), (10, 20))
        self.assertEqual(self.clock.pauses, [0.5, 0.5])
        # the button's label is read too once a second has gone by
        self.assertEqual(self.bot.vision.find_control.call_args_list,
                         [call(FRAME, 'x.png', threshold=0.7, region=(1, 2, 3, 4), ocr=ocr) for ocr in (False, False, True)])

    def test_no_frame_is_waited_out_half_a_second_at_a_time(self):
        self.bot.window.screenshot.side_effect = [None, None, FRAME]
        self.bot.vision.find_control.return_value = (10, 20)
        self.assertEqual(self.bot._wait_for_image('x.png'), (10, 20))
        self.assertEqual(self.clock.pauses, [0.5, 0.5])
        self.bot._update_config_size.assert_called_once_with(FRAME)
        self.bot.vision.find_control.assert_called_once()

    def test_a_battle_reward_is_closed_then_the_screen_looked_at_again_at_once(self):
        self.bot._battle_rewards.handle.side_effect = [True, False]
        self.bot.vision.find_control.return_value = (10, 20)
        self.assertEqual(self.bot._wait_for_image('x.png'), (10, 20))
        self.assertEqual(self.clock.pauses, [])
        self.assertEqual(self.bot.window.screenshot.call_count, 2)
        self.bot.vision.find_control.assert_called_once()

    def test_the_search_stays_near_an_anchor(self):
        self.bot.vision.find_control.return_value = (10, 20)
        self.bot._wait_for_image('x.png', y_anchor=300, y_slop=100)
        self.assertEqual(self.bot.vision.find_control.call_args.kwargs['region'], (0, 200, 1227, 200))

    def test_a_time_out_is_logged_once(self):
        with self.assertLogs('BotCore', 'WARNING') as logs:
            self.assertEqual(self.bot._wait_for_image('x.png', timeout=2), MISS)
        self.assertEqual(self.clock.pauses, [0.5] * 4)
        self.assertEqual(logs.output, ['WARNING:BotCore:Timeout waiting for x.png'])

    def test_no_warning_without_error(self):
        with self.assertNoLogs('BotCore', 'WARNING'):
            self.assertEqual(self.bot._wait_for_image('x.png', timeout=2, error=False), MISS)


class AnyImageWaitTests(WaitLoopTestCase):
    def test_the_first_template_in_order_wins(self):
        hits = {'b.png': (2, 2), 'c.png': (3, 3)}
        self.bot.vision.find_control.side_effect = lambda frame, name, **kw: hits.get(name, MISS)
        self.assertEqual(self.bot._wait_for_any_image(['a.png', 'b.png', 'c.png']), (2, 2))
        self.assertEqual([c.args[1] for c in self.bot.vision.find_control.call_args_list], ['a.png', 'b.png'])

    def test_the_label_is_read_too_after_label_after(self):
        self.bot.vision.find_control.side_effect = lambda frame, name, ocr, **kw: (5, 5) if ocr else MISS
        self.assertEqual(self.bot._wait_for_any_image(['a.png'], threshold=0.6), (5, 5))
        self.assertEqual(self.clock.pauses, [0.5, 0.5])
        self.assertEqual(self.bot.vision.find_control.call_args, call(FRAME, 'a.png', threshold=0.6, region=None, ocr=True))
        self.bot.vision.find_control.reset_mock()
        self.bot._wait_for_any_image(['a.png'], label_after=0)
        self.bot.vision.find_control.assert_called_once()

    def test_a_region_from_the_frame_serves_every_template(self):
        region_from_frame = Mock(return_value=(1, 2, 3, 4))
        self.bot._wait_for_any_image(['a.png', 'b.png'], timeout=0.5, error=False, region_from_frame=region_from_frame)
        region_from_frame.assert_called_once_with(FRAME)
        self.assertEqual([c.kwargs['region'] for c in self.bot.vision.find_control.call_args_list], [(1, 2, 3, 4)] * 2)

    def test_an_explicit_region_wins(self):
        region_from_frame = Mock()
        self.bot._wait_for_any_image(['a.png'], timeout=0.5, error=False, region=(5, 6, 7, 8), region_from_frame=region_from_frame)
        region_from_frame.assert_not_called()
        self.assertEqual(self.bot.vision.find_control.call_args.kwargs['region'], (5, 6, 7, 8))

    def test_without_a_region_each_template_gets_its_own(self):
        self.bot._search_region_for_template = Mock(side_effect=lambda frame, name, *rest: name)
        self.bot._wait_for_any_image(['a.png', 'b.png'], timeout=0.5, error=False)
        self.assertEqual(self.bot._search_region_for_template.call_args_list,
                         [call(FRAME, 'a.png', None, None, 200), call(FRAME, 'b.png', None, None, 200)])
        self.assertEqual([c.kwargs['region'] for c in self.bot.vision.find_control.call_args_list], ['a.png', 'b.png'])

    def test_rewards_and_missing_frames(self):
        self.bot.window.screenshot.side_effect = [None, FRAME, FRAME]
        self.bot._battle_rewards.handle.side_effect = [True, False]
        self.bot.vision.find_control.return_value = (7, 7)
        self.assertEqual(self.bot._wait_for_any_image(['a.png']), (7, 7))
        self.assertEqual(self.clock.pauses, [0.5])
        self.bot.vision.find_control.assert_called_once()

    def test_the_time_out_names_every_template_once(self):
        with self.assertLogs('BotCore', 'WARNING') as logs:
            self.assertEqual(self.bot._wait_for_any_image(['a.png', 'b.png'], timeout=1), MISS)
        self.assertEqual(self.clock.pauses, [0.5, 0.5])
        self.assertEqual(logs.output, ["WARNING:BotCore:Timeout waiting for any of ['a.png', 'b.png']"])


class PlayerNameWaitTests(WaitLoopTestCase):
    def test_a_miss_scrolls_the_list_and_pauses(self):
        self.bot.vision.find_word_on_screen.side_effect = [MISS, (30, 40)]
        self.assertEqual(self.bot._wait_for_player_name('Farm_1', match_alnum_only=True), (30, 40))
        self.bot._scroll_player_list_with_drag.assert_called_once_with(FRAME)
        self.assertEqual(self.clock.pauses, [0.45])
        self.assertEqual(self.bot.vision.find_word_on_screen.call_args, call(FRAME, 'Farm_1', region=RIGHT_HALF, match_alnum_only=True))

    def test_an_explicit_region_is_read_instead(self):
        self.bot.vision.find_word_on_screen.return_value = (30, 40)
        self.bot._wait_for_player_name('Farm_1', region=(1, 2, 3, 4))
        self.assertEqual(self.bot.vision.find_word_on_screen.call_args.kwargs['region'], (1, 2, 3, 4))

    def test_the_supercell_id_login_screen_stops_the_switch(self):
        self.bot._frame_shows_supercell_login_prompt.return_value = True
        with self.assertLogs('BotCore', 'WARNING'), self.assertRaises(RuntimeError):
            self.bot._wait_for_player_name('Farm_1')
        self.bot._status.assert_called_once()
        self.bot._scroll_player_list_with_drag.assert_not_called()

    def test_no_frame_then_a_time_out_logged_once(self):
        self.bot.window.screenshot.side_effect = [None] + [FRAME] * 10
        with self.assertLogs('BotCore', 'WARNING') as logs:
            self.assertEqual(self.bot._wait_for_player_name('Farm_1', timeout=1.2), MISS)
        self.assertEqual(self.clock.pauses, [0.5, 0.45, 0.45])
        self.assertEqual(logs.output, ["WARNING:BotCore:Timeout waiting for player name OCR match: 'Farm_1'"])

    def test_no_warning_without_error(self):
        with self.assertNoLogs('BotCore', 'WARNING'):
            self.assertEqual(self.bot._wait_for_player_name('Farm_1', timeout=1, error=False), MISS)


class AttackWaitTests(WaitLoopTestCase):
    def test_a_popup_is_closed_then_the_screen_looked_at_again(self):
        self.bot._dismiss_okay_or_exit_on_frame.side_effect = [True, False]
        self.bot.vision.find_control.return_value = (100, 700)
        self.assertEqual(self.bot._wait_for_attack_with_nudge(), (100, 700))
        self.assertEqual(self.clock.pauses, [0.25])
        self.bot.vision.find_control.assert_called_once()
        self.bot._nudge_view_to_reveal_attack.assert_not_called()

    def test_a_miss_nudges_the_view(self):
        self.bot.vision.find_control.side_effect = [MISS, MISS, MISS, (100, 700)]
        self.assertEqual(self.bot._wait_for_attack_with_nudge(), (100, 700))
        self.assertEqual(self.bot._nudge_view_to_reveal_attack.call_count, 3)
        self.assertEqual(self.clock.pauses, [0.35] * 3)
        # in the bottom half, and the label read too once a second has gone by
        self.assertEqual(self.bot.vision.find_control.call_args_list,
                         [call(FRAME, 'attack.png', region=BOTTOM_HALF, ocr=ocr) for ocr in (False, False, False, True)])

    def test_a_live_battle_ends_the_wait_without_a_nudge(self):
        self.bot._live_battle_button.return_value = (90, 600)
        with self.assertLogs('BotCore', 'WARNING') as logs:
            self.assertEqual(self.bot._wait_for_attack_with_nudge(), MISS)
        self.assertEqual(len(logs.output), 1)
        self.assertIn('live battle detected', logs.output[0])
        self.bot._nudge_view_to_reveal_attack.assert_not_called()
        self.assertEqual(self.clock.pauses, [])

    def test_no_frame_then_a_time_out_logged_once(self):
        self.bot.window.screenshot.side_effect = [None] + [FRAME] * 10
        with self.assertLogs('BotCore', 'WARNING') as logs:
            self.assertEqual(self.bot._wait_for_attack_with_nudge(timeout=1), MISS)
        self.assertEqual(self.clock.pauses, [0.5, 0.35, 0.35])
        self.assertEqual(logs.output, ['WARNING:BotCore:Timeout waiting for attack.png'])

    def test_no_warning_without_error(self):
        with self.assertNoLogs('BotCore', 'WARNING'):
            self.assertEqual(self.bot._wait_for_attack_with_nudge(timeout=1, error=False), MISS)


class WakeHomeWaitTests(WaitLoopTestCase):
    def test_the_village_is_woken_then_the_attack_button_found(self):
        self.bot.vision.find_control.return_value = (100, 700)
        self.assertEqual(self.bot._wake_home_and_wait_for_attack(), (100, 700))
        self.bot.input.click.assert_called_once_with(640, 700, pause=0.2)
        self.bot.input.scroll.assert_called_once_with(500, 400, 20)
        self.assertEqual(self.clock.pauses, [0.2])
        self.assertEqual(self.bot.vision.find_control.call_args, call(FRAME, 'attack.png', region=BOTTOM_HALF, ocr=False))

    def test_a_builder_base_login_is_left_first(self):
        self.bot.vision.find_template.side_effect = [(50, 60), MISS]  # mbuilder.png on the first look
        self.bot.vision.find_control.return_value = (100, 700)
        self.assertEqual(self.bot._wake_home_and_wait_for_attack(), (100, 700))
        self.bot._leave_builder_base_with_nboat.assert_called_once_with(settle_before_drag=False)
        self.assertEqual(self.clock.pauses, [0.2, 1])
        self.bot.vision.find_control.assert_called_once()

    def test_a_popup_is_closed_then_the_screen_looked_at_again(self):
        self.bot._dismiss_okay_or_exit_on_frame.side_effect = [True, False]
        self.bot.vision.find_control.return_value = (100, 700)
        self.assertEqual(self.bot._wake_home_and_wait_for_attack(), (100, 700))
        self.assertEqual(self.clock.pauses, [0.2, 0.25])

    def test_no_frame_and_no_home_screen_both_nudge(self):
        self.bot.window.screenshot.side_effect = [FRAME, None, FRAME, FRAME]  # the first is the wake-up's
        self.bot._home_hud_visible.side_effect = [False, True]
        self.bot.vision.find_control.return_value = (100, 700)
        self.assertEqual(self.bot._wake_home_and_wait_for_attack(), (100, 700))
        self.assertEqual(self.bot._nudge_view_to_reveal_attack.call_count, 2)
        self.assertEqual(self.clock.pauses, [0.2, 0.35, 0.35])

    def test_a_time_out_is_quiet(self):
        self.bot._home_hud_visible.return_value = False
        with self.assertNoLogs('BotCore', 'WARNING'):
            self.assertEqual(self.bot._wake_home_and_wait_for_attack(timeout=1), MISS)
        self.assertEqual(self.clock.pauses, [0.2, 0.35, 0.35, 0.35])


if __name__ == '__main__':
    unittest.main()
