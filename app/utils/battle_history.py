'''Every battle the bot played, a line of JSON each in ``battles.jsonl`` (the user's data
dir): what the Stats page shows, and what the Builder Base attack plans are learned from
(:mod:`app.core.bb_learning`). A record is a dict with at least ``t`` (ISO time, seconds)
and ``village`` ("home" or "builder"). Local only: nothing leaves the machine.
'''
import json
import threading
from datetime import datetime

from app.utils.common import get_user_app_data_dir
from app.utils.logger import setup_logger

logger = setup_logger('BattleHistory')

FILE_NAME = 'battles.jsonl'
_lock = threading.Lock()


def history_path():
    return get_user_app_data_dir() / FILE_NAME


def append(record, path = None):
    '''Add ``record`` (stamped with the time when it has none); never raises.'''
    entry = dict(record)
    entry.setdefault('t', datetime.now().isoformat(timespec = 'seconds'))
    try:
        target = path or history_path()
        target.parent.mkdir(parents = True, exist_ok = True)
        with _lock, open(target, 'a', encoding = 'utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii = False) + '\n')
    except OSError:
        logger.warning('Could not write the battle history', exc_info = True)
    return entry


def load(path = None):
    '''Every record, oldest first; unreadable lines are skipped.'''
    target = path or history_path()
    records = []
    try:
        with open(target, encoding = 'utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and 't' in entry:
                    records.append(entry)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning('Could not read the battle history', exc_info = True)
    return records
