'''Text reading with PaddleOCR's PP-OCRv6 (Apache-2.0; the ONNX exports RapidOCR publishes):
a text detector (``det_tiny``) finds the lines of text in an image, a line recognizer
(``rec_small``) reads each one. Both run on the CPU, by ONNX Runtime when it is installed,
else by OpenCV's DNN module (the same output, 2-3x slower). Offline and read-only.

It replaced Tesseract and the PP-OCRv4 English line model in November 2026. Measured on
1227x767 GPG frames: a line in 11 ms, the detector in 25 ms on half a frame; a label not
there looked up in 200 ms on half a frame and 440 ms on a whole one (Tesseract: 0.5 and
1.2 s), the reconnect-dialog check of every recovery pass in 40 ms. On 444 saved home frames
the HUD reads as v4 did on 441, better on 2, worse on 1 (Tesseract drops the narrow 1 of the
game's digits at small window sizes and reads some 5 as 8).

The recognizer reads a line as a sequence of time steps (CTC): each character comes with
the steps it was read on, which place it along the line. That gives the word and character
boxes the readers need, the way Tesseract's did.
'''
import os
import threading
from dataclasses import dataclass
from typing import Tuple

import cv2
import numpy as np

from app.utils.common import get_resource_path
from app.utils.logger import setup_logger

logger = setup_logger('PPOCR')

DET_MODEL = 'app/data/ocr/PP-OCRv6_det_tiny.onnx'
REC_MODEL = 'app/data/ocr/PP-OCRv6_rec_small.onnx'
CHARSET = 'app/data/ocr/PP-OCRv6_rec_small_dict.txt'
_REC_HEIGHT = 48  # the recognizer's input height
_DET_MEAN = np.array([0.485, 0.456, 0.406], np.float32)  # the detector's normalisation, on BGR as trained
_DET_STD = np.array([0.229, 0.224, 0.225], np.float32)
_DET_MAX_SIDE = 2048  # px: a bigger image is shrunk for the detector (time grows with the area)
_DET_THRESHOLD = 0.3  # text probability over which a pixel is text
_DET_BOX_SCORE = 0.5  # mean probability under which a blob of text is noise
_DET_UNCLIP = 1.6  # the detector marks a shrunk core of each line: grown back by area x this / perimeter
_DET_MIN_SIDE = 3  # px of the probability map: a thinner blob is noise
# The grown box is the recognizer's crop, 1.6-2x the glyphs' height (it reads better with a
# margin); the core is 0.7-0.9x it (live Build panel at 1227x767). A line reports the core
# grown by this share of its height on each side: about its glyphs, as Tesseract's boxes were.
_TEXT_PAD = 0.15
_THREADS = max(1, min(4, os.cpu_count() or 1))  # the game runs beside: not every core
_lock = threading.Lock()
_models = {}
_local = threading.local()  # OpenCV DNN nets are not thread-safe: one per thread
_charset = None
_unavailable = False


@dataclass(frozen = True)
class Char:
    '''A character read on a line: its text, its span along the line and its probability.'''
    text: str
    left: float
    right: float
    prob: float


@dataclass(frozen = True)
class Line:
    '''A line of text read in an image: its box ``(x0, y0, x1, y1)`` and its characters, the
    spaces between words included, in that image's coordinates.'''
    box: Tuple[int, int, int, int]
    chars: Tuple[Char, ...]

    @property
    def text(self):
        return ''.join(c.text for c in self.chars)


