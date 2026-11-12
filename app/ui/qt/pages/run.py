'''Run page — attack, schedule, modes, live status, controls.'''
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget
from app.config import check_game_window_aspect_for_start
from app.core import bb_strategy, schedule
from app.ui.qt._constants import ATTACK_STRATEGIES, BUILDER_BASE_ATTACK_STRATEGIES
from app.ui.qt.dialogs import show_error, show_under_development
from app.ui.qt.theme import SPACING, TOKENS
from app.ui.qt.widgets import Card, SectionTitle, StepperButton, ToggleSwitch, chip_button, danger_button, neutral_button, primary_button, segment_button, spin_box
from app.utils.common import ui_settings_name
from app.utils.player_list_store import load_players
from app.utils.logger import setup_logger
from app.utils.profile_settings_store import ATTACK_MIN_DARK_K_MAX, ATTACK_MIN_LOOT_K_MAX, load_profile_settings, save_profile_settings
logger = setup_logger('Schedule')
_SCHEDULE_CHECK_MS = 15000  # how often the set start times are checked


def _when(text):
    try:
        return datetime.fromisoformat(str(text)) if text else None
    except ValueError:
        return None


class RunPage(QWidget):
    scheduledStart = Signal(str)  # a set start time ("14:00") just started a run
    _STRATEGY_LABELS = [
        'Valkyries',
        'Sneaky Goblins',
        'Super Minions',
        'Edrags']
    _VILLAGE_LABELS = [
        'Home Village',
        'Builder Base']
    _AUTO_UPGRADE_LABELS = [
        ('Off', 'off'),
        ('Dry run', 'dry'),
        ('Maxer', 'maxer'),
        ('Rusher', 'rusher')]

    def __init__(self, controller, navigate_to, parent = None):
        super().__init__(parent)
        self._controller = controller
        self._navigate_to = navigate_to
        self._settings = QSettings('BasePilot', ui_settings_name())  # per profile, as the main window's
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        outer.setSpacing(SPACING['md'])
        outer.addWidget(self._build_village_selector())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(SPACING['md'])
        self._attack_card = self._build_attack_card()
        layout.addWidget(self._attack_card)
        self._bb_attack_card = self._build_bb_attack_card()
        layout.addWidget(self._bb_attack_card)
        layout.addWidget(self._build_schedule_card())
        self._modes_card = self._build_modes_card()
        layout.addWidget(self._modes_card)
        self._bb_modes_card = self._build_bb_modes_card()
        layout.addWidget(self._bb_modes_card)
        self._status_card = self._build_status_card()
        layout.addWidget(self._status_card)
        layout.addWidget(self._build_controls_card())
        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._apply_village_ui()
        self._restore_choices()
        self._restore_schedule()
        self._controller.botStarted.connect(self._on_bot_started)
        self._controller.botFinished.connect(self._on_bot_finished_ui)
        self._controller.runningChanged.connect(self._on_running_changed)
        self._controller.stateChanged.connect(self._on_state_changed)
        self._controller.lootChanged.connect(self._on_loot_changed)
        self._controller.statusChanged.connect(self._on_status_line)

    
    def _build_village_selector(self):
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        self._village_group = QButtonGroup(self)
        self._village_group.setExclusive(True)
        for i, label in enumerate(self._VILLAGE_LABELS):
            btn = segment_button(label, parent = wrapper)
            if label == 'Home Village':
                btn.setChecked(True)
            self._village_group.addButton(btn, i)
            row.addWidget(btn)
        row.addStretch()
        self._village_group.idClicked.connect(self._on_village_changed)
        return wrapper

    
    def _is_builder_base(self):
        btn = self._village_group.checkedButton()
        return btn is not None and btn.text() == 'Builder Base'

    
    def _on_village_changed(self, _button_id):
        self._apply_village_ui()

    
    def _apply_village_ui(self):
        builder_base = self._is_builder_base()
        self._attack_card.setVisible(not builder_base)
        self._modes_card.setVisible(not builder_base)
        self._bb_attack_card.setVisible(builder_base)
        self._bb_modes_card.setVisible(builder_base)
        self._update_duration_enabled()  # a Home Village Multi-run keeps its duration under Endless

    
    def _build_attack_card(self):
        card = Card()
        card.card_layout.addWidget(SectionTitle('Attack Strategy'))
        row = QHBoxLayout()
        self._strategy_group = QButtonGroup(self)
        self._strategy_group.setExclusive(True)
        for i, label in enumerate(self._STRATEGY_LABELS):
            btn = segment_button(label, parent = card)
            if label == 'Valkyries':
                btn.setChecked(True)
            self._strategy_group.addButton(btn, i)
            row.addWidget(btn)
        card.card_layout.addLayout(row)
        loot_row = QHBoxLayout()
        loot_row.addWidget(SectionTitle('Minimum loot'))
        loot_row.addSpacing(SPACING['xs'])
        self._min_gold = self._min_loot_spin(card)
        loot_row.addWidget(self._min_gold)
        loot_row.addWidget(self._muted('gold', card))
        loot_row.addSpacing(SPACING['md'])
        self._min_elixir = self._min_loot_spin(card)
        loot_row.addWidget(self._min_elixir)
        loot_row.addWidget(self._muted('elixir', card))
        loot_row.addSpacing(SPACING['md'])
        self._min_dark = self._min_loot_spin(card, ATTACK_MIN_DARK_K_MAX, 1)
        loot_row.addWidget(self._min_dark)
        loot_row.addWidget(self._muted('dark', card))
        loot_row.addStretch()
        card.card_layout.addLayout(loot_row)
        loot_hint = self._muted('Home Village only. On the battle-prep screen a base holding less than this is skipped with Next '
                                '(each Next costs a search fee; Settings → Minimum loot to attack caps the skips per raid). '
                                '"any" attacks every base.', card)
        loot_hint.setWordWrap(True)
        card.card_layout.addWidget(loot_hint)
        self._load_min_loot()
        self._min_gold.valueChanged.connect(self._save_min_loot)
        self._min_elixir.valueChanged.connect(self._save_min_loot)
        self._min_dark.valueChanged.connect(self._save_min_loot)
        return card

    @staticmethod
    def _min_loot_spin(parent, maximum = ATTACK_MIN_LOOT_K_MAX, step = 50):
        return spin_box(0, maximum, step = step, suffix = 'k', special = 'any', parent = parent)

    @staticmethod
    def _muted(text, parent):
        label = QLabel(text, parent)
        label.setStyleSheet(f'''color: {TOKENS['text_muted']};''')
        return label

    def _load_min_loot(self):
        '''The loot filter's minimums from the profile (Settings edits them too).'''
        settings = load_profile_settings()
        for (spin, value) in ((self._min_gold, settings.attack_min_gold_k), (self._min_elixir, settings.attack_min_elixir_k),
                              (self._min_dark, settings.attack_min_dark_k)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def _save_min_loot(self, _value = None):
        save_profile_settings(replace(load_profile_settings(), attack_min_gold_k = self._min_gold.value(),
                                      attack_min_elixir_k = self._min_elixir.value(), attack_min_dark_k = self._min_dark.value()))

    def showEvent(self, event):
        super().showEvent(event)
        self._load_min_loot()

    
    def _build_bb_attack_card(self):
        card = Card()
        card.card_layout.addWidget(SectionTitle('Attack Strategy'))
        row = QHBoxLayout()
        self._bb_strategy_group = QButtonGroup(self)
        self._bb_strategy_group.setExclusive(True)
        for i, label in enumerate(BUILDER_BASE_ATTACK_STRATEGIES):
            btn = segment_button(label, parent = card)
            if i == 0:
                btn.setChecked(True)
            self._bb_strategy_group.addButton(btn, i)
            row.addWidget(btn)
        row.addStretch()
        card.card_layout.addLayout(row)
        names = ', '.join(bb_strategy.TROOP_NAMES[t] for t in bb_strategy.PROFILES)
        hint = QLabel('The bot reads the troops on your bar and plays each its own way: the tanks first (the machine, Boxer Giants, '
                      'P.E.K.K.As), Bombers and Raged Barbarians behind them, the support last, Baby Dragons apart; each ability '
                      'once its troop is engaged, one at a time. Battles are always played to the end. Recognised: ' + names + '.')
        hint.setWordWrap(True)
        hint.setStyleSheet(f'''color: {TOKENS['text_muted']};''')
        card.card_layout.addWidget(hint)
        return card

    
    def _build_schedule_card(self):
        card = Card()
        card.card_layout.addWidget(SectionTitle('Schedule'))
        self._star_bonus = ToggleSwitch('Star Bonus', parent = card)
        self._star_bonus.toggled.connect(self._on_star_bonus_toggle)
        card.card_layout.addWidget(self._star_bonus)
        self._endless = ToggleSwitch('Endless (until you press Stop)', parent = card)
        self._endless.toggled.connect(self._on_endless_toggle)
        card.card_layout.addWidget(self._endless)
        endless_hint = self._muted('Battles go on with no time limit, in either village, until you press Stop. A screen the bot '
                                   'cannot get past makes it back off 5 minutes and retry instead of ending the run. Home Village '
                                   'with Maxer or Rusher: when storages are full and nothing can be started, the attacks pause '
                                   'and the bot rechecks every 5 minutes. A Multi-run keeps the duration, for each account.', card)
        endless_hint.setWordWrap(True)
        card.card_layout.addWidget(endless_hint)
        self._stop_when_full = ToggleSwitch('Stop when storages are full', parent = card)
        card.card_layout.addWidget(self._stop_when_full)
        full_hint = self._muted('Ends the run once the gold and elixir bars are both full, in either village. Checked between '
                                'battles, after the walls and upgrades had their turn: what they spend keeps the run going. With '
                                'a duration or Endless; in a Multi-run, that account is done and the next one starts.', card)
        full_hint.setWordWrap(True)
        card.card_layout.addWidget(full_hint)
        dur_row = QHBoxLayout()
        self._duration_label = SectionTitle('Duration')
        dur_row.addWidget(self._duration_label)
        self._minutes_spin = QSpinBox()
        self._minutes_spin.setObjectName('DurationSpin')
        self._minutes_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._minutes_spin.setRange(1, 999)
        self._minutes_spin.setValue(15)
        self._minutes_spin.setFixedSize(56, 28)
        self._minutes_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        step_col = QVBoxLayout()
        step_col.setSpacing(2)
        step_col.setContentsMargins(0, 0, 0, 0)
        self._btn_spin_up = StepperButton(up = True, parent = card)
        self._btn_spin_up.clicked.connect((lambda : self._step_minutes(1)))
        self._btn_spin_down = StepperButton(up = False, parent = card)
        self._btn_spin_down.clicked.connect((lambda : self._step_minutes(-1)))
        step_col.addWidget(self._btn_spin_up)
        step_col.addWidget(self._btn_spin_down)
        self._minutes_unit = QLabel('minutes')
        self._minutes_unit.setObjectName('DurationUnit')
        self._minutes_unit.setStyleSheet(f'''color: {TOKENS['text_muted']};''')
        spin_group = QHBoxLayout()
        spin_group.setSpacing(4)
        spin_group.addWidget(self._minutes_spin)
        spin_group.addLayout(step_col)
        spin_group.addWidget(self._minutes_unit)
        spin_group.addStretch()
        dur_row.addLayout(spin_group)
        dur_row.addStretch()
        card.card_layout.addLayout(dur_row)
        preset_row = QHBoxLayout()
        self._btn_5m = chip_button('5m', parent = card)
        self._btn_5m.clicked.connect((lambda : self._set_minutes(5)))
        preset_row.addWidget(self._btn_5m)
        self._btn_10m = chip_button('10m', parent = card)
        self._btn_10m.clicked.connect((lambda : self._set_minutes(10)))
        preset_row.addWidget(self._btn_10m)
        self._btn_20m = chip_button('20m', parent = card)
        self._btn_20m.clicked.connect((lambda : self._set_minutes(20)))
        preset_row.addWidget(self._btn_20m)
        preset_row.addStretch()
        card.card_layout.addLayout(preset_row)
        self._on_star_bonus_toggle(self._star_bonus.isChecked())
        self._timed = ToggleSwitch('Start at set times (every day)', parent = card)
        card.card_layout.addWidget(self._timed)
        times_row = QHBoxLayout()
        self._times_edit = QLineEdit(card)
        self._times_edit.setPlaceholderText('08:00, 13:30, 21:00')
        self._times_edit.setFixedWidth(220)
        times_row.addWidget(self._times_edit)
        times_row.addSpacing(SPACING['xs'])
        self._times_note = self._muted('', card)
        times_row.addWidget(self._times_note)
        times_row.addStretch()
        card.card_layout.addLayout(times_row)
        timed_hint = self._muted('While BasePilot is open, it presses Start by itself at each time, with this page as it is set '
                                 '(village, strategy, duration, modes). A run still going at that time is left alone: the start '
                                 'goes once it ends, if that is within 10 minutes.', card)
        timed_hint.setWordWrap(True)
        card.card_layout.addWidget(timed_hint)
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(_SCHEDULE_CHECK_MS)
        self._schedule_timer.timeout.connect(self._check_schedule)
        return card

    def _restore_schedule(self):
        self._times_edit.setText(str(self._settings.value('schedule/times', '') or ''))
        self._timed.setChecked(self._settings.value('schedule/enabled', False, type = bool))
        self._schedule_last = _when(self._settings.value('schedule/last', ''))
        self._timed.toggled.connect(self._on_schedule_changed)
        self._times_edit.textChanged.connect(self._on_schedule_changed)
        self._update_schedule_note()
        self._schedule_timer.start()

    def _on_schedule_changed(self, *_args):
        self._settings.setValue('schedule/enabled', self._timed.isChecked())
        self._settings.setValue('schedule/times', self._times_edit.text().strip())
        self._update_schedule_note()

    def _update_schedule_note(self, now = None):
        (times, bad) = schedule.parse_times(self._times_edit.text())
        now = now or datetime.now()
        if bad:
            text = 'Not a time: ' + ', '.join(bad)
        elif not times:
            text = 'Times as HH:MM'
        elif not self._timed.isChecked():
            text = 'Off'
        else:
            at = schedule.next_start(now, times)
            text = f'''Next start: {'today' if at.date() == now.date() else 'tomorrow'} {at:%H:%M}'''
        self._times_note.setText(text)

    def _check_schedule(self, now = None):
        '''Start the run a set time calls for (see :mod:`app.core.schedule`).'''
        now = now or datetime.now()
        self._update_schedule_note(now)
        if not self._timed.isChecked():
            return None
        (times, _bad) = schedule.parse_times(self._times_edit.text())
        at = schedule.due(now, times, getattr(self, '_schedule_last', None))
        if at is None or self._controller.is_running():
            return None  # a run going on: checked again until it ends, or the start is too late
        self._schedule_last = at  # once, even when the start does not go (a setting to fix first)
        self._settings.setValue('schedule/last', at.isoformat(timespec = 'minutes'))
        logger.info('Scheduled start (%s)', f'{at:%H:%M}')
        self.start_bot()
        if self._controller.is_running():
            self.scheduledStart.emit(f'{at:%H:%M}')

    
    def _build_modes_card(self):
        card = Card()
        card.card_layout.addWidget(SectionTitle('Modes'))
        upg_row = QHBoxLayout()
        upg_row.addWidget(SectionTitle('Auto upgrade'))
        upg_row.addSpacing(SPACING['xs'])
        self._auto_upgrade_group = QButtonGroup(self)
        self._auto_upgrade_group.setExclusive(True)
        for i, (label, _key) in enumerate(self._AUTO_UPGRADE_LABELS):
            btn = segment_button(label, parent = card)
            if label == 'Off':
                btn.setChecked(True)
            self._auto_upgrade_group.addButton(btn, i)
            upg_row.addWidget(btn)
        upg_row.addStretch()
        card.card_layout.addLayout(upg_row)
        upg_hint = QLabel('When one of your regular builders is free, Maxer starts an affordable upgrade (never the Town Hall), and the laboratory starts a research; Rusher also grabs the Town Hall the moment it is affordable. The goblin builder and researcher are never used, and any gem prompt is closed at once. Dry run only logs what it would start. Reserve builders for walls in Settings (only applies with Upgrade walls on).')
        upg_hint.setWordWrap(True)
        upg_hint.setStyleSheet(f'''color: {TOKENS['text_muted']};''')
        card.card_layout.addWidget(upg_hint)
        self._upgrade_walls = ToggleSwitch('Upgrade walls', parent = card)
        card.card_layout.addWidget(self._upgrade_walls)
        self._auto_donate = ToggleSwitch('Auto donate', parent = card)
        card.card_layout.addWidget(self._auto_donate)
        self._auto_request = ToggleSwitch('Auto request troops', parent = card)
        card.card_layout.addWidget(self._auto_request)
        clan_hint = QLabel('Between raids the bot opens the clan chat, donates to open requests, and asks for reinforcements. Pick the chat button once in Settings → Clan assist — dry run is on there by default, so the first run only logs what it would click.')
        clan_hint.setWordWrap(True)
        clan_hint.setStyleSheet(f'''color: {TOKENS['text_muted']};''')
        card.card_layout.addWidget(clan_hint)
        mr_row = QHBoxLayout()
        self._multi_run = ToggleSwitch('Multi-run', parent = card)
        self._multi_run.toggled.connect(lambda _checked: self._update_duration_enabled())
        mr_row.addWidget(self._multi_run)
        mr_row.addStretch()
        edit_players = neutral_button('Edit player list', parent = card)
        edit_players.clicked.connect((lambda : self._navigate_to('players')))
        mr_row.addWidget(edit_players)
        card.card_layout.addLayout(mr_row)
        return card

    
    def _build_bb_modes_card(self):
        card = Card()
        card.card_layout.addWidget(SectionTitle('Modes'))
        # No loot priority: every Builder Base battle is played to its end, never ended early.
        self._bb_auto_upgrade = ToggleSwitch('Auto upgrade (builders and star lab, mode from Home Village)', parent = card)
        card.card_layout.addWidget(self._bb_auto_upgrade)
        self._bb_upgrade_walls = ToggleSwitch('Upgrade walls', parent = card)
        card.card_layout.addWidget(self._bb_upgrade_walls)
        bb_walls_hint = self._muted('Between battles, a wall at a time from the Build panel, paid with the gold or elixir over '
                                    'the threshold in Settings → Wall upgrade threshold → Builder Base (full storages by default). '
                                    'Never through a gem prompt, never the Wall Ring.', card)
        bb_walls_hint.setWordWrap(True)
        card.card_layout.addWidget(bb_walls_hint)
        mr_row = QHBoxLayout()
        self._bb_multi_run = ToggleSwitch('Multi-run', parent = card, under_development = True)
        mr_row.addWidget(self._bb_multi_run)
        mr_row.addStretch()
        edit_players = neutral_button('Edit player list', parent = card)
        edit_players.setStyleSheet(f'''color: {TOKENS['text_muted']};''')
        edit_players.clicked.connect((lambda : show_under_development(self.window())))
        mr_row.addWidget(edit_players)
        card.card_layout.addLayout(mr_row)
        return card

    
    def _build_status_card(self):
        card = Card()
        card.setProperty('variant', 'status')
        card.style().unpolish(card)
        card.style().polish(card)
        card.card_layout.addWidget(SectionTitle('Live status'))
        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACING['lg'])
        grid.setVerticalSpacing(4)

        def stat(row, col, title):
            t = QLabel(title.upper())
            t.setObjectName('StatTitle')
            font = t.font()
            font.setLetterSpacing(font.SpacingType.PercentageSpacing, 110)
            t.setFont(font)
            v = QLabel('—')
            v.setObjectName('StatValue')
            # Word-wrap keeps a long readout (the storages triplet) from inflating the
            # card's minimum width past the viewport (clipped every card's right edge).
            v.setWordWrap(True)
            grid.addWidget(t, row * 2, col)
            grid.addWidget(v, row * 2 + 1, col)
            grid.setColumnStretch(col, 1)
            return v

        self._stat_state = stat(0, 0, 'State')
        self._stat_builders = stat(0, 1, 'Builders free')
        self._stat_lab = stat(0, 2, 'Lab free')
        self._stat_storages = stat(0, 3, 'Storages')
        self._stat_loot = stat(1, 0, 'Loot this session')
        self._stat_loot_rate = stat(1, 1, 'Loot / hour')
        self._stat_skipped = stat(1, 2, 'Bases skipped')
        self._stat_note = QLabel('Start the bot to see live village state here. Builders / lab / storages update while Auto upgrade is on.')
        self._stat_note.setWordWrap(True)
        self._stat_note.setStyleSheet(f'''color: {TOKENS['text_muted']};''')
        card.card_layout.addLayout(grid)
        card.card_layout.addWidget(self._stat_note)
        return card

    @staticmethod
    def _fmt_amount(value):
        value = int(value)
        if value >= 1000000:
            return f'''{value / 1000000:.1f}M'''
        if value >= 10000:
            return f'''{value / 1000:.0f}k'''
        return str(value)

    _STATE_COLORS = {
        'farming': '#4ADE80',  # engaged green
        'builder base': '#4ADE80',
        'idling': '#F59E0B',   # holding amber
    }

    def _on_state_changed(self, payload):
        state = payload.get('state')
        if state:
            self._stat_state.setText(str(state).upper())
            color = self._STATE_COLORS.get(str(state).lower(), TOKENS['text'])
            self._stat_state.setStyleSheet(f'''color: {color};''')
        builders = payload.get('builders')
        if builders:
            self._stat_builders.setText(f'''{builders[0]} / {builders[1]}''')
        lab = payload.get('lab')
        if lab:
            self._stat_lab.setText(f'''{lab[0]} / {lab[1]}''')
        storages = payload.get('storages')
        if storages:
            self._stat_storages.setText(str(storages))
        skipped = payload.get('skipped')
        if skipped is not None:
            self._stat_skipped.setText(str(skipped))
        note = payload.get('note')
        if note:
            self._stat_note.setText(f'''Upgrades: {note}''')

    def _on_loot_changed(self, gold, elixir, dark, elapsed):
        self._stat_loot.setText(f'''{self._fmt_amount(gold)} / {self._fmt_amount(elixir)} / {self._fmt_amount(dark)}''')
        if elapsed < 600:
            # A per-hour figure extrapolated from a few minutes is noise — hold it back.
            self._stat_loot_rate.setText('— (needs 10m)')
            return None
        hours = elapsed / 3600
        self._stat_loot_rate.setText(f'''{self._fmt_amount(gold / hours)} / {self._fmt_amount(elixir / hours)} / {self._fmt_amount(dark / hours)}''')

    def _on_status_line(self, msg, _warning):
        if msg.lower().startswith(('idling', 'resuming')):
            idling = msg.lower().startswith('idling')
            self._stat_state.setText('IDLING' if idling else 'FARMING')
            self._stat_state.setStyleSheet(f'''color: {self._STATE_COLORS['idling' if idling else 'farming']};''')
            self._stat_note.setText(msg)

    def _build_controls_card(self):
        card = Card()
        btn_row = QHBoxLayout()
        self._btn_start = primary_button('Start', parent = card)
        self._btn_start.setMinimumHeight(42)
        self._btn_start.clicked.connect(self.start_bot)
        btn_row.addWidget(self._btn_start)
        self._btn_stop = danger_button('Stop', parent = card)
        self._btn_stop.setMinimumHeight(42)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._controller.stop)
        btn_row.addWidget(self._btn_stop)
        card.card_layout.addLayout(btn_row)
        return card

    
    def _clear_minutes_selection(self):
        editor = self._minutes_spin.lineEdit()
        if not editor is None:
            editor.deselect()
            editor.setCursorPosition(len(editor.text()))
            return None

    
    def _endless_applies(self):
        '''Endless takes the duration's place, except in a Home Village Multi-run (a duration
        for each account).'''
        multi_run = getattr(self, '_multi_run', None)  # the Modes card is built after this one
        multi = multi_run is not None and multi_run.isChecked() and not self._is_builder_base()
        return self._endless.isChecked() and not multi

    def _duration_locked(self):
        return self._star_bonus.isChecked() or self._endless_applies()

    def _step_minutes(self, delta):
        if self._duration_locked():
            return None
        if delta > 0:
            self._minutes_spin.stepUp()
        else:
            self._minutes_spin.stepDown()
        self._clear_minutes_selection()
        QTimer.singleShot(0, self._clear_minutes_selection)


    def _set_minutes(self, value):
        if self._duration_locked():
            return None
        self._minutes_spin.setValue(value)
        self._clear_minutes_selection()


    def _update_duration_enabled(self):
        enabled = not self._duration_locked()
        duration_widgets = (self._duration_label, self._minutes_spin, self._btn_spin_up, self._btn_spin_down, self._minutes_unit, self._btn_5m, self._btn_10m, self._btn_20m)
        for widget in duration_widgets:
            widget.setEnabled(enabled)
        if enabled:
            self._minutes_unit.setStyleSheet(f'''color: {TOKENS['text_muted']};''')
            return None
        self._minutes_unit.setStyleSheet('color: #4a5568;')

    def _on_star_bonus_toggle(self, checked):
        if checked and getattr(self, '_endless', None) is not None and self._endless.isChecked():
            self._endless.setChecked(False)
        self._update_duration_enabled()

    def _on_endless_toggle(self, checked):
        if checked and self._star_bonus.isChecked():
            self._star_bonus.setChecked(False)
        self._update_duration_enabled()

    
    def _get_method(self):
        if self._is_builder_base():
            btn = self._bb_strategy_group.checkedButton()
            if btn is None:
                return next(iter(BUILDER_BASE_ATTACK_STRATEGIES.values()))
            return BUILDER_BASE_ATTACK_STRATEGIES.get(btn.text(), 5)
        btn = self._strategy_group.checkedButton()
        if btn is None:
            return ATTACK_STRATEGIES['Valkyries']
        return ATTACK_STRATEGIES.get(btn.text(), 1)

    

    def _get_auto_upgrade_mode(self):
        checked_id = self._auto_upgrade_group.checkedId()
        if 0 <= checked_id < len(self._AUTO_UPGRADE_LABELS):
            return self._AUTO_UPGRADE_LABELS[checked_id][1]
        return 'off'

    def _set_auto_upgrade_mode(self, mode):
        for i, (_label, key) in enumerate(self._AUTO_UPGRADE_LABELS):
            if key == mode:
                btn = self._auto_upgrade_group.button(i)
                if btn is not None:
                    btn.setChecked(True)
                return None

    def _restore_choices(self):
        '''Bring back the last run's choices (mode, walls, duration) across app starts.'''
        self._set_auto_upgrade_mode(str(self._settings.value('run/autoUpgrade', 'off')))
        self._upgrade_walls.setChecked(self._settings.value('run/upgradeWalls', False, type = bool))
        self._bb_auto_upgrade.setChecked(self._settings.value('run/bbAutoUpgrade', False, type = bool))
        self._bb_upgrade_walls.setChecked(self._settings.value('run/bbUpgradeWalls', False, type = bool))
        self._auto_donate.setChecked(self._settings.value('run/autoDonate', False, type = bool))
        self._auto_request.setChecked(self._settings.value('run/autoRequest', False, type = bool))
        # Endless keeps the key of its old name, "Run until maxed": a saved choice carries over.
        self._endless.setChecked(self._settings.value('run/untilMaxed', False, type = bool))
        self._stop_when_full.setChecked(self._settings.value('run/stopWhenFull', False, type = bool))
        minutes = self._settings.value('run/minutes', 15, type = int)
        if 1 <= minutes <= 999:
            self._minutes_spin.setValue(minutes)

    def _save_choices(self):
        self._settings.setValue('run/autoUpgrade', self._get_auto_upgrade_mode())
        self._settings.setValue('run/upgradeWalls', self._upgrade_walls.isChecked())
        self._settings.setValue('run/bbAutoUpgrade', self._bb_auto_upgrade.isChecked())
        self._settings.setValue('run/bbUpgradeWalls', self._bb_upgrade_walls.isChecked())
        self._settings.setValue('run/autoDonate', self._auto_donate.isChecked())
        self._settings.setValue('run/autoRequest', self._auto_request.isChecked())
        self._settings.setValue('run/untilMaxed', self._endless.isChecked())
        self._settings.setValue('run/stopWhenFull', self._stop_when_full.isChecked())
        self._settings.setValue('run/minutes', self._minutes_spin.value())

    
    def _get_minutes(self):
        return self._minutes_spin.value()

    
    def _multi_run_players_for_start(self):
        if self._is_builder_base() or not self._multi_run.isChecked():  # [recovered: decompiler inverted both halves — multi-run never engaged on Home Village]
            return None
        players = load_players()
        if not any([ p.enabled and p.name.strip() for p in players ]):
            return []
        return players

    
    def start_bot(self):
        if self._controller.is_running():
            return None
        if not check_game_window_aspect_for_start(parent = self.window(), on_configure = (lambda : self._navigate_to('settings'))):
            return None
        builder_base = self._is_builder_base()
        method = self._get_method()
        multi_arg = self._multi_run_players_for_start()
        if not builder_base and self._multi_run.isChecked() and not multi_arg:  # [recovered: decompiler dropped the `not` — the error fired when players DID exist]
            show_error(self.window(), 'Multi-run', 'Enable at least one player with Run and a non-empty name.\nOpen Player list… to edit.')
            return None
        star_bonus = self._star_bonus.isChecked()
        # Endless = no time limit, in either village; a Multi-run keeps its duration per account.
        endless = not star_bonus and self._endless_applies()
        if star_bonus:
            mins = 5
        elif endless:
            mins = 0
        else:
            mins = self._get_minutes()
            if mins <= 0 or mins > 999:
                show_error(self.window(), 'Error', 'Invalid time duration. Enter 1-999 minutes.')
                return None
        self._save_choices()
        if builder_base:
            upgrade_walls = self._bb_upgrade_walls.isChecked()
            auto_upgrade = self._get_auto_upgrade_mode() if self._bb_auto_upgrade.isChecked() else 'off'
            # Clan assist rides the Home Village flow (the chat button is calibrated on it,
            # and the Builder Base has no clan chat).
            (auto_donate, auto_request) = (False, False)
        else:
            upgrade_walls = self._upgrade_walls.isChecked()
            auto_upgrade = self._get_auto_upgrade_mode()
            (auto_donate, auto_request) = (self._auto_donate.isChecked(), self._auto_request.isChecked())
        self._controller.start(method = method, minutes = mins, star_bonus = star_bonus, upgrade_walls = upgrade_walls,
                               multi_run_players = multi_arg, builder_base = builder_base, auto_upgrade = auto_upgrade,
                               auto_donate = auto_donate, auto_request = auto_request, stop_when_full = self._stop_when_full.isChecked())

    
    def is_star_bonus_enabled(self):
        return self._star_bonus.isChecked()

    
    def request_start_from_taskbar(self):
        if not self._controller.is_running():
            self.start_bot()
            return None


    def apply_autostart(self, minutes, upgrade_walls, auto_upgrade = 'off', auto_donate = False, auto_request = False):
        '''CLI ``--autostart``: Home Village run with the given duration (``0`` =
        endless), wall toggle, auto-upgrade mode (off|dry|maxer|rusher), and
        the clan-assist toggles.'''
        if self._controller.is_running():
            return None
        self._star_bonus.setChecked(False)
        self._endless.setChecked(minutes <= 0)
        if minutes > 0:
            self._minutes_spin.setValue(minutes)
        self._upgrade_walls.setChecked(bool(upgrade_walls))
        self._auto_donate.setChecked(bool(auto_donate))
        self._auto_request.setChecked(bool(auto_request))
        self._set_auto_upgrade_mode(auto_upgrade)
        self.start_bot()

    
    def request_stop_from_taskbar(self):
        if self._controller.is_running():
            self._controller.stop()
            return None

    
    def _on_bot_started(self):
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)

    
    def _on_bot_finished_ui(self, _error):
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)

    
    def _on_running_changed(self, running):
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)


