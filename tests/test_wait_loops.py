"""The bot's wait loops: what each one looks at, how long it pauses, when it gives up and what it
logs. Simulated time: the clock only moves when the bot pauses on its stop event, or when a test
makes a scan slow."""
import unittest
from unittest.mock import Mock, call, patch

import numpy as np

from tests.helpers import bare_bot

FRAME = np.zeros((767, 1227, 3), np.uint8)
BOTTOM_HALF = (0, 383, 1227, 384)
RIGHT_HALF = (613, 0, 614, 767)
MISS = (None, None)
MISS3 = (None, None, None)
NO_NAME = (MISS, False, None)  # find_word_match: no name read
NEAR = (3, -2)  # the rank of a near name, as find_word_match gives it


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
        bot = self.bot = bare_bot(FRAME)
        bot.stop_event.wait.side_effect = self.clock.wait
        bot.config = Mock(aspect_key='16_10', **{'get_point.return_value': (640, 700)})
        bot.vision = Mock(**{'find_control.return_value': MISS, 'find_template.return_value': MISS,
                             'find_label.return_value': MISS, 'find_word_match.return_value': NO_NAME,
                             'find_words_ocr.side_effect': lambda frame, region: [Mock(text=f'row {self.clock.now}')]})
        bot._battle_rewards = Mock(**{'handle.return_value': False})
        for (name, value) in (('_update_config_size', None), ('_scroll_point', (500, 400)), ('_status', None),
                              ('_frame_shows_supercell_login_prompt', False), ('_scroll_player_list_with_drag', None),
                              ('_dismiss_okay_or_exit_on_frame', False), ('_live_battle_button', MISS),
                              ('_nudge_view_to_reveal_attack', None), ('_home_hud_visible', True),
                              ('_leave_builder_base_with_nboat', None)):
            setattr(bot, name, Mock(return_value=value))

    def slow(self, result, seconds):
        """A scan that takes ``seconds`` of simulated time, then answers ``result``."""
        def scan(*args, **kwargs):
            self.clock.now += seconds
            return result
        return scan


WAITS = {  # each wait with what it returns when it finds nothing
    'image': (lambda bot: bot._wait_for_image('x.png'), MISS),
    'any image': (lambda bot: bot._wait_for_any_image(['a.png', 'b.png']), MISS),
    'player name': (lambda bot: bot._wait_for_player_name('Farm_1'), MISS),
    'attack': (lambda bot: bot._wait_for_attack_with_nudge(), MISS),
    'wake home': (lambda bot: bot._wake_home_and_wait_for_attack(), MISS),
    'return home': (lambda bot: bot._wait_for_return_home_or_chest_claim(), MISS3),
}


class StopTests(WaitLoopTestCase):
    def test_a_stop_before_a_look_raises(self):
        self.bot.stop_event.is_set.return_value = True
        for (name, (wait, _miss)) in WAITS.items():
            with self.subTest(name), self.assertRaises(InterruptedError):
                wait(self.bot)
        self.bot.vision.find_control.assert_not_called()

    def test_a_stop_during_a_pause_ends_the_wait_quietly(self):
        self.bot.stop_event.wait.side_effect = lambda seconds: self.clock.wait(seconds) or True
        for frame in (FRAME, None):
            self.bot.window.screenshot.return_value = frame
            for (name, (wait, miss)) in WAITS.items():
                with self.subTest(name, frame=frame is not None), self.assertNoLogs('BotCore', 'WARNING'):
                    self.assertEqual(wait(self.bot), miss)