class _Model:
    '''One ONNX model, run by ONNX Runtime when it loads, else by OpenCV's DNN module.'''

    def __init__(self, path):
        self.path = path
        self.session = None
        try:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = _THREADS
            options.log_severity_level = 3
            self.session = ort.InferenceSession(path, options, providers = ['CPUExecutionProvider'])
            self.input = self.session.get_inputs()[0].name
            self.runtime = f'onnxruntime {ort.__version__}'
        except Exception as e:  # not installed, or its DLLs did not load
            logger.info('OCR: ONNX Runtime unavailable (%s) — OpenCV DNN runs the models', e)
            # the model's bytes, not its path: OpenCV cannot open a non-ASCII path on Windows
            self.onnx = np.fromfile(path, np.uint8)
            cv2.dnn.readNetFromONNX(self.onnx)  # raises now on a bad model, not at the first read
            self.runtime = f'OpenCV DNN {cv2.__version__}'

    def run(self, x):
        if self.session is not None:
            return self.session.run(None, {self.input: x})[0]
        nets = getattr(_local, 'nets', None)
        if nets is None:
            nets = _local.nets = {}
        net = nets.get(self.path)
        if net is None:
            net = nets[self.path] = cv2.dnn.readNetFromONNX(self.onnx)
        net.setInput(x)
        return net.forward()


def _model(name):
    '''The detector or the recognizer, loaded once; None when the models cannot load.'''
    global _charset, _unavailable
    if _unavailable:
        return None
    with _lock:
        if not _models:
            try:
                with open(get_resource_path(CHARSET), encoding = 'utf-8') as f:
                    chars = f.read().split('\n')[:-1]  # one per line
                _charset = [''] + chars + [' ']  # the CTC blank first, the space class last
                _models['det'] = _Model(str(get_resource_path(DET_MODEL)))
                _models['rec'] = _Model(str(get_resource_path(REC_MODEL)))
                logger.info('OCR: PP-OCRv6 (det tiny, rec small) on %s', _models['rec'].runtime)
            except Exception:
                logger.error('OCR models unavailable: nothing can be read on screen', exc_info = True)
                _models.clear()
                _unavailable = True
                return None
    return _models.get(name)


def available():
    return _model('rec') is not None


_allowed_cache = {}


def _allowed(allowed):
    '''Class indices a whitelist leaves to the decoder: its characters, the blank and the space.'''
    idx = _allowed_cache.get(allowed)
    if idx is None:
        wanted = set(allowed) | {' '}
        idx = _allowed_cache[allowed] = np.array([0] + [i for (i, c) in enumerate(_charset) if i and c in wanted], np.int64)
    return idx


