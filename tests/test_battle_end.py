"""A Home Village raid is played while its loot comes in: the base's available loot read
during the battle, End Battle once it stops dropping, Surrender with no star and nothing
coming, and nothing tapped when the battle ends by itself."""
import itertools
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.config import Config
from app.services import ppocr
from app.core.loot_filter import read_enemy_loot
from tests.helpers import bare_bot

FIXTURES = Path(__file__).parent / 'fixtures'
FRAME = np.zeros((767, 1227, 3), np.uint8)


def make_bot(buttons):
    """``buttons(poll)``: the set of templates showing at that poll."""
    bot = bare_bot(FRAME)
    bot._update_config_size = Mock()
    bot.vision = Mock()
    polls = itertools.count()
    state = {'poll': 0}

    def screenshot():
        state['poll'] = next(polls)
        return FRAME
    bot.window.screenshot.side_effect = screenshot
    bot.vision.find_template.side_effect = lambda f, name, **kw: (600, 650) if name in buttons(state['poll']) else (None, None)
    bot.vision.find_control.return_value = (None, None)
    bot.clock = lambda: float(state['poll'])  # a second a poll
    return bot


def play(bot, reads):
    with patch('app.core.bot.time.monotonic', side_effect=bot.clock), \
            patch('app.core.bot.read_enemy_loot', side_effect=lambda f: reads.pop(0) if reads else None):
        bot._play_out_battle()
    return [c.args[:2] for c in bot.input.click.call_args_list]


class BattleEndTests(unittest.TestCase):
    def test_the_raid_goes_on_while_the_loot_drops(self):
        # a star early (End Battle shows), the loot keeps dropping for a while, then stops
        reads = [(900000 - 20000 * k, 800000 - 15000 * k, 8000) for k in range(20)] + [(520000, 515000, 8000)] * 40
        bot = make_bot(lambda poll: {'endbattle.png'})
        self.assertEqual(play(bot, reads), [(600, 650)])
        self.assertGreaterEqual(bot.window.screenshot.call_count, 20 + 12)  # not at the first star: 12 s after the last drop

    def test_a_misread_is_no_drop(self):
        # 735196 read 7093790 once (live), and a digit dropped: neither keeps the battle going
        reads = [(735196, 597951, 5639), (7093790, 597951, 5639), (73519, 597951, 5639)] + [(735196, 597951, 5639)] * 20
        bot = make_bot(lambda poll: {'endbattle.png'})
        play(bot, reads)
        self.assertLessEqual(bot.window.screenshot.call_count, 14)

    def test_a_battle_over_by_itself_taps_nothing(self):
        bot = make_bot(lambda poll: {'returnhome.png'} if poll >= 5 else {'surrender.png'})
        self.assertEqual(play(bot, [(900000 - 10000 * k, 800000, 8000) for k in range(10)]), [])

    def test_no_star_and_nothing_coming_surrenders_after_a_minute(self):
        bot = make_bot(lambda poll: {'surrender.png'})
        self.assertEqual(play(bot, [(900000, 800000, 8000)] * 100), [(600, 650)])
        self.assertGreaterEqual(bot.window.screenshot.call_count, 60)


@unittest.skipUnless(ppocr.available(), 'needs the OCR models in app/data/ocr')
class LootDuringBattleTests(unittest.TestCase):
    def test_the_available_loot_drops_as_the_storages_fall(self):
        # live 1227x767 raid, the panel below the defender's name (left out of the crops)
        want = {'start': (920388, 864274, 8397), 'raided': (694566, 538228, 5639)}
        for (name, loot) in want.items():
            frame = np.zeros((767, 1227, 3), np.uint8)
            crop = cv2.imread(str(FIXTURES / f'gpg767_hv_battle_loot_{name}.png'))
            frame[58:58 + crop.shape[0], 0:crop.shape[1]] = crop
            Config().set_target_size_from_frame(frame)
            self.assertEqual(read_enemy_loot(frame), loot, name)


if __name__ == '__main__':
    unittest.main()
