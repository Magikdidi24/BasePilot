"""Debug frames: a frame the bot or the clan assistant could not make sense of goes to
debug/<prefix>_<unix time>.jpg in the data dir (here a temporary one); no frame, or a failed
write, gives None and never raises."""
import os
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.core import bot, clan

FRAME = np.full((40, 60, 3), 200, np.uint8)
DUMPERS = (('bot', bot._dump_debug_frame), ('clan', clan._dump_debug_frame))


class DebugFrameTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {'LOCALAPPDATA': folder.name, 'HOME': folder.name})  # never the user's data dir
        env.start()
        self.addCleanup(env.stop)

    def test_a_frame_goes_to_the_debug_dir_as_a_jpeg(self):
        for (name, dump) in DUMPERS:
            with self.subTest(name):
                path = dump(FRAME, 'probe')
                self.assertEqual((path.parent.name, path.name.split('_')[0], path.suffix), ('debug', 'probe', '.jpg'))
                self.assertEqual(cv2.imread(str(path)).shape, FRAME.shape)

    def test_no_frame_gives_no_file(self):
        for (name, dump) in DUMPERS:
            with self.subTest(name):
                self.assertIsNone(dump(None, 'probe'))

    def test_a_failed_write_gives_none(self):
        for (name, dump) in DUMPERS:
            with self.subTest(name), patch('cv2.imwrite', side_effect=OSError('disk full')):
                self.assertIsNone(dump(FRAME, 'probe'))


if __name__ == '__main__':
    unittest.main()
