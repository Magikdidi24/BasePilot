'''Settings page — profile preferences and manual game-window selection.'''
from __future__ import annotations
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QVBoxLayout, QWidget
from app.config import aspect_label, resolve_aspect_key
from app.services.display import DisplayService
from app.services.window import WindowService
from app.core.clan import donate_troop_template_names, missing_templates
from app.ui.qt.point_picker import PointPickerDialog
from app.ui.qt.template_capture import TemplateCaptureDialog
from app.ui.qt.theme import SPACING, TOKENS
from app.ui.qt.widgets import Card, PageTitle, SectionTitle, ToggleSwitch, hint_label, muted_label, neutral_button, primary_button, scroll_page, spin_box
from app.utils.logger import setup_logger
from app.utils.profile_settings_store import BB_WALL_THRESHOLD_K_MAX, ATTACK_MAX_SKIPS_MAX, ATTACK_MIN_DARK_K_MAX, ATTACK_MIN_LOOT_K_MAX, CLAN_MIN_ELIXIR_K_MAX, CLAN_DONATE_COUNT_MAX, CLAN_DONATE_INTERVAL_M_MAX, CLAN_DONATE_INTERVAL_M_MIN, CLAN_REQUEST_INTERVAL_M_MAX, CLAN_REQUEST_INTERVAL_M_MIN, EARTHQUAKE_METHOD_OPTIONS, RESERVE_BUILDERS_MAX, WALL_UPGRADE_THRESHOLD_M_MAX, ProfileSettings, load_profile_settings, save_profile_settings, UPGRADE_ORDER_CHEAPEST, UPGRADE_ORDER_PRICIEST, CLAN_DONATE_TROOP_AUTO, CLAN_DONATE_TROOP_OPTIONS
from app.utils.window_settings_store import clear_window_selection, load_window_selection, save_window_selection
logger = setup_logger('SettingsPage')
# Display label -> the key stored in settings.json (see app.core.clan).
CLAN_TROOP_CHOICES = tuple(('Auto (first troop found)' if key == CLAN_DONATE_TROOP_AUTO else key.title(), key)
                           for key in CLAN_DONATE_TROOP_OPTIONS)

class WindowInfoDialog(QDialog):
    '''Read-only view of every child window/surface under a selected top-level window.'''
    
    def __init__(self, parent, candidate, descendants):
        super().__init__(parent)
        self.setWindowTitle('Window info')
        self.setModal(True)
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        layout.setSpacing(SPACING['sm'])
        header = QLabel(f'''Top-level: {candidate.title or '(no title)'}\nClass: {candidate.top_class}    hwnd={candidate.top_hwnd}''')
        header.setWordWrap(True)
        header.setStyleSheet(f'''color: {TOKENS['text']};''')
        layout.addWidget(header)
        count = len(descendants)
        surfaces = sum([ 1 for d in descendants if d.is_surface ])
        summary = muted_label(f'''{count} child window(s), {surfaces} game surface(s). Surfaces are marked [surface].''')
        layout.addWidget(summary)
        listing = QListWidget()
        listing.setObjectName('WindowInfoList')
        mono = QFont('Consolas')
        mono.setStyleHint(QFont.StyleHint.Monospace)
        listing.setFont(mono)
        if descendants:
            for d in descendants:
                item = QListWidgetItem(d.display_label())
                if d.is_surface:
                    item.setForeground(QColor(TOKENS['primary']))
                listing.addItem(item)
        else:
            listing.addItem(QListWidgetItem('No child windows found under this window.'))
        layout.addWidget(listing, stretch = 1)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = neutral_button('Close', parent = self)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


def _pinned_row(candidates, saved):
    '''Row of the window the pin resolves to, or -1: the first game window the pin matches
    (``WindowSelection.matches``), as ``WindowService._resolve_hwnd`` picks it (game windows
    are listed first).'''
    if not saved.is_set():
        return -1
    return next((i for (i, cand) in enumerate(candidates) if cand.is_game and saved.matches(cand)), -1)


