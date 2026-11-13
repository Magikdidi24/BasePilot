"""How an attack ends once its troops are down (troop spam and Edrags alike): the golden drags
if the bar has them, then the heroes on that frame, then the spells on a fresh capture; a Stop
or a failed capture skips the rest. Characterisation tests: they describe what the strategies
do. (deploy_golden_drags_if_present is True only when a Stop came during the golden drags.)"""
import unittest
from unittest.mock import Mock, call

from app.core.strategies import EdragStrategy, TroopSpamStrategy

# Sentinels: every reader of a frame is mocked, and a mismatch shows as a plain diff.
FRAME = object()  # the frame the attack starts on
FIRST = object()  # the capture once the troops are down, for the golden drags and the heroes
AFTER = object()  # the second capture, for the spells
KINDS = ('spam', 'edrag')


def strategy(kind, captures=(FIRST, AFTER), stop_after=None, stopped_in_golden=False):
    """A strategy whose troops always go down; ``steps`` records the end of the attack.
    ``stop_after`` names the step after which Stop is set ('troops' or 'heroes')."""
    stop = Mock(**{'wait.return_value': False, 'is_set.return_value': False})
    window = Mock(**{'screenshot.side_effect': list(captures)})
    input_service = Mock(window_service=window)
    vision = Mock(**{'find_template.return_value': (100, 1000)})
    config = Mock(aspect_key='16_10')
    if kind == 'spam':
        s = TroopSpamStrategy(input_service, vision, config, stop, 'valkyrie', 0.01)
    else:
        s = EdragStrategy(input_service, vision, config, stop)
    steps = Mock()
    s._sync_frame_size = Mock()
    s._reward_checkpoint = Mock(side_effect=lambda frame=None, selected=None: (frame if frame is not None else FRAME, False))
    s._point = Mock(return_value=(960, 600))
    s._expand_loc = Mock(side_effect=lambda x, y: (x, y))
    s._deploy_diamond_perimeter_troop = Mock(return_value=True)
    if stop_after == 'troops':
        input_service.mouse_up.side_effect = lambda *a, **k: stop.is_set.configure_mock(return_value=True)
        s._deploy_diamond_perimeter_troop.side_effect = lambda *a, **k: stop.is_set.configure_mock(return_value=True) or True
    s.deploy_golden_drags_if_present = steps.golden
    steps.golden.return_value = stopped_in_golden
    s.deploy_heroes = steps.heroes
    s.deploy_spells = steps.spells
    if stop_after == 'heroes':
        steps.heroes.side_effect = lambda frame: stop.is_set.configure_mock(return_value=True)
    return (s, steps, stop)


class AttackFinishTests(unittest.TestCase):
    def test_golden_drags_heroes_then_spells_on_a_fresh_capture(self):
        for kind in KINDS:
            with self.subTest(kind):
                (s, steps, stop) = strategy(kind)
                self.assertTrue(s.execute(FRAME))
                self.assertEqual(steps.mock_calls, [call.golden(FIRST, stop), call.heroes(FIRST), call.spells(AFTER)])

    def test_a_stop_during_the_golden_drags_ends_the_attack(self):
        for kind in KINDS:
            with self.subTest(kind):
                (s, steps, stop) = strategy(kind, stopped_in_golden=True)
                self.assertTrue(s.execute(FRAME))
                self.assertEqual(steps.mock_calls, [call.golden(FIRST, stop)])

    def test_a_stop_as_the_troops_end_captures_nothing(self):
        for kind in KINDS:
            with self.subTest(kind):
                (s, steps, _stop) = strategy(kind, stop_after='troops')
                self.assertTrue(s.execute(FRAME))
                self.assertEqual(steps.mock_calls, [])
                s.input.window_service.screenshot.assert_not_called()

    def test_a_stop_after_the_heroes_skips_the_spells(self):
        for kind in KINDS:
            with self.subTest(kind):
                (s, steps, _stop) = strategy(kind, stop_after='heroes')
                self.assertTrue(s.execute(FRAME))
                self.assertEqual([c[0] for c in steps.mock_calls], ['golden', 'heroes'])

    def test_no_capture_after_the_troops_ends_the_attack(self):
        for kind in KINDS:
            with self.subTest(kind):
                (s, steps, _stop) = strategy(kind, captures=(None,))
                self.assertTrue(s.execute(FRAME))
                self.assertEqual(steps.mock_calls, [])

    def test_no_second_capture_skips_the_spells(self):
        for kind in KINDS:
            with self.subTest(kind):
                (s, steps, _stop) = strategy(kind, captures=(FIRST, None))
                self.assertTrue(s.execute(FRAME))
                self.assertEqual([c[0] for c in steps.mock_calls], ['golden', 'heroes'])

    def test_the_spam_drag_is_released_however_it_ends(self):
        (s, _steps, _stop) = strategy('spam')
        releases = []
        s.deploy_spells.side_effect = lambda frame: releases.append(s.input.mouse_up.call_count) or 1 / 0
        with self.assertRaises(ZeroDivisionError):
            s.execute(FRAME)
        self.assertEqual((releases, s.input.mouse_up.call_count), ([1], 2))  # the drag's own release, then the finally's


if __name__ == '__main__':
    unittest.main()
