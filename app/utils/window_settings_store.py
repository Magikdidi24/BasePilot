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

    def matches(self, window):
        '''True when ``window`` (its ``title`` and ``top_class``) may be the pinned one: the
        same title, case and outer spaces aside (any title when none was saved), and the
        same class when one was saved. Nothing matches a selection that is not set.'''
        if not self.is_set():
            return False
        title = self.title.strip().lower()
        if title and window.title.strip().lower() != title:
            return False
        return not self.top_class or window.top_class == self.top_class



def get_window_selection_path():
    dest = get_user_app_data_dir() / WINDOW_SELECTION_FILENAME
    ensure_dir(dest.parent)
    return dest


def load_window_selection():
    path = get_window_selection_path()
    if not path.is_file():
        return WindowSelection()
    
    try:
        raw = json.loads(path.read_text(encoding = 'utf-8-sig'))  # -sig: Notepad's UTF-8 with BOM too
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





HIDDEN_WINDOW_FILENAME = 'hidden_window.json'


def _hidden_window_path():
    return get_user_app_data_dir() / HIDDEN_WINDOW_FILENAME


def save_hidden_home(rect, hwnd = 0, top_class = ''):
    '''Where the game window was before Hide game moved it off the desktop (left, top,
    right, bottom, as a window placement counts them), and the window itself (``hwnd``,
    ``top_class``): it comes back even when the game surface cannot be found again. On
    disk, so a BasePilot that closed without showing it still can.'''
    path = _hidden_window_path()
    ensure_dir(path.parent)
    record = {'home': [int(v) for v in rect], 'hwnd': int(hwnd or 0), 'class': str(top_class or '')}
    path.write_text(json.dumps(record), encoding = 'utf-8')


def _hidden_record():
    '''The saved record ({} when unreadable), or None when the game is not hidden.'''
    path = _hidden_window_path()
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding = 'utf-8-sig'))
    except (ValueError, OSError):
        return {}
    return record if isinstance(record, dict) else {}


def load_hidden_home():
    '''The saved place of a hidden game window, or None (not hidden, or unreadable).'''
    home = (_hidden_record() or {}).get('home')
    if isinstance(home, list) and len(home) == 4 and all(isinstance(v, int) for v in home):
        return tuple(home)
    return None


def load_hidden_window():
    '''``(hwnd, top_class)`` of the hidden game window, ``(0, '')`` when unknown.'''
    record = _hidden_record() or {}
    hwnd = record.get('hwnd')
    return (hwnd if isinstance(hwnd, int) else 0, str(record.get('class') or ''))


def is_game_hidden():
    '''True while a hidden game window's place is saved (cheap: the UI asks every second).'''
    return _hidden_window_path().is_file()


def forget_hidden_home():
    try:
        _hidden_window_path().unlink()
    except FileNotFoundError:
        pass
