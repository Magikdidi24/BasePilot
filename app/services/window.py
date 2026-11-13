import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
import numpy as np
import cv2
from app.utils.logger import setup_logger
from app.utils.window_settings_store import WindowSelection, forget_hidden_home, is_game_hidden, load_hidden_home, load_hidden_window, load_window_selection, save_hidden_home
logger = setup_logger('WindowService')
WM_LBUTTONDOWN = 513
WM_LBUTTONUP = 514
WM_MOUSEMOVE = 512
MK_LBUTTON = 1
WM_MOUSEWHEEL = 522
WHEEL_DELTA = 120
_CHILD_CLASS_PREFIX = 'CROSVM'
_MINIMIZED_COORD = -30000  # Windows parks minimized windows at (-32000, -32000)

_PW_RENDERFULLCONTENT = 2
GA_ROOT = 2
GA_ROOTOWNER = 3
SPI_GETWORKAREA = 0x0030
HWND_BOTTOM = 1
SW_SHOWNORMAL = 1
SW_SHOWMAXIMIZED = 3
SW_SHOWNOACTIVATE = 4
WPF_RESTORETOMAXIMIZED = 2
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
_SM_VIRTUAL_SCREEN = (76, 77, 78, 79)  # left, top, width, height of the desktop over every monitor
_HIDE_GAP = 200  # px between the desktop's right edge and a hidden game window
_HIDE_SLIVER = 8  # px of a minimized game window left on the desktop while Hide game restores it
_HIDDEN_FIND_EVERY = 10  # s between two looks for a game closed while hidden (all windows are walked)


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', ctypes.c_long),
        ('biHeight', ctypes.c_long),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', ctypes.c_long),
        ('biYPelsPerMeter', ctypes.c_long),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD)]


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ('length', wintypes.UINT),
        ('flags', wintypes.UINT),
        ('showCmd', wintypes.UINT),
        ('ptMinPosition', wintypes.POINT),
        ('ptMaxPosition', wintypes.POINT),
        ('rcNormalPosition', wintypes.RECT)]


def bgra_dib_to_bgr(buffer, width, height):
    '''Top-down 32-bit DIB bytes (B, G, R, A) to an OpenCV BGR frame, in one copy (it used to
    go bytes() -> PIL -> numpy -> cvtColor: 6-20 ms per frame at 1080p-1440p).'''
    return cv2.cvtColor(np.frombuffer(buffer, np.uint8).reshape(height, width, 4), cv2.COLOR_BGRA2BGR)


def off_desktop(rect, desktop):
    '''True when ``rect`` (left, top, right, bottom) has no pixel on ``desktop``.'''
    return rect[0] >= desktop[2] or rect[2] <= desktop[0] or rect[1] >= desktop[3] or rect[3] <= desktop[1]


@dataclass
class WindowCandidate:
    '''A visible top-level window plus its resolved Google Play Games game surface (if any).'''
    # [recovered from bytecode: decompiler collapsed these fields into the docstring]
    top_hwnd: int = 0
    title: str = ''
    top_class: str = ''
    child_hwnd: int = 0
    child_class: str = ''

    @property
    def is_game(self):
        '''True when this window exposes a CROSVM game surface we can capture.'''
        return self.child_hwnd != 0

    
    def to_selection(self):
        return WindowSelection(title = self.title, top_class = self.top_class, child_class = self.child_class)

    
    def display_label(self):
        title = self.title or '(no title)'
        if self.is_game:
            return f'''{title}  —  surface: {self.child_class}'''
        return f'''{title}  —  no game surface ({self.top_class})'''



@dataclass
class DescendantInfo:
    '''A single descendant window under a top-level window (for the Info diagnostics view).'''
    # [recovered from bytecode: decompiler collapsed these fields into the docstring]
    hwnd: int
    cls: str
    title: str
    width: int
    height: int
    depth: int
    is_surface: bool

    def display_label(self):
        indent = '    ' * self.depth
        marker = '[surface] ' if self.is_surface else ''
        size = f'''{self.width}x{self.height}''' if self.width and self.height else '—'
        title = f'''  "{self.title}"''' if self.title else ''
        return f'''{indent}{marker}{self.cls}  ({size})  hwnd={self.hwnd}{title}'''