def _recognize(bgr, allowed = None):
    '''The characters of the one line in ``bgr``, each spanning along its width.'''
    rec = _model('rec')
    if rec is None or bgr is None or bgr.size == 0 or bgr.shape[0] < 4 or bgr.shape[1] < 2:
        return ()
    (h, w) = bgr.shape[:2]
    width = max(16, int(round(w * _REC_HEIGHT / h)))
    img = cv2.resize(bgr, (width, _REC_HEIGHT), interpolation = cv2.INTER_CUBIC).astype(np.float32)
    probs = rec.run(((img / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None].copy())[0]
    if allowed:
        idx = _allowed(allowed)
        best = idx[probs[:, idx].argmax(axis = 1)]
    else:
        best = probs.argmax(axis = 1)
    conf = probs[np.arange(len(best)), best]
    step = w / float(len(best))  # px of the line per time step
    runs = []  # [class, first step, last step, probabilities]
    previous = 0
    for (t, k) in enumerate(best):
        if k and k == previous:
            runs[-1][2] = t
            runs[-1][3].append(float(conf[t]))
        elif k:
            runs.append([int(k), t, t, [float(conf[t])]])
        previous = k
    if not runs:
        return ()
    # A character is read on a step or two near its middle: its span runs halfway to its
    # neighbours, so the characters of a word touch and a space keeps its own width.
    centres = [(r[1] + r[2] + 1) / 2.0 * step for r in runs]
    pitch = float(np.median(np.diff(centres))) if len(centres) > 1 else 0.6 * h
    chars = []
    for (i, (k, _t0, _t1, p)) in enumerate(runs):
        left = (centres[i - 1] + centres[i]) / 2 if i else centres[i] - pitch / 2
        right = (centres[i] + centres[i + 1]) / 2 if i + 1 < len(runs) else centres[i] + pitch / 2
        chars.append(Char(_charset[k], max(0.0, left), min(float(w), right), float(np.mean(p))))
    return tuple(chars)


def read_line(bgr, allowed = None):
    '''The text of the one line in ``bgr`` (a colour crop around it), or None without the
    models. ``allowed``: the characters it may hold (with spaces).'''
    if not available():
        return None
    return ''.join(c.text for c in _recognize(bgr, allowed))


def detect(bgr):
    '''``(crop, text)`` boxes ``(x0, y0, x1, y1)`` of the lines of text in ``bgr``, top to
    bottom: the recognizer's crop, with a margin, and the text's own box.'''
    det = _model('det')
    if det is None or bgr is None or bgr.size == 0:
        return []
    (h, w) = bgr.shape[:2]
    scale = min(1.0, _DET_MAX_SIDE / float(max(h, w)))
    (sh, sw) = (max(1, int(round(h * scale))), max(1, int(round(w * scale))))
    img = cv2.resize(bgr, (sw, sh), interpolation = cv2.INTER_AREA) if scale < 1 else bgr
    (ph, pw) = ((sh + 31) // 32 * 32, (sw + 31) // 32 * 32)  # the detector wants sides in 32s
    pad = np.zeros((ph, pw, 3), np.uint8)
    pad[:sh, :sw] = img
    x = ((pad.astype(np.float32) / 255.0 - _DET_MEAN) / _DET_STD).transpose(2, 0, 1)[None].copy()
    prob = det.run(x)[0, 0][:sh, :sw]
    mask = (prob > _DET_THRESHOLD).astype(np.uint8)
    (n, labels, stats, _centroids) = cv2.connectedComponentsWithStats(mask, connectivity = 4)
    boxes = []
    for i in range(1, n):
        (bx, by, bw, bh, area) = (int(v) for v in stats[i])
        if min(bw, bh) < _DET_MIN_SIDE:
            continue
        if float(prob[by:by + bh, bx:bx + bw][labels[by:by + bh, bx:bx + bw] == i].mean()) < _DET_BOX_SCORE:
            continue
        (crop, text) = (area * _DET_UNCLIP / (2.0 * (bw + bh)), _TEXT_PAD * bh)
        boxes.append(tuple((max(0, int((bx - d) / scale)), max(0, int((by - d) / scale)),
                            min(w, int(np.ceil((bx + bw + d) / scale))), min(h, int(np.ceil((by + bh + d) / scale))))
                           for d in (crop, text)))
    return sorted(boxes, key = lambda b: (b[1][1], b[1][0]))


def read_lines(bgr, allowed = None, single_line = False):
    '''The lines of text in ``bgr``: found by the detector, or the whole image read as one
    line with ``single_line``. Characters left out by ``allowed`` are never read.'''
    if not available() or bgr is None or bgr.size == 0:
        return []
    (h, w) = bgr.shape[:2]
    boxes = [((0, 0, w, h), (0, 0, w, h))] if single_line else detect(bgr)
    lines = []
    for ((x0, y0, x1, y1), text_box) in boxes:
        chars = _recognize(bgr[y0:y1, x0:x1], allowed)
        if chars:
            lines.append(Line(text_box, tuple(Char(c.text, c.left + x0, c.right + x0, c.prob) for c in chars)))
    return lines


def words(line):
    '''``(text, left, right, prob)`` of each word of a :class:`Line` (split on spaces).'''
    out = []
    current = []
    for c in line.chars + (Char(' ', 0, 0, 0),):
        if c.text.strip():
            current.append(c)
        elif current:
            out.append((''.join(k.text for k in current), current[0].left, current[-1].right,
                        float(np.mean([k.prob for k in current]))))
            current = []
    return out