class ImageWaitTests(WaitLoopTestCase):
    def test_the_first_frame_that_shows_the_template_ends_the_wait(self):
        self.bot.vision.find_control.side_effect = [MISS, MISS, (10, 20)]
        self.assertEqual(self.bot._wait_for_image('x.png', region=(1, 2, 3, 4), threshold=0.7), (10, 20))
        self.assertEqual(self.clock.pauses, [0.5, 0.5])
        # the button's label is read too once a second has gone by
        self.assertEqual(self.bot.vision.find_control.call_args_list,
                         [call(FRAME, 'x.png', threshold=0.7, region=(1, 2, 3, 4), ocr=ocr) for ocr in (False, False, True)])

    def test_the_label_read_counts_the_reward_check(self):
        self.bot._battle_rewards.handle.side_effect = self.slow(False, 1.2)
        self.bot.vision.find_control.return_value = (10, 20)
        self.bot._wait_for_image('x.png')
        self.assertIs(self.bot.vision.find_control.call_args.kwargs['ocr'], True)

    def test_the_frame_size_is_set_before_the_look(self):
        order = []
        self.bot._update_config_size.side_effect = lambda frame: order.append('size')
        self.bot.vision.find_control.side_effect = lambda *args, **kwargs: order.append('look') or (10, 20)
        self.bot._wait_for_image('x.png')
        self.assertEqual(order, ['size', 'look'])

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

    def test_the_label_read_counts_the_reward_check(self):
        self.bot._battle_rewards.handle.side_effect = self.slow(False, 1.2)
        self.bot.vision.find_control.return_value = (10, 20)
        self.bot._wait_for_any_image(['a.png'])
        self.assertIs(self.bot.vision.find_control.call_args.kwargs['ocr'], True)

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

    def test_no_warning_without_error(self):
        with self.assertNoLogs('BotCore', 'WARNING'):
            self.assertEqual(self.bot._wait_for_any_image(['a.png'], timeout=1, error=False), MISS)


