'''Logs page — tail basepilot.log in the UI.'''
from __future__ import annotations
import os
import subprocess
import sys
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget
from app.ui.qt.theme import SPACING
from app.ui.qt.widgets import PageTitle, neutral_button
from app.utils.common import get_log_path

# A visit reads this much of the log's end. The view keeps its last 5000 lines anyway (~90 bytes
# a line: ~450 KB, so 1 MiB holds them twice over), and reading the whole 5 MB log stalled the page.
_TAIL_BYTES = 1024 * 1024

class LogsPage(QWidget):
    
    def __init__(self, parent = None):
        super().__init__(parent)
        self._pos = None  # read offset; None: start over from the log's end
        self._tail_timer = QTimer(self)
        self._tail_timer.setInterval(1000)
        self._tail_timer.timeout.connect(self._tail_log)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        layout.setSpacing(SPACING['md'])
        layout.addWidget(PageTitle('Logs'))
        btn_row = QHBoxLayout()
        open_btn = neutral_button('Open in Explorer')
        open_btn.clicked.connect(self._open_in_explorer)
        btn_row.addWidget(open_btn)
        clear_btn = neutral_button('Clear view')
        clear_btn.clicked.connect(self._clear_view)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(5000)
        mono = QFont('Courier New', 9)
        self._log_view.setFont(mono)
        layout.addWidget(self._log_view, stretch = 1)

    
    def showEvent(self, event):
        super().showEvent(event)
        if not event.spontaneous():  # a visit; the window coming back from the taskbar is not one
            self._log_view.clear()  # it still holds the last visit's text
            self._pos = None
        self._tail_log()
        self._tail_timer.start()

    
    def hideEvent(self, event):
        self._tail_timer.stop()
        super().hideEvent(event)

    
    def _tail_log(self):
        path = get_log_path()
        
        try:
            path.parent.mkdir(parents = True, exist_ok = True)
            if not path.is_file():
                path.touch()
            size = path.stat().st_size
            (pos, start) = (self._pos, None)
            if pos is None or size < pos:
                # a new visit, or the log rolled over: start near its end, one byte early so
                # a line starting right there keeps the newline before it to cut on
                start = pos = max(0, size - _TAIL_BYTES - 1)
            with path.open('rb') as fh:
                fh.seek(pos)
                chunk = fh.read()
                self._pos = fh.tell()
            if start:
                chunk = chunk[chunk.find(b'\n') + 1:]  # from the first whole line
            if chunk:
                text = chunk.decode('utf-8', errors = 'replace')
                self._log_view.moveCursor(QTextCursor.MoveOperation.End)
                self._log_view.insertPlainText(text)
                self._log_view.moveCursor(QTextCursor.MoveOperation.End)
                return None
            return None
        except OSError:
            return None


    
    def _clear_view(self):
        self._log_view.clear()

    
    def _open_in_explorer(self):
        path = get_log_path()
        
        try:
            path.parent.mkdir(parents = True, exist_ok = True)
            if not path.is_file():
                path.touch()
            if sys.platform == 'win32':
                os.startfile(path.parent)
                return None
            if sys.platform == 'darwin':
                subprocess.run([
                    'open',
                    str(path.parent)], check = False)
                return None
            subprocess.run([
                'xdg-open',
                str(path.parent)], check = False)
            return None
        except OSError:
            return None



