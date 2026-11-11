'''Stats page — the sessions and battles of the history (:mod:`app.core.stats`).'''
from __future__ import annotations
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app.core import stats
from app.ui.qt.theme import SPACING, TOKENS
from app.ui.qt.widgets import Card, PageTitle, SectionTitle, neutral_button
from app.utils import battle_history

_STAR_COLOURS = {0: TOKENS['danger'], 1: TOKENS['warning'], 2: '#84CC16', 3: TOKENS['success']}
_COLUMNS = ('Started', 'Village', 'Battles', 'Gold', 'Elixir', 'Dark', 'Gold / h', 'Elixir / h', 'Stars', 'Damage')


def _amount(value):
    value = int(value)
    if abs(value) >= 1000000:
        return f'{value / 1000000:.1f}M'
    if abs(value) >= 10000:
        return f'{value / 1000:.0f}k'
    return str(value)


class DamageChart(QWidget):
    '''Bars of the last Builder Base battles' damage (0-200 %), coloured by their stars.'''

    def __init__(self, parent = None):
        super().__init__(parent)
        self._battles = []
        self.setMinimumHeight(140)

    def set_battles(self, battles):
        self._battles = list(battles)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        (w, h) = (self.width(), self.height())
        painter.setPen(QPen(QColor(TOKENS['border'])))
        for level in (100, 200):  # the end of each stage
            y = h - 4 - (h - 8) * level / 200
            painter.drawLine(0, int(y), w, int(y))
        if not self._battles:
            painter.setPen(QColor(TOKENS['text_muted']))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'No Builder Base battle recorded yet')
            return
        step = w / max(1, len(self._battles))
        for (i, (damage, stars)) in enumerate(self._battles):
            bar = (h - 8) * min(200, damage) / 200
            painter.fillRect(QRectF(i * step + 1, h - 4 - bar, max(1.0, step - 2), bar), QColor(_STAR_COLOURS.get(stars, TOKENS['success'])))


class StatsPage(QWidget):
    def __init__(self, parent = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        layout.setSpacing(SPACING['md'])
        layout.addWidget(PageTitle('Stats'))
        buttons = QHBoxLayout()
        refresh = neutral_button('Refresh')
        refresh.clicked.connect(self.reload)
        buttons.addWidget(refresh)
        export = neutral_button('Export CSV')
        export.clicked.connect(self._export)
        buttons.addWidget(export)
        buttons.addStretch()
        layout.addLayout(buttons)
        self._summary = QLabel('')
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(f'''color: {TOKENS['text_muted']};''')
        layout.addWidget(self._summary)
        chart_card = Card()
        chart_card.card_layout.addWidget(SectionTitle('Builder Base: damage of the last battles (bar colour: stars)'))
        self._chart = DamageChart(chart_card)
        chart_card.card_layout.addWidget(self._chart)
        layout.addWidget(chart_card)
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, stretch = 1)
        self._records = []

    def showEvent(self, event):
        super().showEvent(event)
        self.reload()

    def reload(self):
        self._records = battle_history.load()
        summaries = stats.sessions(self._records)
        self._table.setRowCount(len(summaries))
        for (row, s) in enumerate(summaries):
            cells = (s.start.strftime('%d/%m %H:%M'), {'home': 'Home', 'builder': 'Builder', 'both': 'Both'}.get(s.village, s.village),
                     str(s.battles), _amount(s.gold), _amount(s.elixir), _amount(s.dark),
                     _amount(s.per_hour(s.gold)), _amount(s.per_hour(s.elixir)),
                     '' if s.stars is None else f'{s.stars:.1f}', '' if s.damage is None else f'{s.damage:.0f} %')
            for (col, text) in enumerate(cells):
                self._table.setItem(row, col, QTableWidgetItem(text))
        battles = stats.builder_damage(self._records)
        self._chart.set_battles(battles)
        if not self._records:
            self._summary.setText('No battle recorded yet: they are kept from the next run on.')
        else:
            gold = sum(s.gold for s in summaries)
            builder = [r for r in self._records if r.get('village') == 'builder']
            text = f'{len(summaries)} session(s), {len(self._records)} battle(s), {_amount(gold)} gold in all.'
            if builder:
                text += f' Builder Base: {sum(int(r.get("damage") or 0) for r in builder) / len(builder):.0f} % damage on average over {len(builder)} battle(s).'
            self._summary.setText(text)

    def _export(self):
        (path, _filter) = QFileDialog.getSaveFileName(self, 'Export the battles', 'basepilot-battles.csv', 'CSV (*.csv)')
        if path:
            stats.write_csv(self._records or battle_history.load(), path)