class PlayerNameWaitTests(WaitLoopTestCase):
    def test_a_miss_scrolls_the_list_and_pauses(self):
        self.bot.vision.find_word_match.side_effect = [NO_NAME, ((30, 40), True, (4, 0))]
        self.assertEqual(self.bot._wait_for_player_name('Farm_1', match_alnum_only=True), (30, 40))
        self.bot._scroll_player_list_with_drag.assert_called_once_with(FRAME, up=True)
        self.assertEqual(self.clock.pauses, [0.45])
        self.assertEqual(self.bot.vision.find_word_match.call_args, call(FRAME, 'Farm_1', region=RIGHT_HALF, match_alnum_only=True))

    def test_an_explicit_region_is_read_instead(self):
        self.bot.vision.find_word_match.return_value = ((30, 40), True, (4, 0))
        self.bot._wait_for_player_name('Farm_1', region=(1, 2, 3, 4))
        self.assertEqual(self.bot.vision.find_word_match.call_args.kwargs['region'], (1, 2, 3, 4))

    def test_the_name_itself_beats_a_near_one_on_screen_before_it(self):
        # "KingRob" on screen, "KingBob" one scroll further down: the near name is never tapped
        self.bot.vision.find_word_match.side_effect = [((30, 40), False, (0, 0)), ((60, 80), True, (4, 0))]
        self.assertEqual(self.bot._wait_for_player_name('KingBob'), (60, 80))
        self.bot._scroll_player_list_with_drag.assert_called_once_with(FRAME, up=True)

    def test_a_near_name_once_the_list_was_read_through(self):
        # the name never reads as itself (a level badge read into it): taken once the list
        # reads the same after two scrolls, its end
        self.bot.vision.find_word_match.return_value = ((30, 40), False, NEAR)
        self.bot.vision.find_words_ocr.side_effect = lambda frame, region: [Mock(text='12Bob'), Mock(text='KingBob')]
        self.assertEqual(self.bot._wait_for_player_name('Bob'), (30, 40))
        self.assertEqual(self.bot._scroll_player_list_with_drag.call_count, 2)

    def test_the_list_is_read_back_for_a_near_name_seen_earlier(self):
        near = ((30, 40), False, NEAR)
        self.bot.vision.find_word_match.side_effect = [near] + [NO_NAME] * 3 + [near]
        rows = iter([['a'], ['b'], ['b'], ['b'], ['a']])  # it scrolls, then reads the same: the end
        self.bot.vision.find_words_ocr.side_effect = lambda frame, region: [Mock(text=t) for t in next(rows)]
        self.assertEqual(self.bot._wait_for_player_name('KingBob'), (30, 40))
        self.assertEqual([c.kwargs['up'] for c in self.bot._scroll_player_list_with_drag.call_args_list], [True, True, True, False])

    def test_a_near_name_after_half_the_time_on_a_moving_list(self):
        self.bot.vision.find_word_match.return_value = ((30, 40), False, NEAR)  # the list moves every time (setUp)
        self.assertEqual(self.bot._wait_for_player_name('KingBob', timeout=2), (30, 40))
        self.assertGreaterEqual(sum(self.clock.pauses), 1.0)  # not before half the time

    def test_the_nearest_name_of_the_whole_list_is_taken(self):
        # "Bob" looked for: "12Bob" (a badge read into it, the nearest) on the first screen,
        # "KingBob" at the end of the list: the list is read back up to "12Bob"
        badge = ((30, 40), False, (3, -2))
        king = ((60, 80), False, (3, -4))
        self.bot.vision.find_word_match.side_effect = [badge, NO_NAME, king, king, king, NO_NAME, badge]
        rows = iter([['12Bob'], ['Ann'], ['KingBob'], ['KingBob'], ['KingBob'], ['Ann'], ['12Bob']])
        self.bot.vision.find_words_ocr.side_effect = lambda frame, region: [Mock(text=t) for t in next(rows)]
        self.assertEqual(self.bot._wait_for_player_name('Bob'), (30, 40))

    def test_a_list_still_loading_is_not_its_end(self):
        # three empty reads, then a near name, the name itself one scroll down: never the near one
        self.bot.vision.find_word_match.side_effect = [NO_NAME] * 3 + [((30, 40), False, NEAR), ((60, 80), True, (4, 0))]
        rows = iter([[], [], [], ['KingRob'], ['KingBob']])
        self.bot.vision.find_words_ocr.side_effect = lambda frame, region: [Mock(text=t) for t in next(rows)]
        self.assertEqual(self.bot._wait_for_player_name('KingBob'), (60, 80))

    def test_a_near_name_on_screen_is_no_login_prompt(self):
        # the prompt is looked for only when no name at all is read
        self.bot.vision.find_word_match.return_value = ((30, 40), False, NEAR)
        self.bot._frame_shows_supercell_login_prompt.return_value = True
        self.assertEqual(self.bot._wait_for_player_name('KingBob', timeout=2), (30, 40))

    def test_nothing_near_the_list_is_read_on_down_to_the_end(self):
        # no near name in half the time, a still screen (Settings while the list loads): the
        # list is read on down, never back up, until the time out
        self.bot.vision.find_words_ocr.side_effect = lambda frame, region: [Mock(text='Settings')]
        self.assertEqual(self.bot._wait_for_player_name('KingBob', timeout=3, error=False), MISS)
        self.assertTrue(all(c.kwargs['up'] for c in self.bot._scroll_player_list_with_drag.call_args_list))

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

    def ocr_after_popups(self, popups):
        """The label flag of the look after ``popups`` closed popups, 0.25 s each."""
        self.bot._dismiss_okay_or_exit_on_frame.side_effect = [True] * popups + [False]
        self.bot.vision.find_control.return_value = (100, 700)
        self.assertEqual(self.bot._wait_for_attack_with_nudge(), (100, 700))
        return self.bot.vision.find_control.call_args.kwargs['ocr']

    def test_the_label_is_not_read_before_a_second(self):
        self.assertIs(self.ocr_after_popups(3), False)  # 0.75 s

    def test_the_label_is_read_from_one_second_exactly(self):
        self.assertIs(self.ocr_after_popups(4), True)  # 1.0 s

    def test_the_label_read_counts_the_popup_scan(self):
        # the popup and live-battle scans take ~0.2 s at 1227x767, ~1.8 s at 2560x1600
        self.bot._dismiss_okay_or_exit_on_frame.side_effect = self.slow(False, 1.2)
        self.bot.vision.find_control.return_value = (100, 700)
        self.assertEqual(self.bot._wait_for_attack_with_nudge(), (100, 700))
        self.assertEqual(self.bot.vision.find_control.call_args, call(FRAME, 'attack.png', region=BOTTOM_HALF, ocr=True))

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


class ReturnHomeWaitTests(WaitLoopTestCase):
    def on_screen(self, **hits):
        """find_template answers from ``hits`` (template name without .png -> point)."""
        self.bot.vision.find_template.side_effect = lambda frame, name, **kw: hits.get(name[:-len('.png')], MISS)

    def looked_at(self):
        return [c.args[1] for c in self.bot.vision.find_template.call_args_list]

    def test_the_second_return_home_art_counts_on_16_10_only(self):
        self.on_screen(returnhome2=(640, 690), chestclaim=(600, 650))
        self.assertEqual(self.bot._wait_for_return_home_or_chest_claim(), ('return', 640, 690))
        self.assertEqual(self.looked_at(), ['returnhome.png', 'returnhome2.png'])
        self.bot.vision.find_template.reset_mock()
        self.bot.config.aspect_key = '16_9'
        self.assertEqual(self.bot._wait_for_return_home_or_chest_claim(), ('chest', 600, 650))
        self.assertEqual(self.looked_at(), ['returnhome.png', 'chestclaim.png'])

    def test_an_okay_on_the_way_is_tapped_twice_at_most_without_a_pause(self):
        self.on_screen(okay=(50, 60), returnhome=(640, 690))
        self.assertEqual(self.bot._wait_for_return_home_or_chest_claim(dismiss_okay=True), ('return', 640, 690))
        self.assertEqual(self.bot.input.click.call_args_list, [call(50, 60, pause=0.1)] * 2)
        self.assertEqual(self.clock.pauses, [])
        self.bot.input.click.reset_mock()
        self.bot._wait_for_return_home_or_chest_claim()  # not asked: no tap
        self.bot.input.click.assert_not_called()

    def test_no_okay_on_the_way_home_while_a_gem_shows(self):
        self.on_screen(okay=(50, 60), gemicon=(400, 400), returnhome=(640, 690))
        with self.assertLogs('BotCore', 'WARNING') as logs:
            self.assertEqual(self.bot._wait_for_return_home_or_chest_claim(dismiss_okay=True), ('return', 640, 690))
        self.bot.input.click.assert_not_called()
        self.assertIn('not pressing Okay', logs.output[0])

    def test_the_labels_are_read_after_a_second(self):
        self.bot.vision.find_label.side_effect = lambda frame, label, **kw: (630, 700) if label == 'Claim Reward' else MISS
        self.assertEqual(self.bot._wait_for_return_home_or_chest_claim(), ('chest', 630, 700))
        self.assertEqual(self.clock.pauses, [0.5, 0.5])
        self.assertEqual(self.bot.vision.find_label.call_args_list,
                         [call(FRAME, 'Return Home', region=BOTTOM_HALF), call(FRAME, 'Claim Reward', region=BOTTOM_HALF)])

    def test_the_label_read_counts_the_art_scans(self):
        self.bot.vision.find_template.side_effect = self.slow(MISS, 0.4)  # three scans: 1.2 s
        self.bot.vision.find_label.side_effect = lambda frame, label, **kw: (640, 690) if label == 'Return Home' else MISS
        self.assertEqual(self.bot._wait_for_return_home_or_chest_claim(), ('return', 640, 690))
        self.assertEqual(self.clock.pauses, [])

    def test_rewards_missing_frames_and_the_time_out(self):
        self.bot.window.screenshot.side_effect = [None] + [FRAME] * 10
        self.bot._battle_rewards.handle.side_effect = [True] + [False] * 10
        with self.assertLogs('BotCore', 'WARNING') as logs:
            self.assertEqual(self.bot._wait_for_return_home_or_chest_claim(timeout=1.5), MISS3)
        self.assertEqual(self.clock.pauses, [0.5, 0.5, 0.5])
        self.assertEqual(self.bot.window.screenshot.call_count, 4)  # the reward's frame is looked at again at once
        self.assertEqual(logs.output, ['WARNING:BotCore:Timeout waiting for returnhome.png / returnhome2.png (16:10) or chestclaim.png'])


class AccountListScrollTests(unittest.TestCase):
    def test_the_list_is_read_on_then_back(self):
        bot = bare_bot(FRAME)
        with patch('app.core.bot.random.randint', return_value=0), patch('app.core.bot.random.uniform', return_value=0.3):
            bot._scroll_player_list_with_drag(FRAME)
            bot._scroll_player_list_with_drag(FRAME, up=False)
        (down, up) = ([c.args for c in bot.input.mouse_down.call_args_list], [c.args for c in bot.input.mouse_up.call_args_list])
        self.assertGreater(down[0][1], up[0][1])  # dragged upward: the list reads on down
        self.assertEqual((down[1], up[1]), (up[0], down[0]))  # the same stroke the other way: back up
        self.assertTrue(all(0.5 * 767 <= y <= 0.9 * 767 for (_x, y) in down + up))  # on the list, clear of its header


if __name__ == '__main__':
    unittest.main()
