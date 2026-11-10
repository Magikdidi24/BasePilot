'''Tesseract calls for VisionService, in-process through tesserocr when it is installed.

pytesseract launches tesseract.exe and writes temp files on every read; tesserocr keeps
one engine loaded (measured 4-12x faster per read with the same Tesseract 5.5.3 and
identical output). Without tesserocr, or if its engine cannot start, every call goes to
pytesseract. Both paths return pytesseract's shapes, so callers do not care which ran.
'''
import os
import re
import threading

import pytesseract
from app.utils.logger import setup_logger

try:
    import tesserocr
except ImportError:  # optional speed-up
    tesserocr = None

logger = setup_logger('OcrBackend')
Output = pytesseract.Output
TesseractNotFoundError = pytesseract.TesseractNotFoundError

_PSM = re.compile(r'--psm\s+(\d+)')
_VAR = re.compile(r'-c\s+([A-Za-z0-9_]+)=(\S*)')
_TSV_HEADER = ('level', 'page_num', 'block_num', 'par_num', 'line_num', 'word_num', 'left', 'top', 'width', 'height', 'conf', 'text')
_local = threading.local()  # one engine per thread: a TessBaseAPI is not thread-safe
_disabled = tesserocr is None


def _engine():
    '''This thread's tesserocr engine, or None when it cannot start (then pytesseract runs).'''
    global _disabled
    if _disabled:
        return None
    api = getattr(_local, 'api', None)
    if api is None:
        prefix = os.environ.get('TESSDATA_PREFIX')  # set by configure_tesseract() to the bundled tessdata
        try:
            api = tesserocr.PyTessBaseAPI(lang = 'eng', **({'path': prefix} if prefix else {}))
        except RuntimeError as e:
            _disabled = True
            logger.warning('tesserocr could not start (%s); using pytesseract', e)
            return None
        _local.api = api
        logger.info('OCR: in-process tesserocr %s', tesserocr.__version__)
    return api


def _recognize(api, image, config, boxes = False):
    '''Apply a pytesseract-style config ("--psm N -c var=value") and run recognition.'''
    psm = _PSM.search(config or '')
    api.SetPageSegMode(int(psm.group(1)) if psm else tesserocr.PSM.AUTO)  # psm 3, the CLI default
    variables = dict(_VAR.findall(config or ''))
    # variables persist on the engine: always reset the whitelist, the one this app uses
    api.SetVariable('tessedit_char_whitelist', variables.pop('tessedit_char_whitelist', ''))
    for (name, value) in variables.items():
        api.SetVariable(name, value)
    # pytesseract's image_to_boxes runs the CLI with 'batch.nochop makebox'; mirror it (and
    # undo it for other reads: variables persist). Only matters with legacy tessdata models.
    nochop = '0' if boxes else '1'
    api.SetVariable('chop_enable', nochop)
    api.SetVariable('wordrec_enable_assoc', nochop)
    api.SetImage(image)
    # pytesseract hands the CLI a file without DPI, which then assumes 70 dpi: do the same so
    # both paths segment and read identically (otherwise the engine estimates a resolution)
    api.SetVariable('user_defined_dpi', '70')
    api.Recognize()


def _tsv_to_dict(tsv):
    '''pytesseract's Output.DICT from TSV rows: numeric columns as int(float(x)), text as str.'''
    data = {key: [] for key in _TSV_HEADER}
    text_col = len(_TSV_HEADER) - 1
    for line in tsv.split('\n'):
        if not line:
            continue
        cells = line.split('\t')
        cells += [''] * (len(_TSV_HEADER) - len(cells))
        for (i, key) in enumerate(_TSV_HEADER):
            value = cells[i]
            if i != text_col:
                try:
                    value = int(float(value))
                except ValueError:
                    pass
            data[key].append(value)
    return data


def image_to_data(image, output_type = None, config = ''):
    api = _engine() if output_type == Output.DICT else None  # the app only asks for DICT
    if api is None:
        return pytesseract.image_to_data(image, output_type = output_type, config = config)
    _recognize(api, image, config)
    return _tsv_to_dict(api.GetTSVText(0))


def image_to_boxes(image, config = ''):
    api = _engine()
    if api is None:
        return pytesseract.image_to_boxes(image, config = config)
    _recognize(api, image, config, boxes = True)
    return api.GetBoxText(0)


def image_to_tsv(image, config = ''):
    '''Debug dumps only: TSV text from the reference pytesseract path (it has no image_to_tsv).'''
    return pytesseract.image_to_data(image, config = config)