class SettingsPage(QWidget):
    
    def __init__(self, parent = None):
        super().__init__(parent)
        self._candidates = []
        self._display = DisplayService()
        # Held here rather than in a widget: a picked point is data, not a control.
        self._clan_chat_point = None
        self._clan_chat_point_aspect = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        outer.setSpacing(SPACING['md'])
        outer.addWidget(PageTitle('Settings'))
        # The settings cards outgrew the fixed window (upgrade-order/reserve controls) —
        # scroll like the Run page instead of compressing cards into overlap.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING['md'])
        layout.addWidget(self._build_earthquake_card())
        layout.addWidget(self._build_loot_filter_card())
        layout.addWidget(self._build_clan_card())
        layout.addWidget(self._build_window_card())
        layout.addWidget(self._build_app_card())
        layout.addStretch()
        outer.addWidget(scroll_page(content))

    
    def _build_earthquake_card(self):
        card = Card()
        card.card_layout.addWidget(SectionTitle('Earthquake placement'))
        self._earthquake = QComboBox()
        self._earthquake.addItems(list(EARTHQUAKE_METHOD_OPTIONS))
        card.card_layout.addWidget(self._earthquake)
        quake_hint = hint_label('Learn: each raid plays the curve or the random placement, more often the one that took more of the bases\' loot so far (read on the results screen).')
        card.card_layout.addWidget(quake_hint)
        card.card_layout.addWidget(SectionTitle('Wall upgrade threshold'))
        wall_hint = hint_label('With "Upgrade walls" on, only spend time on a wall pass once gold or elixir reaches this amount — a pass opens the builder menu and reads it, which costs far longer than a raid, so it is not worth doing on loot that cannot buy a wall. 0 = only upgrade when storages are full.')
        card.card_layout.addWidget(wall_hint)
        wall_row = QHBoxLayout()
        self._wall_threshold = spin_box(0, WALL_UPGRADE_THRESHOLD_M_MAX, suffix = 'M')
        wall_row.addWidget(self._wall_threshold)
        wall_unit = muted_label('gold or elixir')
        wall_row.addWidget(wall_unit)
        wall_row.addSpacing(SPACING['md'])
        bb_label = QLabel('Builder Base')
        wall_row.addWidget(bb_label)
        self._bb_wall_threshold = spin_box(0, BB_WALL_THRESHOLD_K_MAX, step = 100, suffix = 'k', special = 'full', width = 96, tip = 'Builder Base walls (Run page, Builder Base, Upgrade walls): from this much gold or elixir; "full" = only when a storage is full.')
        wall_row.addWidget(self._bb_wall_threshold)
        wall_row.addStretch()
        card.card_layout.addLayout(wall_row)
        card.card_layout.addWidget(SectionTitle('Upgrade order'))
        order_hint = hint_label('Priciest first soaks full storages into the biggest jobs (best when the bot farms loot faster than builders free up). The raw cost decides, whatever the resource: a dark elixir upgrade (a hero) goes first only when it is the priciest left.')
        card.card_layout.addWidget(order_hint)
        self._upgrade_order = QComboBox()
        self._upgrade_order.addItems(['Priciest first', 'Cheapest first'])
        card.card_layout.addWidget(self._upgrade_order)
        card.card_layout.addWidget(SectionTitle('Reserve builders'))
        reserve_hint = hint_label('With Auto upgrade on, keep this many builders free (the wall flow spends through them). Set 0 when your walls are maxed so every builder is used for upgrades.')
        card.card_layout.addWidget(reserve_hint)
        reserve_row = QHBoxLayout()
        self._reserve_builders = spin_box(0, RESERVE_BUILDERS_MAX)
        reserve_row.addWidget(self._reserve_builders)
        reserve_unit = muted_label('builders kept free')
        reserve_row.addWidget(reserve_unit)
        reserve_row.addStretch()
        card.card_layout.addLayout(reserve_row)
        self._add_save_row(card)
        return card

    
    def _add_save_row(self, card):
        '''Save and Reset under a card: Save writes every card's fields (one profile file),
        Reset reloads every profile field from it.'''
        btn_row = QHBoxLayout()
        btn_save = primary_button('Save', parent = card)
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)
        btn_reset = neutral_button('Reset', parent = card)
        btn_reset.clicked.connect(self._reload)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        card.card_layout.addLayout(btn_row)

    def _build_app_card(self):
        '''App-wide preferences, kept outside the profile (QSettings "BasePilot/App").'''
        from PySide6.QtCore import QSettings
        card = Card()
        card.card_layout.addWidget(SectionTitle('App'))
        self._app_settings = QSettings('BasePilot', 'App')
        self._check_updates = ToggleSwitch('Check for a new version at launch', parent = card)
        self._check_updates.setChecked(self._app_settings.value('checkUpdates', True, type = bool))
        self._check_updates.toggled.connect(lambda on: self._app_settings.setValue('checkUpdates', bool(on)))
        card.card_layout.addWidget(self._check_updates)
        hint = hint_label('One request to GitHub for the latest release of BasePilot, nothing about you or your account.')
        card.card_layout.addWidget(hint)
        return card

    def _build_loot_filter_card(self):
        '''Minimum loot a base must hold before the bot spends an army on it.'''
        card = Card()
        card.card_layout.addWidget(SectionTitle('Minimum loot to attack'))
        hint = hint_label('On the battle-prep screen the bot reads how much loot the base holds and presses Next while it is under these amounts, so an army is never spent on a 40k base. Needs the OCR models and a captured nextbase.png — without either it attacks every base and says so in the log. Set both to 0 to attack anything.')
        card.card_layout.addWidget(hint)
        gold_row = QHBoxLayout()
        self._attack_min_gold = spin_box(0, ATTACK_MIN_LOOT_K_MAX, step = 50, suffix = 'k', special = 'any')
        gold_row.addWidget(self._attack_min_gold)
        gold_unit = muted_label('gold')
        gold_row.addWidget(gold_unit)
        gold_row.addStretch()
        card.card_layout.addLayout(gold_row)
        elixir_row = QHBoxLayout()
        self._attack_min_elixir = spin_box(0, ATTACK_MIN_LOOT_K_MAX, step = 50, suffix = 'k', special = 'any')
        elixir_row.addWidget(self._attack_min_elixir)
        elixir_unit = muted_label('elixir')
        elixir_row.addWidget(elixir_unit)
        elixir_row.addStretch()
        card.card_layout.addLayout(elixir_row)
        dark_row = QHBoxLayout()
        self._attack_min_dark = spin_box(0, ATTACK_MIN_DARK_K_MAX, suffix = 'k', special = 'any')
        dark_row.addWidget(self._attack_min_dark)
        dark_unit = muted_label('dark elixir')
        dark_row.addWidget(dark_unit)
        dark_row.addStretch()
        card.card_layout.addLayout(dark_row)
        skips_row = QHBoxLayout()
        self._attack_max_skips = spin_box(0, ATTACK_MAX_SKIPS_MAX)
        skips_row.addWidget(self._attack_max_skips)
        skips_unit = hint_label('bases skipped per raid at most — every Next costs another search fee')
        skips_row.addWidget(skips_unit)
        skips_row.addStretch()
        card.card_layout.addLayout(skips_row)
        self._add_save_row(card)
        return card


    def _build_clan_card(self):
        '''Clan assist preferences. The toggles that arm it live on the Run page, next
        to the other per-run modes; what lives here is the calibration and the knobs
        that rarely change.'''
        card = Card()
        card.card_layout.addWidget(SectionTitle('Clan assist'))
        hint = hint_label('Donates to your clanmates\' requests and asks for reinforcements between raids. Turn it on per run with "Auto donate" / "Auto request troops" on the Run page.')
        card.card_layout.addWidget(hint)
        card.card_layout.addWidget(SectionTitle('Templates'))
        tpl_hint = hint_label('Clan assist clicks buttons it matches from the game art, and a full set of crops ships for 16:9 clients — so there is usually nothing to do here. Capture your own if you play at 16:10, if a bundled template does not match your client, or to add a troop you want to donate: open the game on the screen that shows the button, drag a box around it, save.')
        card.card_layout.addWidget(tpl_hint)
        tpl_row = QHBoxLayout()
        self._clan_templates_label = hint_label('')
        tpl_row.addWidget(self._clan_templates_label, stretch = 1)
        btn_capture = primary_button('Capture templates', parent = card)
        btn_capture.clicked.connect(self._on_capture_templates)
        tpl_row.addWidget(btn_capture)
        card.card_layout.addLayout(tpl_row)
        card.card_layout.addWidget(SectionTitle('Chat button (fallback)'))
        chat_hint = hint_label('Only used when the clan menu button cannot be matched — a hand-picked spot to click instead. Open the game, click "Pick chat button", then click the clan menu button in the screenshot. Re-pick it if you switch the game between 16:9 and 16:10.')
        card.card_layout.addWidget(chat_hint)
        chat_row = QHBoxLayout()
        self._clan_chat_label = muted_label('Not set')
        chat_row.addWidget(self._clan_chat_label)
        chat_row.addStretch()
        btn_pick = neutral_button('Pick chat button', parent = card)
        btn_pick.clicked.connect(self._on_pick_chat_button)
        chat_row.addWidget(btn_pick)
        btn_clear = neutral_button('Clear', parent = card)
        btn_clear.clicked.connect(self._on_clear_chat_button)
        chat_row.addWidget(btn_clear)
        card.card_layout.addLayout(chat_row)
        self._clan_dry_run = ToggleSwitch('Dry run — read the chat and log what it would click', parent = card)
        card.card_layout.addWidget(self._clan_dry_run)
        dry_hint = hint_label('Leave this on for the first run after calibrating: the bot opens the chat, logs the Donate / Request buttons it recognises, and clicks nothing. Check the Logs page, then turn it off.')
        card.card_layout.addWidget(dry_hint)
        card.card_layout.addWidget(SectionTitle('Donate troop'))
        troop_hint = hint_label('Whatever you captured as donatetroop*.png — every one of them is tried in the donate panel, so capture a crop for each troop you are happy to give away. The list below is only a fallback for when none has been captured: it reuses the deploy-bar icons, which are the same troops drawn on a different background and match less reliably.')
        card.card_layout.addWidget(troop_hint)
        self._clan_troop = QComboBox()
        self._clan_troop.addItems([label for (label, _key) in CLAN_TROOP_CHOICES])
        self._clan_troop.currentIndexChanged.connect((lambda _idx: self._update_clan_templates_label()))
        card.card_layout.addWidget(self._clan_troop)
        count_row = QHBoxLayout()
        self._clan_donate_count = spin_box(0, CLAN_DONATE_COUNT_MAX, special = 'until grey')
        count_row.addWidget(self._clan_donate_count)
        count_unit = muted_label('troops per request — "until grey" gives until the game greys the troop out (it is full)')
        count_row.addWidget(count_unit)
        count_row.addStretch()
        card.card_layout.addLayout(count_row)
        card.card_layout.addWidget(SectionTitle('Elixir floor'))
        elixir_hint = hint_label('Only donate while the HUD shows at least this much elixir, so giving troops away never eats the loot you are farming for. Read before the clan menu opens; needs the OCR models — without them the check is skipped and logged. 0 turns it off.')
        card.card_layout.addWidget(elixir_hint)
        elixir_row = QHBoxLayout()
        self._clan_min_elixir = spin_box(0, CLAN_MIN_ELIXIR_K_MAX, step = 50, suffix = 'k', special = 'off')
        elixir_row.addWidget(self._clan_min_elixir)
        elixir_unit = muted_label('elixir needed before donating')
        elixir_row.addWidget(elixir_unit)
        elixir_row.addStretch()
        card.card_layout.addLayout(elixir_row)
        card.card_layout.addWidget(SectionTitle('How often'))
        interval_hint = hint_label('Checked between raids, from the home screen. Requests are asked for far less often than clanmates ask you — the castle only holds so much.')
        card.card_layout.addWidget(interval_hint)
        donate_row = QHBoxLayout()
        self._clan_donate_interval = spin_box(CLAN_DONATE_INTERVAL_M_MIN, CLAN_DONATE_INTERVAL_M_MAX, suffix = 'm', special = 'every raid')
        donate_row.addWidget(self._clan_donate_interval)
        donate_unit = muted_label('between donation visits — "every raid" donates on every trip home')
        donate_row.addWidget(donate_unit)
        donate_row.addStretch()
        card.card_layout.addLayout(donate_row)
        request_row = QHBoxLayout()
        self._clan_request_interval = spin_box(CLAN_REQUEST_INTERVAL_M_MIN, CLAN_REQUEST_INTERVAL_M_MAX, suffix = 'm')
        request_row.addWidget(self._clan_request_interval)
        request_unit = muted_label('between reinforcement requests')
        request_row.addWidget(request_unit)
        request_row.addStretch()
        card.card_layout.addLayout(request_row)
        self._add_save_row(card)
        return card


    def _on_capture_templates(self):
        TemplateCaptureDialog.open(self.window())
        self._update_clan_templates_label()


    def _update_clan_templates_label(self):
        '''Say plainly which crops are still missing — clan assist does nothing until
        the ones its errands need are on disk.'''
        troop = CLAN_TROOP_CHOICES[max(0, self._clan_troop.currentIndex())][1]
        missing = missing_templates(donate = True, request = True, donate_troop = troop,
                                    have_chat_point = bool(self._clan_chat_point))
        troops = donate_troop_template_names()
        troop_note = f'''{len(troops)} troop(s) captured''' if troops else 'no troop captured'
        if not missing:
            self._clan_templates_label.setText(f'''All templates captured — {troop_note}.''')
            return None
        self._clan_templates_label.setText(f'''Missing: {', '.join(missing)} ({troop_note})''')


    def _update_chat_point_label(self):
        point = self._clan_chat_point
        if not point:
            self._clan_chat_label.setText('Not set — clan assist stays idle until you pick it.')
            return None
        aspect = self._clan_chat_point_aspect
        pretty = aspect_label(aspect)
        self._clan_chat_label.setText(f'''Set: {point[0] * 100:.1f}% x, {point[1] * 100:.1f}% y ({pretty})''')


    def _on_pick_chat_button(self):
        picked = PointPickerDialog.pick(self.window(), title = 'Pick the clan chat button',
                                        hint = 'Click the clan chat button in the screenshot below — the one that opens the chat panel on the left of the game. Press Refresh if the game has moved since this was captured.')
        if picked is None:
            return None
        (fx, fy, aspect) = picked
        self._clan_chat_point = [float(fx), float(fy)]
        self._clan_chat_point_aspect = aspect
        self._update_chat_point_label()
        self._flash_status_bar('Chat button picked — press Save')


    def _on_clear_chat_button(self):
        self._clan_chat_point = None
        self._clan_chat_point_aspect = None
        self._update_chat_point_label()
        self._flash_status_bar('Chat button cleared — press Save')


    def _build_window_card(self):
        card = Card()
        card.card_layout.addWidget(SectionTitle('Game window'))
        hint = hint_label("If the bot can't find Clash of Clans, pick the Google Play Games window below and press Test. Windows with a game surface are listed first.")
        card.card_layout.addWidget(hint)
        self._window_list = QListWidget()
        self._window_list.setObjectName('WindowList')
        self._window_list.setMinimumHeight(140)
        self._window_list.currentRowChanged.connect((lambda _: self._update_window_buttons()))
        card.card_layout.addWidget(self._window_list)
        self._window_status = hint_label('')
        card.card_layout.addWidget(self._window_status)
        row = QHBoxLayout()
        self._btn_refresh = neutral_button('Refresh', parent = card)
        self._btn_refresh.clicked.connect(self._refresh_windows)
        row.addWidget(self._btn_refresh)
        self._btn_test = neutral_button('Test', parent = card)
        self._btn_test.clicked.connect(self._on_test_window)
        row.addWidget(self._btn_test)
        self._btn_info = neutral_button('Info', parent = card)
        self._btn_info.clicked.connect(self._on_window_info)
        row.addWidget(self._btn_info)
        self._btn_use = primary_button('Use this window', parent = card)
        self._btn_use.clicked.connect(self._on_use_window)
        row.addWidget(self._btn_use)
        row.addStretch()
        self._btn_auto = neutral_button('Auto-detect', parent = card)
        self._btn_auto.clicked.connect(self._on_auto_detect)
        row.addWidget(self._btn_auto)
        card.card_layout.addLayout(row)
        disp_hint = hint_label("Ultrawide / 21:9 monitor? Google Play Games locks the game to your display's aspect at launch, so it renders 21:9 (unsupported). Fix: click below to switch to 16:9, FULLY close and reopen Clash, then restore your display — the running game stays 16:9.")
        card.card_layout.addWidget(disp_hint)
        disp_row = QHBoxLayout()
        self._btn_disp_169 = neutral_button('Switch display to 16:9', parent = card)
        self._btn_disp_169.clicked.connect(self._on_switch_display_169)
        disp_row.addWidget(self._btn_disp_169)
        self._btn_disp_restore = neutral_button('Restore my display', parent = card)
        self._btn_disp_restore.clicked.connect(self._on_restore_display)
        disp_row.addWidget(self._btn_disp_restore)
        disp_row.addStretch()
        card.card_layout.addLayout(disp_row)
        return card

    
    def showEvent(self, event):
        super().showEvent(event)
        self._reload()
        self._refresh_windows()

    
    def _reload(self):
        '''Every profile field of the page from settings.json.'''
        settings = load_profile_settings()
        idx = self._earthquake.findText(settings.earthquake_method)
        if idx >= 0:
            self._earthquake.setCurrentIndex(idx)
        self._wall_threshold.setValue(settings.wall_upgrade_threshold_m)
        self._bb_wall_threshold.setValue(settings.bb_wall_threshold_k)
        self._reserve_builders.setValue(settings.reserve_builders)
        self._upgrade_order.setCurrentIndex(1 if settings.upgrade_order == UPGRADE_ORDER_CHEAPEST else 0)
        self._clan_chat_point = list(settings.clan_chat_point) if settings.clan_chat_point else None
        self._clan_chat_point_aspect = settings.clan_chat_point_aspect
        self._update_chat_point_label()
        self._clan_dry_run.setChecked(bool(settings.clan_dry_run))
        keys = [key for (_label, key) in CLAN_TROOP_CHOICES]
        self._clan_troop.setCurrentIndex(keys.index(settings.clan_donate_troop) if settings.clan_donate_troop in keys else 0)
        self._clan_donate_count.setValue(settings.clan_donate_count)
        self._clan_min_elixir.setValue(settings.clan_min_elixir_k)
        self._clan_donate_interval.setValue(settings.clan_donate_interval_m)
        self._clan_request_interval.setValue(settings.clan_request_interval_m)
        self._update_clan_templates_label()
        self._attack_min_gold.setValue(settings.attack_min_gold_k)
        self._attack_min_elixir.setValue(settings.attack_min_elixir_k)
        self._attack_min_dark.setValue(settings.attack_min_dark_k)
        self._attack_max_skips.setValue(settings.attack_max_skips)


    def _on_save(self):
        # One profile file: every card's fields go in together, or the ones left out
        # would be written back as defaults.
        save_profile_settings(ProfileSettings(
            earthquake_method = self._earthquake.currentText(),
            wall_upgrade_threshold_m = self._wall_threshold.value(),
            bb_wall_threshold_k = self._bb_wall_threshold.value(),
            reserve_builders = self._reserve_builders.value(),
            upgrade_order = UPGRADE_ORDER_CHEAPEST if self._upgrade_order.currentIndex() == 1 else UPGRADE_ORDER_PRICIEST,
            clan_dry_run = self._clan_dry_run.isChecked(),
            clan_chat_point = self._clan_chat_point,
            clan_chat_point_aspect = self._clan_chat_point_aspect,
            clan_donate_troop = CLAN_TROOP_CHOICES[max(0, self._clan_troop.currentIndex())][1],
            clan_donate_count = self._clan_donate_count.value(),
            clan_min_elixir_k = self._clan_min_elixir.value(),
            clan_donate_interval_m = self._clan_donate_interval.value(),
            clan_request_interval_m = self._clan_request_interval.value(),
            attack_min_gold_k = self._attack_min_gold.value(),
            attack_min_elixir_k = self._attack_min_elixir.value(),
            attack_min_dark_k = self._attack_min_dark.value(),
            attack_max_skips = self._attack_max_skips.value()))
        self._flash_status_bar('Saved')

    
    def _selected_candidate(self):
        row = self._window_list.currentRow()
        if 0 <= row and row < len(self._candidates):
            pass
        else:
            return None
        return self._candidates[row]

    
    def _update_window_buttons(self):
        cand = self._selected_candidate()
        has_sel = cand is not None
        self._btn_test.setEnabled(has_sel)
        self._btn_use.setEnabled(has_sel)
        self._btn_info.setEnabled(has_sel)

    
    def _refresh_windows(self):
        
        try:
            self._candidates = WindowService().enumerate_windows()
            saved = load_window_selection()
            self._window_list.clear()
            for cand in self._candidates:
                item = QListWidgetItem(cand.display_label())
                if not cand.is_game:
                    item.setForeground(self._muted_brush())
                self._window_list.addItem(item)
            selected_row = _pinned_row(self._candidates, saved)
            if selected_row >= 0:
                self._window_list.setCurrentRow(selected_row)
            if not self._candidates:
                self._window_status.setText('No visible windows found. Open the game, then Refresh.')
            elif saved.is_set():
                self._window_status.setText(f'''Pinned window: {saved.title or '(saved)'}''')
            else:
                self._window_status.setText('Using auto-detect.')
            self._update_window_buttons()
            return None
        except Exception as exc:
            logger.warning(f'''Could not enumerate windows: {exc}''')
            self._candidates = []

    
    def _muted_brush(self):
        return QColor(TOKENS['text_muted'])

    
    @staticmethod
    def _size_label(w, h):
        if not w or not h:
            return 'size unavailable'
        aspect = resolve_aspect_key(w, h)
        if aspect is None:
            return f'''{w}x{h} (not ~16:9/16:10)'''
        pretty = aspect_label(aspect)
        return f'''{w}x{h} ({pretty})'''

    
    def _on_test_window(self):
        cand = self._selected_candidate()
        if cand is None:
            return None
        if not cand.is_game:
            self._window_status.setText('No Google Play Games surface (CROSVM) under this window — pick the game window.')
            return None
        ws = WindowService()
        surface_size = ws.window_pixel_size(cand.child_hwnd)
        if surface_size is None:
            self._window_status.setText('Could not read the window size. Is the game minimized?')
            return None
        sub_size = None
        try:
            for d in ws.enumerate_descendants(cand.top_hwnd):
                if d.cls.lower() == 'subwin':
                    sub_size = (d.width, d.height)
                    break
        except Exception as exc:  # the surface's own size is still worth showing
            logger.warning(f'''Could not inspect subWin: {exc}''')
        (sw, sh) = surface_size
        lines = [
            f'''Capture target {cand.child_class}: {self._size_label(sw, sh)}''']
        if sub_size is not None:
            lines.append(f'''Inner subWin: {self._size_label(*sub_size)}''')
        if resolve_aspect_key(sw, sh) is None:
            lines.append('Surface aspect unsupported — try resizing the game window.')
        else:
            lines.append('Surface OK to use.')
        self._window_status.setText('\n'.join(lines))

    
    def _on_switch_display_169(self):
        (ok, size, reason) = self._display.switch_to_16_9()
        if ok and reason == 'already_16_9':
            self._window_status.setText('Your display is already 16:9 — just (re)launch Clash in Google Play Games and it will render 16:9.')
        elif ok:
            self._window_status.setText(f'''Display set to {size[0]}x{size[1]} (16:9). Now FULLY close and reopen Clash in Google Play Games, then click "Restore my display".''')
        elif reason == 'no_16_9_mode':
            self._window_status.setText('Your display driver offers no 16:9 mode — use a 16:9 monitor for the game instead.')
        else:
            self._window_status.setText('Could not switch the display resolution.')
        self._flash_status_bar('Display set to 16:9' if ok else 'Display switch failed')


    def _on_restore_display(self):
        (ok, size, reason) = self._display.restore()
        if ok:
            self._window_status.setText(f'''Display restored to {size[0]}x{size[1]}. If you relaunched Clash while in 16:9 it stays 16:9 — press Test to confirm, then Start.''')
        elif reason == 'nothing_to_restore':
            self._window_status.setText('Nothing to restore — you have not switched your display (or it was already restored).')
        else:
            self._window_status.setText('Could not restore the display. Use Windows Settings → Display to set it back.')
        self._flash_status_bar('Display restored' if ok else 'Restore failed')


    def _on_window_info(self):
        cand = self._selected_candidate()
        if cand is None:
            return None

        try:
            descendants = WindowService().enumerate_descendants(cand.top_hwnd)
        except Exception as exc:  # the dialog still shows the window itself
            logger.warning(f'''Could not enumerate descendants: {exc}''')
            descendants = []
        WindowInfoDialog(self.window(), cand, descendants).exec()

    
    def _on_use_window(self):
        cand = self._selected_candidate()
        if cand is None:
            return None
        save_window_selection(cand.to_selection())
        self._window_status.setText(f'''Pinned: {cand.title or '(no title)'}. Press Test to verify.''')
        self._flash_status_bar('Window saved')

    
    def _on_auto_detect(self):
        clear_window_selection()
        self._window_status.setText('Cleared — using auto-detect.')
        self._flash_status_bar('Auto-detect')
        self._refresh_windows()

    
    def _flash_status_bar(self, msg):
        win = self.window()
        if isinstance(win, QMainWindow):
            if not win.statusBar() is None:
                win.statusBar().showMessage(msg, 1500)
                return None
            return None