class WindowService:
    '''Handles window finding and screenshot capture using Windows API.'''
    _TOP_LEVEL_CLASS_PREFIX = 'HwndWrapper'
    _minimized_logged: bool = False  # the "window is minimized" warning is logged once per run
    
    def __init__(self, window_name = 'Clash of Clans', child_class = 'CROSVM_1'):
        self.window_name = window_name
        self.child_class = child_class
        self.hwnd = 0
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            self.find_window()
            return None
        except Exception:
            self.user32.SetProcessDPIAware()


    
    def _ensure_hwnd(self):
        '''True when ``self.hwnd`` is a live window. A missing or dead handle (game or Play
        Games restarted) is re-resolved, at most every 30 s so a closed game does not flood
        the log. (The decompiled guard this replaces returned None exactly when the lookup
        succeeded, and never re-resolved a stale non-zero handle.)'''
        if self.hwnd and self.user32.IsWindow(self.hwnd):
            return True
        now = time.monotonic()
        if now < getattr(self, '_next_find_at', 0):
            return False
        self._next_find_at = now + 30
        selection = load_window_selection()
        if selection is not None and selection.is_set():
            # Only the pinned window may come back: auto-detect could pick another client
            # (two profiles, two games) and send it this bot's clicks.
            self.hwnd = self._resolve_hwnd(selection)
            if self.hwnd:
                logger.info(f'''Pinned game window re-attached (HWND: {self.hwnd})''')
            return bool(self.hwnd)
        return self.find_window()

    def find_window(self):
        '''
Resolve the game-surface HWND.

Honors a user-pinned selection (Settings → Game window) first; otherwise falls back to
auto-detection (Google Play Games window with a ``CROSVM*`` child surface).
'''
        selection = load_window_selection()
        self.hwnd = self._resolve_hwnd(selection)
        if self.hwnd:
            how = 'pinned selection' if selection.is_set() else 'auto-detect'
            logger.info(f'''Window found via {how} (HWND: {self.hwnd})''')
            return True
        if selection.is_set():
            logger.warning(f'''Pinned game window not found (title={selection.title!r}, child={selection.child_class!r}); falling back to auto-detect.''')
            self.hwnd = self._auto_detect_child()
            if self.hwnd:
                logger.info(f'''Window found via auto-detect fallback (HWND: {self.hwnd})''')
                return True
        logger.warning(f'''Window not found: {self.window_name} (expect a titled window with a {_CHILD_CLASS_PREFIX!r}* surface, either as the top-level window itself or a descendant — Google Play Games). Open Settings → Game window to pick it manually.''')
        return False

    
    def _get_class(self, hwnd):
        buf = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    
    def _get_title(self, hwnd):
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ''
        buff = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value

    
    def _find_descendant(self, root_hwnd, predicate):
        '''Depth-first search for the first descendant whose class satisfies ``predicate``.'''
        EnumChildWindows = self.user32.EnumChildWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        found = {
            'hwnd': 0,
            'class': '' }
        
        def enum_child_cb(child_hwnd, lParam):
            cls = self._get_class(child_hwnd)
            if predicate(cls):
                found['hwnd'] = child_hwnd
                found['class'] = cls
                return False
            EnumChildWindows(child_hwnd, EnumWindowsProc(enum_child_cb), 0)
            return True

        EnumChildWindows(root_hwnd, EnumWindowsProc(enum_child_cb), 0)
        return (found['hwnd'], found['class'])

    
    def _find_crosvm_descendant(self, root_hwnd, preferred_class = ''):
        '''Resolve a game-surface child: exact ``preferred_class`` first, then any ``CROSVM*``.'''
        if preferred_class:
            (hwnd, cls) = self._find_descendant(root_hwnd, (lambda c: c == preferred_class))
            if hwnd:
                return (hwnd, cls)
        return self._find_descendant(root_hwnd, (lambda c: c.upper().startswith(_CHILD_CLASS_PREFIX)))

    
    def _resolve_surface(self, top_hwnd, top_class, preferred_class = ''):
        '''Resolve the game surface for a top-level window.

Google Play Games window topology varies across machines/builds:
- Some have an outer ``HwndWrapper`` shell with a ``CROSVM*`` **descendant** (capture that).
- Others expose ``CROSVM*`` as the **top-level window itself** (no wrapper); capture it directly.

Returns ``(surface_hwnd, surface_class)`` or ``(0, "")`` when no surface is present.
'''
        (hwnd, cls) = self._find_crosvm_descendant(top_hwnd, preferred_class)
        if hwnd:
            return (hwnd, cls)
        if top_class.upper().startswith(_CHILD_CLASS_PREFIX):
            return (top_hwnd, top_class)
        return (0, '')

    
    def enumerate_windows(self):
        '''List visible, titled top-level windows with their resolved game surface (if any).

Used by the Settings picker so users can choose the right window when auto-detection
fails. Candidates with a CROSVM surface are sorted first.
'''
        EnumWindows = self.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        IsWindowVisible = self.user32.IsWindowVisible
        candidates = []
        
        def enum_top_cb(hwnd, lParam):
            if IsWindowVisible(hwnd):
                title = self._get_title(hwnd)
                if title:
                    top_class = self._get_class(hwnd)
                    (child_hwnd, child_class) = self._resolve_surface(hwnd, top_class)
                    candidates.append(WindowCandidate(top_hwnd = hwnd, title = title, top_class = top_class, child_hwnd = child_hwnd, child_class = child_class))
            return True

        EnumWindows(EnumWindowsProc(enum_top_cb), 0)
        candidates.sort(key = (lambda c: (not (c.is_game), c.title.lower())))
        return candidates

    
    def enumerate_descendants(self, root_hwnd):
        '''All descendant windows of ``root_hwnd`` (class, title, size, depth) for diagnostics.'''
        EnumChildWindows = self.user32.EnumChildWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        results = []
        seen = set()
        
        def walk(parent_hwnd, depth):
            
            def cb(child_hwnd, lParam):
                if child_hwnd not in seen:
                    seen.add(child_hwnd)
                    cls = self._get_class(child_hwnd)
                    size = self.window_pixel_size(child_hwnd)
                    results.append(DescendantInfo(hwnd = child_hwnd, cls = cls, title = self._get_title(child_hwnd), width = size[0] if size else 0, height = size[1] if size else 0, depth = depth, is_surface = cls.upper().startswith(_CHILD_CLASS_PREFIX)))
                    walk(child_hwnd, depth + 1)
                return True

            EnumChildWindows(parent_hwnd, EnumWindowsProc(cb), 0)

        walk(root_hwnd, 0)
        return results

    
    def window_pixel_size(self, hwnd):
        '''Outer pixel size of any HWND via ``GetWindowRect`` (same basis as :meth:`screenshot`).'''
        if not hwnd:
            return None

        try:
            rect = wintypes.RECT()
            self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w <= 0 or h <= 0:
                return None
            return (int(w), int(h))
        except Exception:
            return None


    def _resolve_hwnd(self, selection, quiet = False):
        '''Resolve the game-surface HWND from a pinned selection, or auto-detect when unset.
        ``quiet``: no warning about two matching windows (a check that runs again and again).'''
        if not selection.is_set():
            return self._auto_detect_child()
        surfaces = []
        for cand in self.enumerate_windows():
            if not selection.matches(cand):
                continue
            (surface_hwnd, _) = self._resolve_surface(cand.top_hwnd, cand.top_class, selection.child_class)
            if not surface_hwnd:
                continue
            surfaces.append(surface_hwnd)
        if not surfaces:
            return 0
        if len(surfaces) > 1 and not quiet:
            # Two emulator windows with the same title cannot be told apart by a pin that
            # only records title and class, and two BasePilot profiles would then both
            # drive the first one. Say so rather than picking silently.
            logger.warning('%d windows match the pinned selection %r — using the first (HWND %s). Give the clients different window titles to run them side by side.',
                           len(surfaces), selection.title, surfaces[0])
        return surfaces[0]

    
    def _auto_detect_child(self):
        """Default Google Play Games detection: a 'Clash of Clans' window with a CROSVM surface.

The surface may be a descendant (under an ``HwndWrapper`` shell) or the top-level window
itself. The CROSVM requirement alone excludes Chromium hosts (Discord, Chrome) that merely
share the title substring, so no outer-class gate is needed.
"""
        name = self.window_name.lower()
        for cand in self.enumerate_windows():
            if not cand.is_game:
                continue
            if name and name not in cand.title.lower():
                continue
            return cand.child_hwnd
        return 0

    
    def get_outer_pixel_size(self):
        '''
Outer window size in pixels (``GetWindowRect``), same basis as :meth:`screenshot`.
'''
        if not self._ensure_hwnd():
            return None
        
        try:
            rect = wintypes.RECT()
            self.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w <= 0 or h <= 0:
                return None
            return (int(w), int(h))
        except Exception:
            return None


    
    def is_minimized(self):
        '''True when the game window is minimized (its own window or a parent).

        Windows parks a minimized window at (-32000, -32000); Google Play Games nests the
        game surface in a wrapper, so the surface itself can report not-iconic while its
        parent is. Measured live: minimized captures come back pure black while clicks
        still reach the game, which is the worst possible combination — the bot cannot
        see what it is clicking.
        '''
        try:
            hwnd = self.hwnd
            while hwnd:
                if self.user32.IsIconic(hwnd):
                    return True
                rect = wintypes.RECT()
                self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                if rect.left <= _MINIMIZED_COORD and rect.top <= _MINIMIZED_COORD:
                    return True
                hwnd = self.user32.GetParent(hwnd)
            return False
        except Exception:
            return False

    def _print_window(self, width, height):
        '''PrintWindow into a 32-bit DIB. Every GDI handle is released on every path: one
        leaked per frame exhausts the process's 10k GDI objects during a multi-day run.'''
        hwnd_dc = self.user32.GetWindowDC(self.hwnd)
        mem_dc = self.gdi32.CreateCompatibleDC(hwnd_dc)
        hbitmap = self.gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
        previous = self.gdi32.SelectObject(mem_dc, hbitmap)
        try:
            if not self.user32.PrintWindow(self.hwnd, mem_dc, _PW_RENDERFULLCONTENT):
                return None  # a failed capture is not a (black) frame
            bmi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0)  # top-down, BI_RGB
            buffer = (ctypes.c_ubyte * (width * height * 4))()
            if not self.gdi32.GetDIBits(hwnd_dc, hbitmap, 0, height, ctypes.byref(buffer), ctypes.byref(bmi), 0):
                return None
            return bgra_dib_to_bgr(buffer, width, height)
        finally:
            self.gdi32.SelectObject(mem_dc, previous)  # DeleteObject refuses a bitmap still selected into a DC
            self.gdi32.DeleteObject(hbitmap)
            self.gdi32.DeleteDC(mem_dc)
            self.user32.ReleaseDC(self.hwnd, hwnd_dc)

    def screenshot(self):
        '''Captures a screenshot of the window.

        Returns None when the window is minimized or renders nothing: a black frame
        matches no template and reads no text, so acting on one means clicking blind.
        '''
        if not self._ensure_hwnd():
            return None
        if self.is_minimized():
            if not WindowService._minimized_logged:
                WindowService._minimized_logged = True
                logger.warning('Game window is minimized — capture is blank while it stays that way. Restore the Clash of Clans window (it may sit behind other windows, just not minimized), or use Hide game on the Run page to keep it out of the way. Logged once per run.')
            return None
        WindowService._minimized_logged = False
        
        try:
            rect = wintypes.RECT()
            self.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width <= 0 or height <= 0:
                return None
            return self._print_window(width, height)
        except Exception as e:
            logger.error(f'''Screenshot failed: {e}''')
            return None

    # Hide game. Minimized, the game surface captures black: the bot cannot see it, and the
    # game left without input drops its connection. Restored but off the desktop, Google
    # Play Games keeps drawing it, PrintWindow keeps capturing it and the taps still land
    # (measured live on 14/11/2026: a Builder Base battle went on, its abilities fired once
    # each, with the window off-screen), and the desktop is free for other work.

    def _game_top_window(self, quiet = False):
        '''The Google Play Games window around the game surface (0: none): the one Hide game
        moved while it is still there, without finding the game surface again. ``quiet``: no
        "not found" in the log (the UI looks every second while the game is hidden).'''
        (saved, saved_class) = load_hidden_window()
        if saved and self.user32.IsWindow(saved) and self._get_class(saved) == saved_class:
            return saved
        if quiet:
            now = time.monotonic()
            if now < getattr(self, '_next_hidden_find', 0):
                return 0
            self._next_hidden_find = now + _HIDDEN_FIND_EVERY
            surface = self._resolve_hwnd(load_window_selection(), quiet = True)
        else:
            surface = self.hwnd if self._ensure_hwnd() else 0
        return (self.user32.GetAncestor(surface, GA_ROOT) or surface) if surface else 0

    def _rect(self, hwnd):
        rect = wintypes.RECT()
        self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return (rect.left, rect.top, rect.right, rect.bottom)

    def _desktop(self):
        (x, y, w, h) = (self.user32.GetSystemMetrics(i) for i in _SM_VIRTUAL_SCREEN)
        return (x, y, x + w, y + h)

    def _workspace_origin(self):
        '''Where window placements count from on the screen: the corner of the main
        screen's work area (a taskbar on the left or at the top moves it).'''
        work = wintypes.RECT()
        if not self.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0):
            return (0, 0)
        return (work.left, work.top)

    def _placement(self, hwnd):
        wp = _WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(_WINDOWPLACEMENT)
        return wp if self.user32.GetWindowPlacement(hwnd, ctypes.byref(wp)) else None

    def _save_home(self, top, place):
        save_hidden_home((place.left, place.top, place.right, place.bottom), top, self._get_class(top))

    def hide_game(self):
        '''Move the game window off the desktop, restored, to the bottom of the window stack
        (the last window Windows activates when another one closes). Its place is saved for
        :meth:`show_game`. Returns '' once hidden, else why it was not.'''
        top = self._game_top_window()
        if not top:
            return 'Game window not found.'
        wp = self._placement(top)
        if wp is None:
            return 'Could not read the game window.'
        iconic = bool(self.user32.IsIconic(top))
        if wp.showCmd == SW_SHOWMAXIMIZED or (iconic and wp.flags & WPF_RESTORETOMAXIMIZED):
            return 'The game window is maximized: make it a window again first.'
        normal = wp.rcNormalPosition
        size = (normal.right - normal.left, normal.bottom - normal.top)
        (desktop, rect) = (self._desktop(), self._rect(top))
        if not iconic:
            if (rect[2] - rect[0], rect[3] - rect[1]) != size:
                # snapped to a side or a corner: its restore place is not where it is
                return 'The game window is snapped to the side of the screen: drag it free first.'
            if off_desktop(rect, desktop):
                if load_hidden_home() is None:  # off the desktop with nothing to bring it back: now there is
                    self._save_home(top, normal)
                return ''
            self._save_home(top, normal)
        elif load_hidden_home() is None:
            self._save_home(top, normal)
        # else minimized while hidden (Show desktop): its restore place is off the desktop, the saved one stays
        (ox, oy) = self._workspace_origin()
        if iconic:
            # SetWindowPlacement pulls a place wholly off the desktop back onto it: restore the
            # window with a sliver on screen, then slide it out.
            left = desktop[2] - _HIDE_SLIVER - ox
            (wp.showCmd, wp.rcNormalPosition) = (SW_SHOWNOACTIVATE, wintypes.RECT(left, normal.top, left + size[0], normal.top + size[1]))
            self.user32.SetWindowPlacement(top, ctypes.byref(wp))
        self.user32.SetWindowPos(top, HWND_BOTTOM, desktop[2] + _HIDE_GAP, normal.top + oy, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        rect = self._rect(top)
        if off_desktop(rect, desktop) and (rect[2] - rect[0], rect[3] - rect[1]) == size:
            logger.info('Game window hidden off the desktop at %s: it keeps running (Show game, or its taskbar button, brings it back)', rect[:2])
            return ''
        self.show_game()
        if not off_desktop(rect, desktop):
            return 'The game window did not move off the screen.'
        # past a screen of another scale, Windows resizes the window: the capture would change size
        return 'The game window changed size off the desktop: the screen on the right has another scale. Move the game to the right-most screen first.'

    def show_game(self, activate = False):
        '''Bring a hidden game window back to its saved place (Windows pulls a place no
        screen shows any more onto the desktop). ``activate``: in front of every window;
        otherwise it keeps its place in the window stack, behind the user's work. False when
        the window cannot be brought back: what is saved stays, for the next try.'''
        top = self._game_top_window()
        wp = self._placement(top) if top else None
        if wp is None:
            return False
        home = load_hidden_home()
        if home is not None:
            wp.rcNormalPosition = wintypes.RECT(*home)
        wp.showCmd = SW_SHOWNORMAL if activate else SW_SHOWNOACTIVATE
        if not self.user32.SetWindowPlacement(top, ctypes.byref(wp)):
            return False
        forget_hidden_home()
        if activate:
            self.user32.SetForegroundWindow(top)
        logger.info('Game window shown at %s', self._rect(top)[:2])
        return True

    def keep_hidden(self):
        '''The UI's check, every second while the game is hidden. Returns what the user
        should know when it gave up, else ''.

        - brought forward (its taskbar button, Alt+Tab, one of its dialogs): it comes back;
        - minimized (Show desktop): hidden again, restored, so the bot keeps seeing it;
        - back on the desktop some other way: no longer hidden;
        - closed: nothing until the game opens again, then the same checks (Play Games may
          open it where it was last, off the desktop).'''
        if not is_game_hidden():
            return ''
        top = self._game_top_window(quiet = True)
        if not top:
            return ''
        if load_hidden_window()[0] != top:  # the game was opened again: follow its new window
            home = load_hidden_home()
            if home is not None:
                save_hidden_home(home, top, self._get_class(top))
        foreground = self.user32.GetForegroundWindow()
        if foreground and (foreground == top or self.user32.GetAncestor(foreground, GA_ROOTOWNER) == top):
            self.show_game()
        elif self.user32.IsIconic(top):
            why = self.hide_game()
            if why:  # given up: minimized as the user left it (it would come back maximized), or back in its place
                forget_hidden_home()
                return f'The game was minimized and could not be hidden again: {why}'
        elif not off_desktop(self._rect(top), self._desktop()):
            forget_hidden_home()
        return ''
