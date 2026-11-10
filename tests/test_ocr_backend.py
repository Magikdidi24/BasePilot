import os
import re
import shutil
import subprocess
import unittest

import cv2
import numpy as np

from app.services import ocr_backend
from app.services.vision import VisionService as V


def tessdata_prefix():
    if os.environ.get('TESSDATA_PREFIX'):
        return os.environ['TESSDATA_PREFIX']
    out = subprocess.run(['tesseract', '--list-langs'], capture_output=True, text=True).stdout
    m = re.search(r'"(.+?)"', out)
    return m.group(1) if m else None


@unittest.skipUnless(ocr_backend.tesserocr and shutil.which('tesseract'), 'needs tesserocr and the tesseract binary')
class TesserocrMatchesPytesseract(unittest.TestCase):
    """The in-process engine must read exactly what the pytesseract CLI path reads."""

    def setUp(self):
        os.environ.setdefault('TESSDATA_PREFIX', tessdata_prefix() or '')
        self.saved = ocr_backend._disabled

    def tearDown(self):
        ocr_backend._disabled = self.saved

    def reads(self, frame):
        h, w = frame.shape[:2]
        words = V.find_words_ocr(frame, (0, h // 2, w, h - h // 2), white_text=True, roi_upscale=2)
        chars = V.find_chars_ocr(frame, (0, h // 2, w, h - h // 2), white_text=True, tesseract_config=V._TESSERACT_NUMBERS_HUD) or []
        return [(b.text, b.left, b.top, b.width, b.height, b.confidence) for b in words], [str(c) for c in chars]

    def test_same_words_boxes_and_confidences(self):
        frame = cv2.imread('docs/basepilot-screenshot.png')
        ocr_backend._disabled = True
        cli = self.reads(frame)
        ocr_backend._disabled = False
        self.assertEqual(self.reads(frame), cli)
        self.assertIsNotNone(ocr_backend._engine())  # the in-process engine actually ran
