"""How an attack ends once its troops are down (troop spam and Edrags alike): golden drags when
the event offers them, else the heroes then the spells, each on a fresh frame, a Stop between
them ending the attack. Characterisation tests: they describe what the strategies do."""
import unittest
from unittest.mock import Mock, call

import numpy as np

from app.core.strategies import EdragStrategy, TroopSpamStrategy

FRAME = np.zeros((1200, 1920, 3), np.uint8)


def strategy(kind, stop_after_heroes=False, golden=False):
    """A strategy whose troops always go down; ``steps`` records the end of the attack."""
    stop = Mock(**{'wait.return_value': False, 'is_set.return_value': False})
    window = Mock(**{'screenshot.return_value': FRAME})
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
    s.deploy_golden_drags_if_present = steps.golden
    steps.golden.return_value = golden
    s.deploy_heroes = steps.heroes
    s.deploy_spells = steps.spells
    if stop_after_heroes:
        steps.heroes.side_effect = lambda frame: stop.is_set.configure_mock(return_value=True)
    return (s, steps, stop)


class AttackFinishTests(unittest.TestCase):
    def test_heroes_then_spells_on_fresh_frames(self):
        for kind in ('spam', 'edrag'):
            with self.subTest(kind):
                (s, steps, stop) = strategy(kind)
                self.assertTrue(s.execute(FRAME))
                self.assertEqual(steps.mock_calls, [call.golden(FRAME, stop), call.heroes(FRAME), call.spells(FRAME)])

    def test_golden_drags_end_the_attack(self):
        for kind in ('spam', 'edrag'):
            with self.subTest(kind):
                (s, steps, stop) = strategy(kind, golden=True)
                self.assertTrue(s.execute(FRAME))
                self.assertEqual(steps.mock_calls, [call.golden(FRAME, stop)])

    def test_a_stop_after_the_heroes_keeps_the_spells(self):
        for kind in ('spam', 'edrag'):
            with self.subTest(kind):
                (s, steps, _stop) = strategy(kind, stop_after_heroes=True)
                self.assertTrue(s.execute(FRAME))
                self.assertEqual([c[0] for c in steps.mock_calls], ['golden', 'heroes'])

    def test_no_capture_after_the_troops_ends_the_attack(self):
        for kind in ('spam', 'edrag'):
            with self.subTest(kind):
                (s, steps, _stop) = strategy(kind)
                s.input.window_service.screenshot.return_value = None
                self.assertTrue(s.execute(FRAME))
                self.assertEqual(steps.mock_calls, [])

    def test_the_spam_drag_is_released_however_it_ends(self):
        (s, _steps, _stop) = strategy('spam')
        s.deploy_spells.side_effect = RuntimeError('boom')
        with self.assertRaises(RuntimeError):
            s.execute(FRAME)
        s.input.mouse_up.assert_called()


if __name__ == '__main__':
    unittest.main()
