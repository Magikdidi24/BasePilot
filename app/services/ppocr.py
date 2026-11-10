'''Line recognition with PaddleOCR's English PP-OCRv4 mobile model (Apache-2.0; the ONNX
export RapidOCR publishes), run by OpenCV's DNN module: no dependency besides OpenCV, about
30 ms per line on a CPU, read-only and offline.

Tesseract drops the narrow 1 of the game's digits at small window sizes (live 1227x767:
elixir "11 320 116" read 3206) and reads some 5 as 8; this model read every HUD line of
those frames right. It only reads a line: the caller cuts it out (no text detection here).
'''
import threading

import cv2
import numpy as np

from app.utils.common import get_resource_path
from app.utils.logger import setup_logger

logger = setup_logger('PPOCR')

MODEL = 'app/data/ocr/en_PP-OCRv4_rec_mobile.onnx'
CHARSET = 'app/data/ocr/en_dict.txt'
_HEIGHT = 48  # the model's input height
_local = threading.local()  # cv2.dnn nets are not thread-safe: one per thread
_charset = None
_unavailable = False


def _net():
    global _charset, _unavailable
    if _unavailable:
        return None
    net = getattr(_local, 'net', None)
    if net is None:
        try:
            net = cv2.dnn.readNetFromONNX(str(get_resource_path(MODEL)))
            if _charset is None:
                with open(get_resource_path(CHARSET), encoding = 'utf-8') as f:
                    chars = f.read().split('\n')[:-1]  # one per line; the last is a space
                _charset = [''] + chars + [' ']  # CTC blank first, the space class last
        except Exception:
            logger.warning('PP-OCR model unavailable — Tesseract reads the numbers instead', exc_info = True)
            _unavailable = True
            return None
        _local.net = net
    return net


def available():
    return _net() is not None


def read_line(bgr):
    '''The text of the one line in ``bgr`` (a colour crop around it), or None without the model.'''
    net = _net()
    if net is None or bgr is None or bgr.size == 0 or bgr.shape[0] < 4:
        return None
    width = max(16, int(round(bgr.shape[1] * _HEIGHT / bgr.shape[0])))
    rgb = cv2.resize(bgr, (width, _HEIGHT), interpolation = cv2.INTER_CUBIC)[:, :, ::-1].astype(np.float32)
    net.setInput(((rgb / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None])
    best = net.forward()[0].argmax(axis = 1)  # CTC, greedy: collapse repeats, drop blanks
    text = []
    previous = -1
    for i in best:
        if i != previous and 0 < i < len(_charset):
            text.append(_charset[i])
        previous = i
    return ''.join(text)
