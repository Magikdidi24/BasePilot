'''Reusable Qt widgets for the BasePilot UI.'''
from __future__ import annotations
from PySide6.QtCore import Qt, QRectF, QSize, QPointF
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QPushButton, QScrollArea, QSpinBox, QVBoxLayout
from app.ui.qt.theme import SPACING, TOKENS

class Card(QFrame):
    
    def __init__(self, parent = None):
        super().__init__(parent)
        self.setObjectName('Card')
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(SPACING['md'], SPACING['md'], SPACING['md'], SPACING['md'])
        self._layout.setSpacing(SPACING['sm'])

    
    @property
    def card_layout(self):
        return self._layout



class SectionTitle(QLabel):
    '''Instrument-panel micro-label: uppercase + letter-spaced (QSS cannot express
    either, so the widget owns them; color/size stay in the stylesheet).'''

    def __init__(self, text, parent = None):
        super().__init__(text.upper(), parent)
        self.setObjectName('SectionTitle')
        self.setAutoFillBackground(False)
        font = self.font()
        font.setLetterSpacing(font.SpacingType.PercentageSpacing, 108)
        self.setFont(font)



class PageTitle(QLabel):
    
    def __init__(self, text, parent = None):
        super().__init__(text, parent)
        self.setObjectName('PageTitle')



class ToggleSwitch(QCheckBox):
    
    def __init__(self, text = '', *, parent = None, under_development = False):
        super().__init__(text, parent)
        self.setObjectName('ToggleSwitch')
        self._under_development = under_development
        self.setFixedHeight(24)
        if under_development:
            self.setChecked(False)
            return None

    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        (track_w, track_h) = (40, 22)
        x0 = 0
        y0 = (self.height() - track_h) // 2
        if self._under_development:
            on_color = QColor(TOKENS['border_hi'])
            off_color = QColor(TOKENS['border'])
            text_color = QColor(TOKENS['text_faint'])
        else:
            on_color = QColor(TOKENS['primary'])
            off_color = QColor(TOKENS['neutral'])
            text_color = QColor(TOKENS['text'])
        track_color = on_color if self.isChecked() and not self._under_development else off_color
        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(x0, y0, track_w, track_h, track_h / 2, track_h / 2)
        knob_d = 18
        knob_x = x0 + track_w - knob_d - 2 if self.isChecked() and not self._under_development else x0 + 2
        knob_y = y0 + (track_h - knob_d) // 2
        painter.setBrush(QColor('#a0a0a8' if self._under_development else '#ffffff'))
        painter.drawEllipse(knob_x, knob_y, knob_d, knob_d)
        if self.text():
            painter.setPen(text_color)
            font = painter.font()
            font.setPointSize(10)
            painter.setFont(font)
            text_rect = QRectF(track_w + 10, 0, self.width() - track_w - 10, self.height())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
            return None

    
    def mousePressEvent(self, event):
        if self._under_development:
            from app.ui.qt.dialogs import show_under_development
            show_under_development(self.window())
            return None
        super().mousePressEvent(event)

    
    def sizeHint(self):
        text_w = self.fontMetrics().horizontalAdvance(self.text()) + 8 if self.text() else 0
        return QSize(40 + text_w + 10, 24)

    
    def hitButton(self, pos):
        return self.rect().contains(pos)



def _styled_button(text, role, parent = None):
    btn = QPushButton(text, parent)
    btn.setProperty('role', role)
    btn.style().unpolish(btn)
    btn.style().polish(btn)
    return btn


def primary_button(text, *, parent = None):
    return _styled_button(text, 'primary', parent)


def danger_button(text, *, parent = None):
    return _styled_button(text, 'danger', parent)


def neutral_button(text, *, parent = None):
    return _styled_button(text, 'neutral', parent)


def chip_button(text, *, parent = None):
    return _styled_button(text, 'chip', parent)


def segment_button(text, *, parent = None):
    btn = _styled_button(text, 'segment', parent)
    btn.setCheckable(True)
    btn.setMinimumWidth(int(btn.sizeHint().width() * 1.1))
    return btn


class StepperButton(QPushButton):
    '''Compact up/down arrow for numeric steppers.'''
    
    def __init__(self, *, up, parent = None):
        super().__init__(parent)
        self._up = up
        self.setProperty('role', 'stepper')
        self.setFixedSize(22, 13)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.style().unpolish(self)
        self.style().polish(self)

    
    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isEnabled():
            return None
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TOKENS['text']))
        cx = self.width() / 2
        cy = self.height() / 2
        if self._up:
            points = [
                QPointF(cx, cy - 3),
                QPointF(cx - 4, cy + 2),
                QPointF(cx + 4, cy + 2)]
        else:
            points = [
                QPointF(cx, cy + 3),
                QPointF(cx - 4, cy - 2),
                QPointF(cx + 4, cy - 2)]
        painter.drawPolygon(QPolygonF(points))


def spin_box(low, high, *, step = 1, suffix = '', special = '', width = 88, tip = '', parent = None):
    '''A QSpinBox of ``low``..``high`` at the settings' fixed width; ``special`` is shown for
    the lowest value ("any", "off"…).'''
    spin = QSpinBox(parent)
    spin.setRange(low, high)
    spin.setSingleStep(step)
    spin.setSuffix(suffix)
    spin.setSpecialValueText(special)
    spin.setFixedWidth(width)
    spin.setToolTip(tip)
    return spin


def loot_spin(maximum, step, parent = None):
    '''A minimum-loot spin in thousands, "any" at 0: Settings and the Run page show the same.'''
    return spin_box(0, maximum, step = step, suffix = 'k', special = 'any', parent = parent)


def muted_label(text, parent = None):
    '''A label in the muted text colour: units and notes beside the controls.'''
    label = QLabel(text, parent)
    label.setStyleSheet(f'''color: {TOKENS['text_muted']};''')
    return label


def hint_label(text, parent = None):
    '''A muted label that wraps: the explanations under the controls.'''
    label = muted_label(text, parent)
    label.setWordWrap(True)
    return label


def scroll_page(content):
    '''``content`` in a scroll area that sizes it to the page's width: vertical scrolling only.'''
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll
