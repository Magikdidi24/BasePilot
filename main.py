'''Entry point for the BasePilot GUI.'''
from __future__ import annotations
import os
import sys
import threading
from multiprocessing import freeze_support

# Make the project root (which contains the `app` package) importable when run
# from source. When frozen by PyInstaller, the package is already on the path.
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

# `--profile NAME` before anything reads the data directory: it decides where settings,
# the game-window pin, captured templates, the log and debug frames live, so two copies
# of BasePilot can drive two clients at once without overwriting each other. Read from
# argv here rather than in the GUI parser because the very first import below already
# resolves the log path.
if '--profile' in sys.argv:
    try:
        os.environ['BASEPILOT_PROFILE'] = sys.argv[sys.argv.index('--profile') + 1]
    except IndexError:
        pass

from app.ui.qt.app import run_gui
from app.utils.logger import setup_logger
logger = setup_logger('Main')


def _load_ocr():
    '''Load the OCR models off the UI thread: the first read on screen does not wait for
    them, and the log says at once what runs them (or that they did not load).'''
    try:
        from app.services import ppocr
        ppocr.available()
    except Exception:
        logger.warning('OCR warm-up failed', exc_info = True)


def main():
    try:
        threading.Thread(target = _load_ocr, daemon = True, name = 'OcrWarmUp').start()
        try:
            from app.services.display import DisplayService
            DisplayService().restore_if_pending()
        except Exception:
            logger.warning('Display restore-if-pending check failed', exc_info = True)
        logger.info('Starting Application...')
        run_gui()
    except Exception as e:
        logger.critical(f'''Unhandled exception: {e}''', exc_info = True)
        sys.exit(1)


if __name__ == '__main__':
    freeze_support()
    main()
