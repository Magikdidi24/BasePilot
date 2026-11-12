"""Images under a folder with an accent: OpenCV's own file functions cannot open such a path on
Windows (cv2.imread gives None, cv2.imwrite False), and the exe unpacks its templates under the
user's folder, so a Windows user named with an accent had a bot that found no template."""
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.core import bot
from app.services import ppocr
from app.services.vision import VisionService
from app.utils.common import read_image

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'templates' / '16_10'


class AccentedFolderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / 'Jérôme données'
        self.folder.mkdir()

    def test_an_image_there_reads(self):
        path = self.folder / 'probe.png'
        path.write_bytes(cv2.imencode('.png', np.full((10, 12, 3), 90, np.uint8))[1].tobytes())
        self.assertEqual(read_image(path).shape, (10, 12, 3))
        self.assertEqual(read_image(path, cv2.IMREAD_GRAYSCALE).shape, (10, 12))

    def test_a_missing_or_broken_file_reads_as_none(self):
        self.assertIsNone(read_image(self.folder / 'missing.png'))
        (self.folder / 'broken.png').write_text('not an image', encoding='utf-8')
        self.assertIsNone(read_image(self.folder / 'broken.png'))
        (self.folder / 'empty.png').write_bytes(b'')
        self.assertIsNone(read_image(self.folder / 'empty.png'))

    def test_a_template_there_is_found(self):
        template = shutil.copy(TEMPLATES / 'build.png', self.folder / 'build.png')
        art = read_image(template)
        (h, w) = art.shape[:2]
        frame = np.zeros((h + 200, w + 300, 3), np.uint8)
        frame[120:120 + h, 200:200 + w] = art
        with patch('app.services.vision.get_template_path', return_value=Path(template)):
            self.assertEqual(VisionService.find_template(frame, 'build.png', scale_template=False), (200 + w // 2, 120 + h // 2))

    def test_a_debug_frame_is_written_there(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.folder), 'HOME': str(self.folder)}):
            path = bot._dump_debug_frame(np.full((40, 60, 3), 200, np.uint8), 'probe')
        self.assertIsNotNone(path)
        self.assertTrue(path.is_relative_to(self.folder))  # under the accented folder, never the real data dir
        self.assertEqual(read_image(path).shape, (40, 60, 3))

    def test_the_ocr_fallback_loads_its_model_there(self):
        model = shutil.copy(next((ROOT / 'app' / 'data' / 'ocr').glob('*det*.onnx')), self.folder / 'det.onnx')
        with patch.dict(sys.modules, {'onnxruntime': None}):  # ONNX Runtime does not load: OpenCV DNN runs it
            loaded = ppocr._Model(str(model))
        self.assertTrue(loaded.runtime.startswith('OpenCV DNN'), loaded.runtime)
        self.assertEqual(loaded.run(np.zeros((1, 3, 64, 64), np.float32)).shape, (1, 1, 64, 64))


class NoOpenCvFileCallTests(unittest.TestCase):
    """OpenCV's file functions stay out of app/: on Windows they cannot open a non-ASCII path,
    and the Linux CI, where they can, would not see one come back."""
    def test_images_and_models_go_through_python_file_reads(self):
        found = []
        for path in (ROOT / 'app').rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            for m in re.finditer(r'\b(imread\w*|imwrite\w*|imcount|VideoCapture|VideoWriter|FileStorage|readNet\w*)\((?!self\.onnx\))', text):
                found.append(f'{path.relative_to(ROOT)}: {m.group(0)}')
        self.assertEqual(found, [])


if __name__ == '__main__':
    unittest.main()
