'''Manual game-window selection (JSON) under LOCALAPPDATA\\BasePilot.

Stores a stable identity (window title + top-level class + game-surface child class) so the
correct Google Play Games window can be re-resolved across restarts, even when the HWND changes
or auto-detection picks the wrong window.
'''
from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from app.utils.common import ensure_dir, get_user_app_data_dir
from app.utils.logger import setup_logger
logger = setup_logger('WindowSettings')
WINDOW_SELECTION_FILENAME = 'window.json'
_warned_unreadable = set()  # one warning per file: every WindowService re-reads the pin, every 30 s while the game is away

@dataclass
class WindowSelection:
    '''A user-pinned window identity. Empty fields mean "auto-detect".'''
    title: 'str' = ''
    top_class: 'str' = ''
    child_class: 'str' = ''
    
    def is_set(self):
        return bool(self.title.strip() or self.child_class.strip())



def get_window_selection_path():
    dest = get_user_app_data_dir() / WINDOW_SELECTION_FILENAME
    ensure_dir(dest.parent)
    return dest


def load_window_selection():
    path = get_window_selection_path()
    if not path.is_file():
        return WindowSelection()
    
    try:
        raw = json.loads(path.read_text(encoding = 'utf-8'))
        if not isinstance(raw, dict):
            return WindowSelection()
        return WindowSelection(title = str(raw.get('title', '') or ''), top_class = str(raw.get('top_class', '') or ''), child_class = str(raw.get('child_class', '') or ''))
    except (ValueError, OSError) as e:  # ValueError: not JSON (e.g. cut off mid-write) or not UTF-8
        if path not in _warned_unreadable:
            _warned_unreadable.add(path)
            logger.warning(f'''Ignoring unreadable game-window pin {path} ({e}); using auto-detect. Pick the window again in Settings → Game window.''')
        return WindowSelection()  # [recovered: returned None, which find_window dereferenced, so a truncated window.json made Start fail with no message]



def save_window_selection(selection):
    path = get_window_selection_path()
    path.parent.mkdir(parents = True, exist_ok = True)
    payload = asdict(selection)
    path.write_text(json.dumps(payload, indent = 2), encoding = 'utf-8')


def clear_window_selection():
    '''Remove any saved selection so auto-detection is used again.'''
    path = get_window_selection_path()
    
    try:
        path.unlink()
        return None
    except FileNotFoundError:
        
        try:
            return None
        except OSError:
            save_window_selection(WindowSelection())
            return None



