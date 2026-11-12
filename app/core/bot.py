import time
from datetime import datetime
from app.core.battle_rewards import BattleRewards
import random
import threading
import cv2
import numpy as np
from app.config import ASPECT_16_10, Config
from app.core.clan import ClanAssistant, ClanOptions, missing_templates
from app.core.loot_filter import TEMPLATE_NEXT_BASE, LootFilter, combine_reads, meets, read_enemy_loot
from app.core.strategies import EdragStrategy, TroopSpamStrategy, _EDRAG_DELAY
from app.core import bb_learning, bb_results, bb_scout, bb_strategy, hv_results
from app.core.build_panel import TAB_BUILDINGS, BuildPanelUpgrader, find_close, gem_prompt_visible, panel_tab, wall_upgrade_button
from app.core.upgrade_menu import RESOURCE_ELIXIR, RESOURCE_GOLD
from app.core.upgrader import AUTO_UPGRADE_MODES, LIVE_UPGRADE_MODES, MODE_OFF, UpgradeAdvisor
from app.core.village_state import is_october_hud, read_hud_triplet_stable, read_village_state, read_village_state_stable, storages_full
from app.services.input import InputService
from app.services.vision import BOTTOM_HALF_BOT_TEMPLATES, TOP_HALF_BOT_TEMPLATES, VisionService
from app.services.window import WindowService
from app.utils import battle_history
from app.utils.common import get_template_path
from app.utils.logger import setup_logger
from app.utils.profile_settings_store import EARTHQUAKE_METHOD_CURVE, EARTHQUAKE_METHOD_LEARN, EARTHQUAKE_METHOD_RANDOM
logger = setup_logger('BotCore')
_HOME_VILLAGE_BUILDER_TEMPLATES = ('builder.png', 'gbuilder.png')
_BB_CARD_SWAP_TEMPLATE = 'bbswap.png'  # green swap button under every troop card before the first deploy
_BB_CARD_ABOVE_SWAP = 91  # ref px from that button up to the card art (tapping the button opens the swap menu)
_BB_RETURN_HOME_TEMPLATE = 'breturnhome.png'
# s between label reads of Return Home while its art is not matched: a safety net (the art
# matches the results screen), and each read stalled the fight's ability and speed taps
_BB_RETURN_HOME_OCR_EVERY = 10
_BB_RESULTS_LEAVE_TIMEOUT = 8.0  # s for the results screen to go once Return Home is tapped
_BB_BATTLE_MAX_SECONDS = 360  # two stages of ~2 min, the scouting and the transitions; then recovery
_BB_REDEPLOY_AFTER = 8  # s after a deploy before swap buttons on the bar mean a new stage
_BB_TEMPLATE_SUPPRESS_PAD = 0.1
_BB_FULL_ELIXIR_CART_TEMPLATES = ('fullecart.png', 'fullecart2.png', 'fullecart3.png')
_BB_COLLECT_TEMPLATE = 'collect.png'
_BB_STAR_BONUS_TEMPLATE = 'bstar.png'
_BB_BATTLE_MACHINE_TEMPLATE = 'battlemachine.png'
_BB_FLYING_MACHINE_TEMPLATE = 'flyingmachine.png'
# The speed button of a stage's last minute, while it reads 1x: a tap makes it 4x. Live GPG
# 1227x767: 1.00 on "1x", 0.72 on "4x", under 0.4 without the button.
_BB_SPEED_TEMPLATE = 'bbspeed1x.png'
_BB_SPEED_MIN = 0.9
_BB_SPEED_RETRY = 3  # s before another tap if it still reads 1x (a lost tap)
_BB_LANDED_CHECK_AFTER = 0.6  # s after a deploy before the bar is read again (a landed troop's card is green by then)
_BB_SIDES_TRIED = 3  # sides of the base the first troop tries before a map edge
_NO_MASTER_BUILDER = 0.7  # mbuilder.png under this: not the Builder Base's home
_VILLAGE_DETECT_RETRIES = 3
_BB_CORE_WEIGHTS = {'core': 3.0, 'reach': 0.3}  # the scouting's core weight of these plans (best: its own, 1.2)
_BB_STILL_TIMEOUT = 2.0  # s to wait for the view to stop moving
_BB_STILL_DIFF = 1.5  # mean grey change (160x100) between two frames 0.25 s apart under which the view is still
_STAR_BONUS_THRESHOLD = 0.75
_TROOP_FAILURE_LIMIT = 4
_TROOP_RETRY_WAIT_SECONDS = 15  # training is instant since the Mar 2025 "Clash Anytime" update — this only lets the UI settle
_RELOAD_GRACE_SECONDS = 180  # let a quick phone check finish before reconnecting over it
_WALL_SINGLE_MAX = 5  # walls bought one by one per wall pass (loot is re-checked before each)
# How deep the Wall row sits depends on the village: it is the last entry of "Other
# upgrades", and that list grows with every building the village owns. A fixed cap of 8
# stops was two nudges short on a TH15 account (live: the row first appeared at stop 9,
# and the list ended at stop 10) — 705 passes in one log gave up with "OCR missed at all
# scroll positions" without ever reaching it. Scrolling now stops when the list stops
# moving, and this is only the safety cap.
_WALL_MENU_SCROLL_STEPS = 20
# Mean absolute pixel difference over the menu ROI between two stops. Live separation is
# wide: 9.7-23.8 while the list is still travelling, 0.9-1.5 once it has hit the bottom.
_WALL_MENU_BOTTOM_DIFF = 4.0
_WALL_MENU_OPEN_SECONDS = 1.2  # the builder popup renders ~1s after the click (0.8s frames are still empty)
_WALL_MENU_WHEEL_CLICKS = 2  # ~3-4 rows per nudge; the OCR band spans the whole popup so a nudge cannot jump the Wall row past it
_WALL_ROW_STABLE_TOL = 30  # ref px: max y drift between consecutive frames before the row is trusted for a click
_AUTO_UPGRADE_SCAN_INTERVAL_SECONDS = 600  # full popup scan is OCR-heavy (~15-25s); keep it rare vs the ~35s attack cycle
_WALL_RETRY_SECONDS = 600  # a wall pass that bought nothing fails the same way next raid; wait before paying for another
_BUILD_PANEL_POLLS = 6  # ~3 s for the Build panel to slide in (its title read, or its tab art)
_TAP_EATEN_AFTER = 3.0  # s without the next screen: a tap a selection on screen ate (it deselects); tapped again
# Oct 2026 HUD: the profile (Town Hall and XP badge, top left) holds Settings; its centre in
# screen heights from the top-left corner (live 1227x767: (61, 72), both villages)
_PROFILE_BADGE = (0.08, 0.094)
_PROFILE_TABS_Y = 0.22  # the profile window's tabs (My Profile, Social, Inbox, Settings) sit above this
# Oct 2026 HUD: the Build panel's card list fills the right edge, above its tab bar.
_BUILD_PANEL_ROI_FRAC = (0.70, 0.08, 0.30, 0.80)  # x, y, w, h as fractions of the capture
_LABEL_FALLBACK_AFTER = 1.0  # s of template misses before also reading the control's label (OCR is slower)
_BATTLE_LABEL_AFTER = 20  # s; during a live battle none of the end buttons shows for a while, and OCR on every poll loads the CPU next to the game
_LOOT_STALL = 12.0  # s with the base's available loot not dropping: the troops took what they could reach
_BATTLE_GIVE_UP = 60.0  # s with no star (Surrender only) and no loot coming before surrendering
_BATTLE_LONGEST = 200.0  # s: past a battle's 3 minutes, end it whatever shows
_LOOT_POLL = 1.0  # s between two reads of the available loot
_HV_ARMIES = {1: 'sneaky', 2: 'superminion', 3: 'valkyrie', 4: 'edrag'}  # attack method -> army, for the learned Earthquakes
_BATTLE_CARD_MAX_X = 0.28  # Battle menu: the Battle card ends here, the Ranked Battle card starts at ~0.29 W (16:10 live)
_IDLE_RECHECK_SECONDS = 300  # while idling (storages full, nothing startable): wake, recover the screen, re-read state
_FULL_STOP_FRAMES = 2  # "Stop when storages are full": both bars full on this many frames in a row
_FULL_STOP_GAP = 0.5  # s between those frames
_CLAN_UNCALIBRATED_BACKOFF_SECONDS = 3600  # no chat button picked: say so once, not once per raid
# "never done" for the clan clocks. They are compared against time.monotonic(), which
# restarts at boot, so a plain 0 means "done at boot" — on a machine up for less than the
# request interval that silently held reinforcement requests back for the first half hour.
_CLAN_CLOCK_NEVER = float('-inf')
_NEXT_CLEAR_POLLS = 8  # ~4s for the skipped base's controls to leave the screen
_NEXT_SETTLE_SECONDS = 1.0  # after the new base's controls appear, before reading its loot
_LOOT_READ_POLLS = 6  # ~3s for the loot panel to render before calling it unreadable
_LOOT_READ_SAMPLES = 3  # reads folded into one verdict (a single read drops digits ~half the time)
# Loot-tracker plausibility caps per snapshot interval (one battle): a raid tops out
# well under these even with boosts — anything larger is an OCR misread that slipped
# past the ≥0 filter (live repro: "+15.5M elixir" in one battle).
_LOOT_DELTA_MAX_MAIN = 3000000
_LOOT_DELTA_MAX_DARK = 50000

# The game's own Android dialogs when it drops the server: "Connection lost / Try again"
# and, after a few idle minutes, "Anyone there? / Reload game". Their only action is a
# cyan text button 0.1-0.15 H under the title, left-aligned with it; reloading spends nothing.
_RECONNECT_TITLES = ('Connection lost', 'Anyone there')


def reconnect_button(vision, frame):
    '''Center of the reconnect button of a connection dialog, or None.'''
    (h, w) = frame.shape[:2]
    for title in _RECONNECT_TITLES:
        (tx, ty) = vision.find_label(frame, title, region = (int(0.2 * w), int(0.3 * h), int(0.6 * w), int(0.35 * h)))
        if tx is None:
            continue
        (x0, x1) = (max(0, int(tx - 0.12 * w)), min(w, int(tx + 0.15 * w)))
        (y0, y1) = (min(h, int(ty + 0.04 * h)), min(h, int(ty + 0.2 * h)))
        hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        cyan = (hsv[..., 0] >= 80) & (hsv[..., 0] <= 105) & (hsv[..., 1] >= 50) & (hsv[..., 2] >= 140)
        # Only ink in the holes of the dialog's dark box (the largest dark region here) counts:
        # the window reaches past the box over the game, whose art can be cyan too (live, GPG
        # 1227x767: the light-blue Clone spell left of the box). Ink cut by the window's edge
        # is in no hole either, hence the room left under the button. Opening the dark mask
        # first (~0.006 H) cuts the thin dark outline that would join art touching the box to it.
        k = max(3, int(0.006 * h)) | 1
        dark = cv2.morphologyEx((hsv[..., 2] <= 60).astype(np.uint8), cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
        (n, regions, stats, _) = cv2.connectedComponentsWithStats(dark)
        if n < 2:
            continue
        box = regions == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        (_, rest) = cv2.connectedComponents((~box).astype(np.uint8))
        cyan &= ~np.isin(rest, np.concatenate((rest[0], rest[-1], rest[:, 0], rest[:, -1])))
        # The label is the largest line of that ink (its letters joined side by side), so specks
        # left in a hole of thick dark art joined to the box cannot pull the tap off it.
        (n, lines, stats, _) = cv2.connectedComponentsWithStats(cv2.dilate(cyan.astype(np.uint8), np.ones((1, 2 * k + 1), np.uint8)))
        if n < 2:
            continue
        cyan &= lines == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        if cyan.sum() < 20:
            continue
        (ys, xs) = np.nonzero(cyan)
        return (x0 + int((xs.min() + xs.max()) // 2), y0 + int((ys.min() + ys.max()) // 2))
    return None


def _dump_debug_frame(frame, prefix):
    '''Save a frame to the debug dir; returns the path or None. Never raises.'''
    if frame is None:
        return None
    try:
        import cv2 as _cv2
        from app.utils.common import get_user_app_data_dir
        dbg = get_user_app_data_dir() / 'debug'
        dbg.mkdir(parents = True, exist_ok = True)
        path = dbg / f'''{prefix}_{int(time.time())}.jpg'''
        _cv2.imwrite(str(path), frame, [_cv2.IMWRITE_JPEG_QUALITY, 88])
        logger.info('Debug frame saved to %s', path)
        return path
    except Exception:
        logger.debug('Debug frame dump failed', exc_info = True)
        return None


class Bot:
    '''Main Bot Logic.'''
    
    def __init__(self):
        self.config = Config()
        self.window = WindowService()
        self.stop_event = threading.Event()
        self.input = InputService(self.window, self.stop_event)
        self.vision = VisionService()
        self._battle_rewards = BattleRewards(self.window, self.input, self.stop_event)
        self.running = False
        self._earthquake_method = EARTHQUAKE_METHOD_CURVE
        self._loot_totals = (0, 0, 0)
        self._loot_prev_resources = None
        self._loot_session_start_mono = 0
        self._loot_callback = None
        self._suppress_loot_negative_error_once = False
        self.finish_reason = None  # why the last run ended on its own ("storages full"), for the UI


    def start(self, method, run_time_minutes, star_bonus = False, status_callback = None, loot_callback = None, multi_run_players = None, upgrade_walls = False, earthquake_method = EARTHQUAKE_METHOD_CURVE, builder_base = False, wall_upgrade_threshold = 0, auto_upgrade = MODE_OFF, reserve_builders = 1, state_callback = None, upgrade_order = None, clan_options = None, loot_filter = None, bb_wall_threshold = 0, stop_when_full = False):
        '''Starts the bot loop. With ``multi_run_players``, runs a full session per enabled player.
        ``run_time_minutes <= 0`` (single runs, either village) means ENDLESS: battles go on
        until the user stops the bot (with Maxer or Rusher, full storages with nothing to
        start pause them, see :meth:`_maybe_idle`). ``stop_when_full`` ends the run once gold
        and elixir are both full (a Multi-run moves on to the next account).'''
        self._status_callback = status_callback
        self._loot_callback = loot_callback
        self._state_callback = state_callback
        self._earthquake_method = earthquake_method
        self.finish_reason = None
        if not self.window.find_window():
            raise RuntimeError('Clash of Clans window not found. Please ensure the game is open.')
        self._reset_loot_session()
        self._session_id = datetime.now().isoformat(timespec = 'seconds')  # groups the session's battles in the history
        self._emit_loot_update()
        self.running = True
        self.stop_event.clear()
        unlimited = not star_bonus and multi_run_players is None and int(run_time_minutes or 0) <= 0
        duration = 900 if star_bonus else (0 if unlimited else max(1, int(run_time_minutes)) * 60)
        mr = multi_run_players is not None
        self._multi_run = mr
        self._stop_when_full = bool(stop_when_full)
        self._builder_base = builder_base
        self._wall_upgrade_threshold = max(0, int(wall_upgrade_threshold or 0))
        self._bb_wall_threshold = max(0, int(bb_wall_threshold or 0))
        self._auto_upgrade_mode = auto_upgrade if auto_upgrade in AUTO_UPGRADE_MODES else MODE_OFF
        self._auto_upgrade_last_scan = 0
        self._wall_retry_at = 0
        self._reserve_builders = max(0, int(reserve_builders or 0))
        self._walls_enabled = bool(upgrade_walls)  # not _upgrade_walls: that is the wall-pass method
        self._panel_upgrader = None
        self._reload_first_seen = None  # a dialog seen before an earlier Stop must not skip this session's grace
        self._upgrade_order = upgrade_order
        self._advisor = None  # one UpgradeAdvisor per session (it holds execution cooldowns)
        self._clan_options = clan_options if clan_options is not None else ClanOptions()
        self._loot_filter = loot_filter if loot_filter is not None else LootFilter()
        self._loot_filter_off = False
        self._bases_skipped = 0
        self._clan = None  # one ClanAssistant per session (it holds the failure counter)
        # Donate/request on the FIRST home visit of the session, then on their intervals.
        self._clan_last_donate = _CLAN_CLOCK_NEVER
        self._clan_last_request = _CLAN_CLOCK_NEVER
        logger.info(f'''Bot started. Method: {method}, Time: {'endless' if unlimited else f'{duration // 60}m'}, StopWhenFull: {self._stop_when_full}, StarBonus: {star_bonus}, MultiRun: {mr}, UpgradeWalls: {upgrade_walls}, WallThreshold: {self._wall_upgrade_threshold}, AutoUpgrade: {self._auto_upgrade_mode}, ReserveBuilders: {self._reserve_builders}, Earthquake: {earthquake_method}, BuilderBase: {builder_base}, ClanDonate: {self._clan_options.donate}, ClanRequest: {self._clan_options.request}, ClanDryRun: {self._clan_options.dry_run}, LootFilter: {self._loot_filter.summary() if self._loot_filter.enabled else 'off'}''')

        try:

            if not multi_run_players is None:
                self._ensure_correct_village(builder_base = False)
                queue = [ p for p in multi_run_players if p.enabled ]
                if not queue:
                    raise RuntimeError('Multi-run: no players marked Run')
                for player in queue:
                    self._check_stop()
                    try:
                        self._switch_account_and_load_home(player.name)
                    except InterruptedError:
                        raise
                    except Exception:
                        # one unreadable name must not cost the accounts after it
                        logger.error('Multi-run: could not switch to %r — skipping this account', player.name, exc_info = True)
                        self._recover_safely()
                        continue
                    # Each account sits in its own clan: start this player's session
                    # with a chat visit due instead of inheriting the last one's clocks.
                    self._clan_last_donate = _CLAN_CLOCK_NEVER
                    self._clan_last_request = _CLAN_CLOCK_NEVER
                    self._wall_retry_at = 0
                    self._gold_pinned = self._elixir_pinned = False  # the last account's cap is not this one's
                    self._panel_upgrader = None  # nor its failed-card cooldowns
                    self._check_stop()
                    self._run_loop(method, duration, star_bonus, upgrade_walls)
                    self._check_stop()
                    self._multi_run_builder_base_after_session()
                    self._check_stop()
            elif self._builder_base:  # [recovered: decompiler nested this single-run block inside the multi-run `if`]
                self._ensure_correct_village(builder_base = True)
                self._run_builder_base_loop(duration, star_bonus = star_bonus)
            else:
                self._ensure_correct_village(builder_base = False)
                self._run_loop(method, duration, star_bonus, upgrade_walls)
        except InterruptedError:
            logger.info('Bot stopped by user.')
        except Exception as e:
            logger.error(f'''Bot crashed: {e}''', exc_info = True)
            raise
        finally:
            self.running = False
            self._earthquake_method = EARTHQUAKE_METHOD_CURVE
            logger.info('Bot stopped.')

    
    def stop(self):
        '''Signals the bot to stop.'''
        self.running = False
        self.stop_event.set()

    
    def _reset_loot_session(self):
        '''Reset counters for a new :meth:`start` — no disk persistence.'''
        self._loot_totals = (0, 0, 0)
        self._loot_prev_resources = None
        self._loot_session_start_mono = time.monotonic()
        self._suppress_loot_negative_error_once = False
        self._last_hud_triplet = None
        self._gold_pinned = False
        self._elixir_pinned = False

    
    def _emit_loot_update(self):
        cb = getattr(self, '_loot_callback', None)
        if not cb:
            return None
        (g, el, de) = self._loot_totals
        elapsed = max(0, time.monotonic() - float(self._loot_session_start_mono))
        cb(g, el, de, elapsed)

    
    def _loot_snapshot_before_attack(self):
        '''
On home: OCR top‑right HUD, diff vs previous snapshot, accumulate non‑negative deltas,
refresh the baseline.

Called before wall upgrades (when storages full) **and** immediately before tapping
Attack so post‑raid gains are recorded **before** wall spend can make the next snapshot
look like a decrease on every resource vs that baseline (which would skip the add).

When deltas vs the previous snapshot are not all non-negative, session totals are not
incremented unless ``_suppress_loot_negative_error_once`` suppresses one skip (set after
wall upgrades for the first pre-Attack snapshot that would otherwise count as an error).
'''
        # Consecutive-frame agreement: single HUD reads get corrupted by animations
        # (live repro: elixir "115M" — an upward misread passes the ≥0 filter and
        # poisons the session totals). No stable read this cycle → just skip.
        triplet = self._read_hud_triplet_stable()
        if triplet is None:
            logger.debug('Loot tracker: no stable HUD read this cycle')
            self._emit_loot_update()
            return None
        self._record_loot(triplet)

    def _record_loot(self, triplet, village = 'home'):
        '''Add the gains since the last HUD read ``triplet`` to the session totals (see
        :meth:`_loot_snapshot_before_attack`) and push them to the UI. A Home Village gain
        (the last raid's loot) goes in the battle history too.'''
        self._last_hud_triplet = triplet
        (cur_g, cur_el, cur_de) = triplet
        prev = self._loot_prev_resources
        # Cap detection without TH-specific numbers: at a TRUE cap, consecutive
        # stable pre-attack reads pin to the identical value (raids refill the
        # entry fee back to cap); below cap every battle moves the number. The
        # full-storage icons fire from ~85% up, so they alone must not idle the
        # bot away from real remaining headroom.
        if prev is not None:
            self._gold_pinned = cur_g == prev[0]
            self._elixir_pinned = cur_el == prev[1]
        skipped_due_to_negative_delta = False
        if not prev is None:
            (lg, le, ld) = prev
            dg = cur_g - lg
            d_el = cur_el - le
            d_de = cur_de - ld
            if dg >= 0 and d_el >= 0 and d_de >= 0:
                if dg <= _LOOT_DELTA_MAX_MAIN and d_el <= _LOOT_DELTA_MAX_MAIN and d_de <= _LOOT_DELTA_MAX_DARK:
                    (tg, te, td) = self._loot_totals
                    self._loot_totals = (tg + dg, te + d_el, td + d_de)
                    if village == 'home' and (dg or d_el or d_de) and not getattr(self, '_hv_result_recorded', False):
                        # the raid's results screen was not read: its loot from the HUD instead
                        battle_history.append({'village': 'home', 'session': getattr(self, '_session_id', None), 'gold': dg, 'elixir': d_el, 'dark': d_de})
                    logger.info('Loot tracker: +%s / +%s / +%s (G/E/DE) → session %s / %s / %s', dg, d_el, d_de, self._loot_totals[0], self._loot_totals[1], self._loot_totals[2])
                else:
                    # One battle cannot earn this much — an OCR misread slipped through.
                    logger.warning('Loot tracker: implausible gain +%s/+%s/+%s discarded (OCR misread); baseline refreshed', dg, d_el, d_de)
            else:
                skipped_due_to_negative_delta = True
                logger.warning('Loot tracker: negative delta — previous gold/elixir/dark=%s/%s/%s current read=%s/%s/%s', lg, le, ld, cur_g, cur_el, cur_de)
        self._loot_prev_resources = triplet
        if village == 'home':
            self._hv_result_recorded = False  # this read took in the last raid's loot
        self._emit_loot_update()
        if skipped_due_to_negative_delta:
            if self._suppress_loot_negative_error_once:
                self._suppress_loot_negative_error_once = False
                return None
            return None
        self._suppress_loot_negative_error_once = False

    
    def _check_stop(self):
        if self.stop_event.is_set():
            raise InterruptedError('Bot stopped by user')

    
    def _update_config_size(self, frame):
        '''Reload aspect profile if screenshot size implies a different template folder.'''
        self.config.set_target_size_from_frame(frame)

    
    def _scroll_point(self):
        '''Scroll anchor in authoring space [1000,1000]; scaled to current capture.'''
        (x, y) = self.config.scale_point([
            1000,
            1000])
        return (x, y)

    
    def _nudge_view_to_reveal_attack(self):
        '''Click ``empty`` (``data.json``) and scroll at anchor to nudge village until Attack is findable.'''
        self.input.click(pause = 0.15, *self.config.get_point('empty'))
        self.input.scroll(*self._scroll_point(), 5)

    
    def _find_home_village_builder(self, frame, region):
        for name in _HOME_VILLAGE_BUILDER_TEMPLATES:
            (x, y) = self.vision.find_template(frame, name, region = region)
            if not x:
                continue
            return (x, y)
        return (None, None)

    def _live_battle_button(self, frame):
        '''Surrender, or End Battle (battle prep, or after the first star): the way out of a
        live battle. A battle that loaded after the start wait gave up shows End Battle.'''
        bottom = VisionService.bottom_half_region(frame)
        for name in ('surrender.png', 'endbattle.png'):
            (x, y) = self.vision.find_template(frame, name, region = bottom)
            if x:
                return (x, y)
        return (None, None)

    def _home_hud_visible(self, frame):
        '''Home Village screen: its builder chip, else the Battle and Build buttons together with
        no Builder Base chip (the Oct 2026 HUD redrew the chip; a stale chip template must not
        leave recovery looping on a screen that is already home).'''
        bottom = VisionService.bottom_half_region(frame)  # Oct 2026: the counters sit above Build, bottom right
        if self._find_home_village_builder(frame, bottom)[0]:
            return True
        if self.vision.find_template(frame, 'mbuilder.png', region = bottom)[0]:
            return bool(getattr(self, '_builder_base', False))  # the other village, unless that is where we farm
        return bool(self.vision.find_template(frame, 'attack.png', region = bottom)[0] and self.vision.find_template(frame, 'build.png')[0])

    
    def _build_panel_roi(self, frame):
        '''Card list of the October 2026 Build panel (right edge), in capture pixels.'''
        (h, w) = frame.shape[:2]
        (fx, fy, fw, fh) = _BUILD_PANEL_ROI_FRAC
        return (int(w * fx), int(h * fy), int(w * fw), int(h * fh))

    def _open_build_panel(self, frame):
        '''Oct 2026 HUD: tap Build (bottom right) and have its Buildings & Heroes list, which
        holds the Wall card: the panel opens on it (its title reads so; the Builder Base's
        panel has no other), or its tab is tapped. A Build tap that a selection still on
        screen ate (a wall just bought: the tap only deselects it) goes again, once the
        Build button shows with no panel. True once the list had time to render.'''
        for attempt in range(2):
            (bx, by) = self.vision.find_template(frame, 'build.png', region = VisionService.bottom_half_region(frame))
            if not bx:
                logger.info('Wall upgrade: Build button not found — skipping this pass')
                return False
            self.input.click(bx, by, pause = 0.5)
            for _ in range(_BUILD_PANEL_POLLS):
                self._check_stop()
                frame = self.window.screenshot()
                if frame is None:
                    return False
                self._update_config_size(frame)
                if panel_tab(self.vision, frame) == TAB_BUILDINGS:
                    return not self.stop_event.wait(_WALL_MENU_OPEN_SECONDS)
                (tx, ty) = self.vision.find_template(frame, 'buildings_tab.png')
                if tx:
                    self.input.click(tx, ty, pause = 0.3, rand = False)
                    return not self.stop_event.wait(_WALL_MENU_OPEN_SECONDS)
                if self.stop_event.wait(0.5):
                    return False
            if attempt == 0:
                logger.info('Wall upgrade: no Build panel after the tap — tapping Build again (a selection ate it)')
        logger.info('Wall upgrade: Buildings & Heroes not open after Build — skipping this pass')
        return False

    def _find_wall_row_once(self):
        '''One fresh screenshot → the Wall card's label read in the Build panel.

        Returns ``(frame, point)``; the frame comes back so the caller can tell a list
        that is still travelling from one that has hit its bottom without paying for a
        second capture.
        '''
        frame = self.window.screenshot()
        if frame is None:
            return (None, None)
        self._update_config_size(frame)
        # The Wall card sits in the Build panel on the right: the lowest hit, as the old popup
        # reader took.
        words = self.vision.find_words_ocr(frame, self._build_panel_roi(frame)) or []
        hits = [w for w in words if 'wall' in w.text.lower()]
        if hits:
            return (frame, max(hits, key = lambda b: b.top + b.height).center)
        return (frame, None)

    def _wall_menu_signature(self, frame):
        '''A thumbnail of the builder-menu ROI, for telling "the list moved" from "the
        list is at its end". None when there is no frame.

        The same ROI the row OCR reads, so no new geometry: the village animating behind
        the translucent popup is the only thing that changes once the list has stopped,
        and that is worth about 1.5 in mean abs difference against 10-24 for a nudge.
        '''
        if frame is None:
            return None
        (rx, ry, rw, rh) = self._build_panel_roi(frame)
        roi = frame[ry:ry + rh, rx:rx + rw]
        if not roi.size:
            return None
        return cv2.resize(roi, (48, 48)).astype(np.int16)


    def _wall_menu_scroll_point(self):
        '''Wheel target: the middle of the Build panel's card list.'''
        (fx, fy, fw, fh) = _BUILD_PANEL_ROI_FRAC
        return (int(self.config.width * (fx + fw / 2)), int(self.config.height * (fy + fh / 2)))


    def _should_upgrade_walls(self, threshold = None):
        '''The resources a wall pass may spend (a set of RESOURCE_GOLD / RESOURCE_ELIXIR, empty
        when the pass is not worth what it costs). Only those pay: walls bought with elixir
        because gold was full would drain the elixir the laboratory needs.

        A pass is expensive: it opens the builder menu, OCR-scrolls to find the Wall row,
        batches walls and confirms — far longer than a raid cycle. So the threshold the
        user set (*Settings → Wall upgrade threshold*) is the gate, and the HUD numbers
        decide against it. ``threshold``: the Builder Base's, else the Home Village's.

        A full-storage icon on its own is NOT enough to spend that time: those fire from
        ~85% of a storage and say nothing about what a wall costs. The icons only stand
        in when the HUD cannot be read, and when the threshold is 0 — which the UI
        defines as "only upgrade when storages are full".
        '''
        frame = self.window.screenshot()
        if frame is None:
            return frozenset()
        self._update_config_size(frame)
        full = frozenset(r for (r, on) in zip((RESOURCE_GOLD, RESOURCE_ELIXIR), storages_full(frame)) if on)
        icons_full = bool(full)
        if threshold is None:
            threshold = getattr(self, '_wall_upgrade_threshold', 0)
        threshold = int(threshold or 0)
        if threshold <= 0:
            if icons_full:
                logger.info('Wall upgrades: full storage (%s), threshold is 0', ', '.join(sorted(full)))
            return full
        # Consecutive-frame agreement: a single HUD read is corrupted often enough that
        # acting on one costs a whole pointless pass either way.
        triplet = self._read_hud_triplet_stable()
        if triplet is None:
            if icons_full:
                logger.info('Wall upgrades: HUD unreadable but a storage is full (%s) — running the pass', ', '.join(sorted(full)))
            return full
        (gold, elixir, _dark) = triplet
        enough = frozenset(r for (r, v) in ((RESOURCE_GOLD, gold), (RESOURCE_ELIXIR, elixir)) if v >= threshold)
        if enough:
            logger.info('Wall upgrades: loot gold=%s elixir=%s reached threshold %s (paying with %s)', gold, elixir, threshold, ', '.join(sorted(enough)))
            return enough
        logger.info('Wall upgrades: gold=%s elixir=%s below threshold %s — skipping the pass%s',
                    gold, elixir, threshold, ' (full-storage icon ignored)' if icons_full else '')
        return frozenset()


    def _deselect_wall_ui(self):
        '''Tap empty ground to close the wall selection bar / gem dialog remnants. The wall
bar has no X button — while it is open, the next tap anywhere is swallowed by the
deselect, which would eat the upcoming Attack click. An X still on top is tapped instead:
the Build panel stays open when no Wall card was read, and it shifts the HUD left, so
'empty' would land on a button (the box at 1227x767).'''
        self._dismiss_open_popup(allow_okay = False)
        frame = self.window.screenshot()
        point = find_close(self.vision, frame) if frame is not None else None
        self.input.click(pause = 0.3, *(point or self.config.get_point('empty')))


    def _maybe_upgrade_walls(self, upgrade_walls):
        '''Upgrade walls on home when enabled and loot is high enough (threshold or full storages).'''
        if not upgrade_walls or time.monotonic() < getattr(self, '_wall_retry_at', 0):
            return None
        resources = self._should_upgrade_walls()
        if not resources:  # [recovered: decompiler dropped the second `not`, so it upgraded only when storages were NOT full]
            return None
        cb = getattr(self, '_status_callback', None)
        if cb:
            cb('Upgrading walls...')
        self._loot_snapshot_before_attack()
        for i in range(_WALL_SINGLE_MAX):
            self._check_stop()
            if i:
                resources = self._should_upgrade_walls()
                if not resources:
                    break
            bought = self._upgrade_walls(resources)
            self._deselect_wall_ui()
            if not bought:
                self._wall_retry_at = time.monotonic() + _WALL_RETRY_SECONDS
                if cb:
                    cb(f'Walls: nothing bought this pass — next try in {_WALL_RETRY_SECONDS // 60} min (see Logs)')
                break
        self._suppress_loot_negative_error_once = True


    def _maybe_auto_upgrade(self, force = False):
        '''Interval-gated builder-popup scan + upgrade decision/execution (see
        UpgradeAdvisor). ``force=True`` bypasses the interval (used when storages fill
        up — the idle gate needs a spend attempt NOW, not in 10 minutes). A failure
        here must never take down the farm loop. Returns the PassResult or None.'''
        mode = getattr(self, '_auto_upgrade_mode', MODE_OFF)
        if mode == MODE_OFF:
            return None
        now = time.monotonic()
        if not force and now - getattr(self, '_auto_upgrade_last_scan', 0) < _AUTO_UPGRADE_SCAN_INTERVAL_SECONDS:
            return None
        self._auto_upgrade_last_scan = now
        try:
            frame = self.window.screenshot()
            if frame is not None and self.vision.find_template(frame, 'build.png', region = VisionService.bottom_half_region(frame))[0]:
                return self._build_panel_pass(mode)
            if getattr(self, '_advisor', None) is None:
                self._advisor = UpgradeAdvisor(self.window, self.input, self.vision, self.config, self.stop_event)
            result = self._advisor.run_pass(mode, reserve_builders = getattr(self, '_reserve_builders', 1),
                                            order = getattr(self, '_upgrade_order', None))
            cb = getattr(self, '_status_callback', None)
            if cb and result is not None and result.pick is not None:
                cb(f'''Upgrades: {result.note}''')
            self._emit_state(note = result.note if result else None,
                             builders = result.scan.chip if result and result.scan else None)
            return result
        except InterruptedError:
            raise
        except Exception:
            logger.warning('Auto-upgrade pass failed; continuing farm loop', exc_info = True)
            return None

    def _effective_reserve(self):
        '''Builders kept free for walls; with wall upgrades off they would only sit idle.'''
        return getattr(self, '_reserve_builders', 1) if getattr(self, '_walls_enabled', False) else 0

    def _build_panel_upgrader(self):
        if getattr(self, '_panel_upgrader', None) is None:
            self._panel_upgrader = BuildPanelUpgrader(self.window, self.input, self.vision, self.config, self.stop_event)
        return self._panel_upgrader

    def _build_panel_pass(self, mode):
        '''October 2026 HUD: one upgrade and one research from the Build panel, never with
        the goblin and never through a gem prompt (see :mod:`app.core.build_panel`).'''
        note = self._build_panel_upgrader().run_pass(mode, reserve_builders = self._effective_reserve(), order = getattr(self, '_upgrade_order', None),
                                             builder_base = getattr(self, '_builder_base', False))
        logger.info('Upgrades: %s', note)
        cb = getattr(self, '_status_callback', None)
        if cb:
            cb(f'''Upgrades: {note}''')
        return None

    def _clan_assistant(self):
        '''The session's single ClanAssistant (holds the failure counter that
        disables the feature on a mis-calibrated screen).'''
        if getattr(self, '_clan', None) is None:
            self._clan = ClanAssistant(self.window, self.input, self.vision, self.config, self.stop_event,
                                       self._clan_options, status_callback = getattr(self, '_status_callback', None))
        return self._clan

    def _clan_elixir_ok(self, opts):
        '''True when there is enough elixir on the HUD to be giving troops away.

        Read before the clan menu is opened — the menu covers the HUD, and a donation
        the user cannot afford to replace is worse than a late one.

        An unreadable HUD does NOT block donating: this is a courtesy floor, not a
        spend guard (nothing here can spend anything), and the reading needs OCR, which
        is absent when its models cannot load. It is logged either way.
        '''
        floor = int(getattr(opts, 'min_elixir', 0) or 0)
        if floor <= 0:
            return True
        triplet = self._read_hud_triplet_stable()
        if triplet is None:
            logger.info('Clan assist: no trustworthy HUD reading — donating without the elixir check '
                        '(the bars animate for a second or two after a raid; earlier lines say if a reading was rejected)')
            return True
        elixir = triplet[1]
        if elixir >= floor:
            return True
        logger.info('Clan assist: elixir %s is below the %s floor — skipping donations this pass', elixir, floor)
        cb = getattr(self, '_status_callback', None)
        if cb:
            cb(f'''Clan: elixir {self._fmt_resource(elixir)} below {self._fmt_resource(floor)} — not donating yet''')
        return False

    def _maybe_clan_assist(self):
        '''Interval-gated clan chat visit: donate to open requests, ask for
        reinforcements. Home Village only, and called from the home screen — the chat
        panel would swallow the Attack tap if it were opened any later.

        Donations and requests are independent clocks (troops are asked for far less
        often than clanmates ask for them), but a pass that is due on either clock
        opens the chat once and does both errands that are due. Like the upgrade pass,
        a failure here must never take down the farm loop.'''
        opts = getattr(self, '_clan_options', None)
        if opts is None or not opts.enabled or getattr(self, '_builder_base', False):
            return None
        now = time.monotonic()
        # A donate interval of 0 means "every time we are home", i.e. after each raid:
        # clanmates' requests expire, and the visit is cheap next to an attack cycle.
        donate_due = opts.donate and (opts.donate_interval_s <= 0
                                      or now - getattr(self, '_clan_last_donate', _CLAN_CLOCK_NEVER) >= opts.donate_interval_s)
        request_due = opts.request and now - getattr(self, '_clan_last_request', _CLAN_CLOCK_NEVER) >= opts.request_interval_s
        if not donate_due and not request_due:
            return None
        missing = missing_templates(donate = donate_due, request = request_due,
                                    donate_troop = opts.donate_troop,
                                    have_chat_point = opts.chat_point is not None)
        if missing:
            # Nothing to match, so nothing to click. Park both clocks so this lands in
            # the log once per session rather than once per raid.
            self._clan_last_donate = now + _CLAN_UNCALIBRATED_BACKOFF_SECONDS
            self._clan_last_request = now + _CLAN_UNCALIBRATED_BACKOFF_SECONDS
            msg = f'''Clan assist: missing template(s) {', '.join(missing)} — capture them in Settings → Clan assist.'''
            logger.warning(msg)
            cb = getattr(self, '_status_callback', None)
            if cb:
                cb(msg)
            return None
        if donate_due and not self._clan_elixir_ok(opts):
            donate_due = False
            self._clan_last_donate = now  # re-check on the next donation interval
            if not request_due:
                return None
        try:
            assistant = self._clan_assistant()
            if assistant.disabled:
                return None
            cb = getattr(self, '_status_callback', None)
            if cb:
                cb('Clan chat: donating...' if donate_due else 'Clan chat: requesting troops...')
            result = assistant.run_pass(donate = donate_due, request = request_due)
            # Only the errands actually attempted reset their clock: a pass that could
            # not open the chat retries on the next lap instead of waiting out the
            # interval, and the failure counter is what stops a broken setup.
            if result.opened:
                if donate_due:
                    self._clan_last_donate = now
                if request_due:
                    self._clan_last_request = now
            if cb:
                cb(f'''Clan: {result.note}''')
            return result
        except InterruptedError:
            raise
        except Exception:
            logger.warning('Clan assist pass failed; continuing farm loop', exc_info = True)
            return None

    def _emit_state(self, state = None, builders = None, lab = None, storages = None, note = None, skipped = None):
        '''Push a live-state update to the UI panel (best-effort, never raises).'''
        cb = getattr(self, '_state_callback', None)
        if not cb:
            return None
        try:
            cb({ 'state': state, 'builders': builders, 'lab': lab, 'storages': storages, 'note': note, 'skipped': skipped })
        except Exception:
            logger.debug('State callback failed', exc_info = True)

    def _read_state_stable(self, attempts = 3):
        def _capture():
            frame = self.window.screenshot()
            if frame is not None and frame.size:
                self._update_config_size(frame)
            return frame
        return read_village_state_stable(_capture, self.stop_event.wait, attempts)

    def _read_hud_triplet_stable(self):
        def _capture():
            frame = self.window.screenshot()
            if frame is not None and frame.size:
                self._update_config_size(frame)
            return frame
        return read_hud_triplet_stable(_capture, self.stop_event.wait)

    @staticmethod
    def _fmt_resource(value):
        value = int(value)
        if value >= 1000000:
            return f'''{value / 1000000:.1f}M'''
        if value >= 10000:
            return f'''{value / 1000:.0f}k'''
        return str(value)

    def _emit_village_state(self, state, mode_label):
        if state is None:
            return None
        # Storages field: real OCR'd amounts (from the last stable loot snapshot) plus
        # the game's bar-fill flags. The flat-swatch "full" templates fire from ~90%
        # up, so they are labeled "~full", never "full".
        flags = []
        if state.gold_full:
            flags.append('gold ~full')
        if state.elixir_full:
            flags.append('elixir ~full')
        triplet = getattr(self, '_last_hud_triplet', None)
        if triplet is not None:
            storages = f'''{self._fmt_resource(triplet[0])} / {self._fmt_resource(triplet[1])} / {self._fmt_resource(triplet[2])}'''
            if flags:
                storages += f''' ({', '.join(flags)})'''
        else:
            storages = ', '.join(flags) if flags else 'filling'
        self._emit_state(state = mode_label, builders = state.builders, lab = state.lab, storages = storages)

    def _maybe_idle(self, deadline):
        '''The "run until maxed" idle gate. When both main storages are full and a
        forced upgrade pass could not spend anything, attacking earns nothing — wait
        in place (game session kept alive via recovery on each wake) until a builder
        frees up or loot is spent, instead of stopping or attacking pointlessly.

        Dark elixir has no full-storage indicator; while gold/elixir still have room
        the normal farm loop is what fills DE. Pet House state is invisible on the
        home screen (no HUD chip, no builder-popup row — verified live), so pets are
        the user's manual job and never block idling; the status line calls out an
        idle LAB so research (also manual for now) is never silently forgotten.'''
        if getattr(self, '_auto_upgrade_mode', MODE_OFF) not in LIVE_UPGRADE_MODES:
            return None
        frame = self.window.screenshot()
        if frame is None:
            return None
        self._update_config_size(frame)
        state = read_village_state(frame, self.config)
        self._emit_village_state(state, 'farming')
        if state is None:
            return None
        reserve = self._effective_reserve()
        free = state.free_builders
        # Spend eagerly: ANY full storage with a spare builder is money leaking (live
        # pain: Grand Warden started with elixir, then the free builder sat next to a
        # full gold storage for 10 minutes waiting on the interval pass).
        eager = free is not None and free > reserve and (state.gold_full or state.elixir_full)
        if not state.storages_full and not eager:
            return None
        if not state.storages_full:
            # Eager-only trigger: rate-limit so a full-gold stretch with nothing
            # startable does not burn a ~20s scan every battle cycle.
            now = time.monotonic()
            if now - getattr(self, '_eager_spend_last', 0) < 180:
                return None
            self._eager_spend_last = now
        logger.info('Idle gate: spend burst (%s) — forcing upgrade passes', state.summary())
        # Burn through candidates NOW instead of one per 5-minute wake: every failed
        # pick lands on cooldown so each retry reaches the next candidate, and every
        # SUCCESS frees loot but may leave another builder idle — keep going until
        # nothing is pickable or the attempts are spent.
        for _attempt in range(5):
            result = self._maybe_auto_upgrade(force = True)
            if result is None:
                break  # scan preconditions failed
            if result.pick is None and not result.collecting:
                break  # genuinely nothing pickable remains (a collect pass is not a verdict)
        state = self._read_state_stable()
        if state is None or not state.storages_full:
            return None
        if getattr(self, '_stop_when_full', False):
            return None  # the run ends right after (_stop_if_storages_full) instead of waiting here
        if not (getattr(self, '_gold_pinned', False) and getattr(self, '_elixir_pinned', False)):
            # Icons say ~full but the values are still moving — real headroom remains
            # (live: idled at 18M/21M gold, wasting ~3M of farmable gold). Keep
            # farming until both numbers pin at their caps.
            logger.info('Idle gate: storages ~full but still filling (gold pinned=%s, elixir pinned=%s) — farming on', getattr(self, '_gold_pinned', False), getattr(self, '_elixir_pinned', False))
            return None
        reserve = self._effective_reserve()
        cb = getattr(self, '_status_callback', None)
        logger.info('Idle gate: nothing startable with storages full (%s) — pausing attacks, rechecking every %ds', state.summary(), _IDLE_RECHECK_SECONDS)
        while True:
            self._check_stop()
            if deadline and time.time() >= deadline:
                return None
            msg = f'''Idling — {state.summary() if state else 'state unreadable'}; recheck in {_IDLE_RECHECK_SECONDS // 60}m'''
            if state is not None and state.lab_idle:
                msg += ' — LAB IS IDLE: start a research!'
            if cb:
                cb(msg)
            self._emit_village_state(state, 'idling')
            if self.stop_event.wait(_IDLE_RECHECK_SECONDS):
                return None
            # The game disconnects after a few idle minutes — recovery clicks Reload
            # (after its own grace period) and walks back to the home screen.
            self._home_screen_recovery()
            # Idling can last hours; clanmates still ask for troops in that time.
            self._maybe_clan_assist()
            # A builder or the lab may have freed up: one pass spends on it right here
            # (it only reads the chips when nothing is free).
            self._maybe_auto_upgrade(force = True)
            self._safely('Wall pass', self._maybe_upgrade_walls, getattr(self, '_walls_enabled', False))
            state = self._read_state_stable()
            if state is None:
                continue
            if not state.storages_full:
                if state.builders is None:
                    # Unreadable builder chip = probably not a clean home frame (mid-
                    # recovery, reload dialog) — the missing full-icons prove nothing.
                    # Stay idle; the next wake re-reads (live repro: one wake exited on
                    # "builders ? free, storages filling" right after a disconnect).
                    logger.info('Idle: degraded read (%s) — staying idle', state.summary())
                    continue
                logger.info('Idle over: storages have room again (%s)', state.summary())
                break
            free = state.free_builders
            if free is not None and free > reserve:
                logger.info('Idle over: %d builder(s) free (%s)', free, state.summary())
                break
        self._auto_upgrade_last_scan = 0  # resume with an immediate scan so the freed builder is used
        if cb:
            cb('Resuming — ' + state.summary())
        self._emit_village_state(state, 'farming')

    def _storages_full_now(self):
        '''Gold and elixir both full on the home screen of either village (:func:`storages_full`:
        the left end of both bars coloured), on two frames in a row: a run is not ended on one
        frame that something passing over the bars may have coloured.'''
        for i in range(_FULL_STOP_FRAMES):
            if i and self.stop_event.wait(_FULL_STOP_GAP):
                return False
            frame = self.window.screenshot()
            if frame is None:
                return False
            self._update_config_size(frame)
            if not all(storages_full(frame)):
                return False
        return True

    def _stop_if_storages_full(self):
        '''*Stop when storages are full*, between battles once the walls and upgrades had their
        turn: True when gold and elixir are both full. A single run ends there; in a Multi-run
        only the account in play is done, and the next one starts.'''
        if not getattr(self, '_stop_when_full', False) or not self._storages_full_now():
            return False
        multi = getattr(self, '_multi_run', False)
        msg = f'''Storages full (gold and elixir) — {'this account is done' if multi else 'stopping the run'}.'''
        logger.info(msg)
        cb = getattr(self, '_status_callback', None)
        if cb:
            cb(msg)
        if not multi:
            self.finish_reason = 'storages full'
        return True


    def _upgrade_walls(self, resources = (RESOURCE_ELIXIR, RESOURCE_GOLD)):
        '''Open builder menu, scroll to Wall, add walls → remove if both red → Okay.'''
        frame = self.window.screenshot()
        if frame is None:
            return None
        self._update_config_size(frame)
        home_roi = VisionService.bottom_half_region(frame)
        (hax, hay) = self.vision.find_control(frame, 'attack.png', region = home_roi)
        if not hax:
            logger.info('Wall upgrade: not on the home screen (Attack button missing) — skipping this pass')
            return None
        if not self._open_build_panel(frame):
            return None
        # TH15+ overflows the builder popup ('Suggested upgrades' grows and 'Other upgrades'
        # continues past the fold), so the Wall row can start below the visible area. The
        # popup scrolls with the mouse wheel without closing; touch-drags scroll too but
        # overshoot past Wall (it now sits mid-list, not at the end). Poll the OCR at each
        # position and wheel down a notch between misses.
        wall_pt = None
        candidate = None
        scrolls = 0
        signature = None
        stalls = 0
        for _ in range(_WALL_MENU_SCROLL_STEPS * 2):
            self._check_stop()
            (frame, found) = self._find_wall_row_once()
            if found:
                if candidate and abs(found[1] - candidate[1]) <= self.config.scale_scalar(_WALL_ROW_STABLE_TOL):
                    wall_pt = found
                    if scrolls:
                        logger.info('Wall upgrade: Wall row found after %d scroll nudge(s)', scrolls)
                    break
                # One agreeing frame is required before clicking — the list keeps easing
                # after a wheel nudge, and a click on stale coordinates lands on whatever
                # row slid underneath (live repro: opened the Blacksmith's Forge).
                candidate = found
                if self.stop_event.wait(0.25):
                    return None
                continue
            candidate = None
            # The end of the list is the end of the hunt: the Wall row is the last entry,
            # so once the list has stopped travelling there is nothing further down to
            # find, and another nudge would only cost time. Two still stops are required
            # because the list also sits still for a beat mid-flick.
            new_signature = self._wall_menu_signature(frame)
            if signature is not None and new_signature is not None and float(np.mean(np.abs(new_signature - signature))) < _WALL_MENU_BOTTOM_DIFF:
                stalls += 1
                if stalls >= 2:
                    logger.info('Wall upgrade: reached the end of the builder list after %d nudge(s) with no Wall row', scrolls)
                    break
            else:
                stalls = 0
            signature = new_signature
            scrolls += 1
            if scrolls >= _WALL_MENU_SCROLL_STEPS:
                break
            self.input.scroll(*self._wall_menu_scroll_point(), _WALL_MENU_WHEEL_CLICKS)
            if self.stop_event.wait(0.5):
                return None
        if not wall_pt:
            logger.info('Wall upgrade: no Wall row in the builder list — skipping this pass')
            # The builder popup is still open at this point, and an open popup swallows
            # the next tap — including the Attack one.
            self._deselect_wall_ui()
            return None
        self.input.click(pause = 0.6, rand = False, *wall_pt)
        return self._buy_selected_wall(resources)

    def _buy_selected_wall(self, resources = (RESOURCE_ELIXIR, RESOURCE_GOLD)):
        '''The Wall card selected a wall: tap that wall's own Upgrade button (elixir first,
        then gold), then confirm its upgrade dialog the gem-safe way. True when bought.'''
        tile = None
        frame = None
        for _ in range(8):  # the camera pans to the wall before its buttons render (often >1s)
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                return None
            self._update_config_size(frame)
            tile = wall_upgrade_button(self.vision, frame, resources)
            if tile:
                break
            if self.stop_event.wait(0.5):
                return None
        if not tile:
            logger.info('Wall upgrade: no affordable Upgrade button under the selected wall — skipping this pass')
            _dump_debug_frame(frame, 'wallrow')
            return None
        (point, resource) = tile
        self.input.click(*point, pause = 0.5, rand = False)
        result = self._build_panel_upgrader().confirm(resource, 'Wall')
        if result != 'started':
            logger.info('Wall upgrade: %s', result)
            return None
        logger.info('Wall upgrade: one wall upgraded with %s', resource)
        return True

    
    def _dismiss_star_bonus(self, frame):
        '''The Star Bonus dialog ("Star Bonus received": the loot is already given), whose
        Okay only closes it. Found by its title, read only when an Okay-like button shows
        (okay.png is drawn at 0.9 there: 0.75 at the bot's scale); its Okay by that art or
        its label. True when tapped.'''
        if frame is None:
            return False
        (h, w) = frame.shape[:2]
        dialog = (w // 4, h // 2, w // 2, h // 2)

        def okay(scale):
            (x, y, _score) = VisionService.find_template_with_confidence(frame, 'okay.png', threshold = 0.8, region = dialog, scale = scale)
            return (x, y) if x is not None else None
        point = VisionService.with_scale_fallback(okay)
        if not point:
            return False
        if self.vision.find_label(frame, 'Star Bonus', region = (w // 4, 0, w // 2, h // 3))[0] is None:
            return False
        logger.info('Star Bonus dialog: tapping its Okay')
        self.input.click(*point, pause = 0.6)
        return True

    def _dismiss_okay_or_exit_on_frame(self, frame, allow_okay = True):
        '''If ``okay.png``, ``exit.png``, or a known dialog-specific control is visible,
        click it. Returns True if dismissed. The Daily Reward popup (blocked the bot a
        whole night) must be CLAIMED before its X works ("Claim reward first!"), so the
        green Claim button outranks its grey X; both have their own art (exit.png does
        not match).'''
        # allow_okay=False for screens the caller has not inspected: their Okay may confirm a purchase.
        # A gem on screen means a gem purchase is on offer: never its Okay, only an X.
        if allow_okay and gem_prompt_visible(self.vision, frame):
            logger.warning('Popup with a gem icon: closing it, not pressing its Okay')
            allow_okay = False
        if self._dismiss_star_bonus(frame):
            return True
        names = ['okay.png', 'exit.png', 'closex.png'] if allow_okay else ['exit.png', 'closex.png']
        for extra in ('claim_btn.png', 'dailyreward_x.png', 'needgold_x.png'):
            if get_template_path(extra).exists():
                names.append(extra)
        for name in names:
            (x, y) = self.vision.find_template(frame, name)
            if not x:
                continue
            self.input.click(x, y, pause = 0.15)
            return True
        return False

    
    def _wait_for_attack_with_nudge(self, timeout = 10, error = True):
        '''Poll bottom-half ``attack.png``; dismiss ``okay`` / ``exit`` popups first; else empty + scroll.'''
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(0.5):
                    return (None, None)
                continue
            self._update_config_size(frame)
            if self._dismiss_okay_or_exit_on_frame(frame):
                if self.stop_event.wait(0.25):
                    return (None, None)
                continue
            if self._live_battle_button(frame)[0]:
                # We are inside a live battle — nudge clicks would deploy troops. Bail out and
                # let _home_screen_recovery surrender/return-home.
                logger.warning('Attack wait: live battle detected (Surrender / End Battle visible) — leaving it to recovery')
                return (None, None)
            search_region = self._search_region_for_template(frame, 'attack.png', None, None, 200)
            (ax, ay) = self.vision.find_control(frame, 'attack.png', region = search_region, ocr = time.time() - start >= _LABEL_FALLBACK_AFTER)
            if ax:
                return (ax, ay)
            self._nudge_view_to_reveal_attack()
            if self.stop_event.wait(0.35):
                return (None, None)
        if error:
            logger.warning('Timeout waiting for attack.png')  # [recovered: decompiler misnested this inside the loop — it spammed once per poll]
        return (None, None)

    
    def _run_loop(self, method_id, duration_seconds, star_bonus = False, upgrade_walls = False):
        start_time = time.time()
        if self.stop_event.wait(1):
            return None
        frame = self.window.screenshot()
        self._update_config_size(frame)
        empty_pt = self.config.get_point('empty')
        self.input.click(pause = 0.2, *empty_pt)
        self.input.scroll(*self._scroll_point(), 20)
        delay = random.uniform(0.1, 0.3)
        if self.stop_event.wait(delay):
            return None
        if star_bonus and self._is_star_bonus_claimed():
            logger.info('Star bonus mode: no star bonus template matched on home — nothing to collect. Finishing without attacks.')
            return None
        # duration_seconds == 0 → endless: only the user's Stop ends the session (or full
        # storages with "Stop when storages are full"); with Maxer or Rusher, full storages
        # park the loop in _maybe_idle instead.
        deadline = start_time + duration_seconds if duration_seconds else None
        self._maybe_clan_assist()
        self._safely('Wall pass', self._maybe_upgrade_walls, upgrade_walls)
        self._maybe_auto_upgrade()
        self._safely('Idle gate', self._maybe_idle, deadline)
        if self._safely('Full storages', self._stop_if_storages_full):
            return None
        cb = getattr(self, '_status_callback', None)
        troop_failures = 0
        while deadline is None or time.time() < deadline:
            self._check_stop()
            outcome = 'no_attack'
            try:
                outcome = self._find_match_and_attack(method_id)
                if outcome != 'no_attack':
                    self._return_home()
            except InterruptedError:
                raise
            except Exception:
                logger.error('Attack cycle failed (outcome so far: %s)', outcome, exc_info = True)
            self._recover_safely()
            if outcome in ('troop', 'no_attack'):
                # A cycle that never reached a battle used to count as a success and loop
                # silently (efebolukbasi/BasePilot#7, #9); it now backs off like missing troops.
                what = 'Troops not found' if outcome == 'troop' else 'Battle not started (game screen not recognized)'
                troop_failures += 1
                if troop_failures >= _TROOP_FAILURE_LIMIT:
                    if deadline is None:
                        # An endless run must never stop on its own: long back-off
                        # instead (a stuck popup / event screen usually clears, and
                        # recovery runs again on the next attempt).
                        msg = f'''{what} {troop_failures} times in a row — backing off {_IDLE_RECHECK_SECONDS // 60}m, then retrying (endless run).'''
                        logger.warning(msg)
                        if cb:
                            cb(msg)
                        troop_failures = 0
                        if self.stop_event.wait(_IDLE_RECHECK_SECONDS):
                            return None
                        self._recover_safely()
                        continue
                    msg = f'''{what} {troop_failures} times in a row — stopping. Check the army / saved recipe, and that the game shows the home village.'''
                    logger.warning(msg)
                    if cb:
                        cb(msg)
                    return None
                msg = f'''{what} ({troop_failures}/{_TROOP_FAILURE_LIMIT}) — retrying in {_TROOP_RETRY_WAIT_SECONDS}s.'''
                logger.warning(msg)
                if cb:
                    cb(msg)
                # Tap any collect bubbles while we are home — if the failure was really the
                # need-more-gold dialog (entry fee unaffordable), mine gold un-wedges it.
                self._multi_run_collect_home_village_resources()
                if self.stop_event.wait(_TROOP_RETRY_WAIT_SECONDS):
                    return None
            else:
                troop_failures = 0
            self._maybe_clan_assist()
            self._safely('Wall pass', self._maybe_upgrade_walls, upgrade_walls)
            self._maybe_auto_upgrade()
            self._safely('Idle gate', self._maybe_idle, deadline)
            if self._safely('Full storages', self._stop_if_storages_full):
                return None
            self.input.scroll(*self._scroll_point(), 5)
            if self.stop_event.wait(random.uniform(0.15, 0.25)):
                return None
            if star_bonus and self._is_star_bonus_claimed():
                logger.info('Star bonus claimed (star icons no longer visible). Stopping.')
                return None
        return None

    
    def _run_builder_base_loop(self, duration_seconds, star_bonus = False):
        '''Builder Base farming: Battle → Find Now → deploy → the battle to its end → Return
        Home. ``duration_seconds == 0``: endless, until the user's Stop (or full storages with
        "Stop when storages are full"); a stuck screen backs off instead of ending the run.'''
        start_time = time.time()
        cb = getattr(self, '_status_callback', None)
        if self.stop_event.wait(1):
            return None
        frame = self.window.screenshot()
        if not frame is None:
            self._update_config_size(frame)
        # no tap on the home village's "empty" point here: it lands on Builder Base walls
        self.input.scroll(*self._scroll_point(), 20)
        if self.stop_event.wait(random.uniform(0.1, 0.3)):
            return None
        if star_bonus and self._is_bb_star_bonus_finished():
            msg = 'Builder Base star bonus: bstar.png not visible — nothing to collect. Finishing without attacks.'
            logger.info(msg)
            if cb:
                cb(msg)
            return None
        self._maybe_auto_upgrade()
        self._safely('Walls', self._bb_maybe_upgrade_walls)
        self._safely('Live status', self._bb_live_status)
        if self._safely('Full storages', self._stop_if_storages_full):
            return None
        failures = 0
        while not duration_seconds or time.time() - start_time < duration_seconds:
            self._check_stop()
            try:
                attacked = self._bb_attack_once(cb)
            except InterruptedError:
                raise
            except Exception:
                logger.error('Builder Base: attack cycle failed', exc_info = True)
                attacked = False
            # A missed end (no End Battle, stars or Surrender in time) leaves the battle or its
            # results on screen: walk back to the village before anything else.
            self._recover_safely()
            if not attacked:
                failures += 1
                if failures >= _TROOP_FAILURE_LIMIT:
                    if not duration_seconds:
                        # An endless run never stops on its own: a popup or an event screen in
                        # the way usually clears, and recovery runs again after the back-off.
                        msg = f'''Builder Base: {failures} cycles in a row without a battle — backing off {_IDLE_RECHECK_SECONDS // 60}m, then retrying (endless run).'''
                        logger.warning(msg)
                        if cb:
                            cb(msg)
                        failures = 0
                        if self.stop_event.wait(_IDLE_RECHECK_SECONDS):
                            return None
                        self._recover_safely()
                        continue
                    msg = f'''Builder Base: {failures} cycles in a row without a battle — stopping. Check that the Builder Base is on screen.'''
                    logger.warning(msg)
                    if cb:
                        cb(msg)
                    return None
                if self.stop_event.wait(_TROOP_RETRY_WAIT_SECONDS):
                    return None
                continue
            failures = 0
            self._bb_collect_elixir_cart_after_attack()
            self._safely('Live status', self._bb_live_status)
            self._maybe_auto_upgrade()
            self._safely('Walls', self._bb_maybe_upgrade_walls)
            if self._safely('Full storages', self._stop_if_storages_full):
                return None
            if star_bonus and self._is_bb_star_bonus_finished():
                logger.info('Builder Base star bonus finished (bstar.png no longer visible). Stopping.')
                return None
            if self.stop_event.wait(random.uniform(0.35, 0.6)):
                return None
        return None

    def _bb_maybe_upgrade_walls(self):
        '''Builder Base walls, with the Home Village's pass (:meth:`_upgrade_walls`: the Build
        panel's Wall card, the selected wall's own Upgrade button paid with gold or elixir
        but never the Wall Ring, the gem-safe Confirm), from the Builder Base's threshold
        (*Settings → Wall upgrade threshold → Builder Base*). Walls are instant: no builder
        is used. No tap on "empty" ground here (it lands on walls and obstacles): a wall
        left selected deselects on the next tap, which is tapped again (Build, Battle).'''
        if not getattr(self, '_walls_enabled', False) or time.monotonic() < getattr(self, '_wall_retry_at', 0):
            return None
        threshold = getattr(self, '_bb_wall_threshold', 0)
        resources = self._should_upgrade_walls(threshold)
        if not resources:
            return None
        cb = getattr(self, '_status_callback', None)
        if cb:
            cb('Builder Base: upgrading walls...')
        bought = 0
        for i in range(_WALL_SINGLE_MAX):
            self._check_stop()
            if i:
                resources = self._should_upgrade_walls(threshold)
                if not resources:
                    break
            if not self._upgrade_walls(resources):
                if not bought:
                    self._wall_retry_at = time.monotonic() + _WALL_RETRY_SECONDS
                    if cb:
                        cb(f'Builder Base walls: nothing bought this pass — next try in {_WALL_RETRY_SECONDS // 60} min (see Logs)')
                break
            bought += 1
        frame = self.window.screenshot()
        point = find_close(self.vision, frame) if frame is not None else None
        if point:
            self.input.click(*point, pause = 0.3)  # the Build panel, when a pass stopped with it open
        if bought:
            logger.info('Builder Base walls: %d bought this pass', bought)
        self._suppress_loot_negative_error_once = True

    def _bb_live_status(self):
        '''The Builder Base HUD into the live status: storages (gold / elixir) and the
        session's gains (the HUD's third number there is the gems: left out).'''
        triplet = self._read_hud_triplet_stable()
        if triplet is None:
            self._emit_loot_update()
            self._emit_state(state = 'Builder Base')
            return
        (gold, elixir, _gems) = triplet
        self._record_loot((gold, elixir, 0), village = 'builder')
        self._emit_state(state = 'Builder Base', storages = f'{self._fmt_resource(gold)} / {self._fmt_resource(elixir)}')

    def _bb_attack_once(self, cb):
        '''One Builder Base battle: Battle → Find Now → deploy → play it to its end (never
        End Battle nor Surrender). False when no battle was played (a control never showed up).'''
        self._bb_stage_plans = {}  # a new battle draws the attack plan of each stage
        self.input.scroll(*self._scroll_point(), 20)
        if self.stop_event.wait(random.uniform(0.1, 0.25)):
            self._check_stop()
        self._dismiss_star_bonus(self.window.screenshot())  # Battle shows dimmed under it and would match
        (ax, ay) = self._wait_for_image('attack.png', timeout = 10)
        if not ax:
            logger.warning('Builder Base: attack.png not found')
            return False
        self.input.click(ax, ay, pause = 0.15)
        (fx, fy) = self._wait_for_image('findnow.png', timeout = _TAP_EATEN_AFTER, error = False)
        if not fx:
            self._dismiss_star_bonus(self.window.screenshot())
            (ax, ay) = self._find_template_once('attack.png')
            if ax:  # still home: a selection (a wall just bought) or a dialog took the tap
                logger.info('Builder Base: Battle tap eaten (a selection on screen) — tapping it again')
                self.input.click(ax, ay, pause = 0.15)
            (fx, fy) = self._wait_for_image('findnow.png', timeout = 10)
        if not fx:
            logger.warning('Builder Base: findnow.png not found')
            return False
        self.input.click(fx, fy, pause = 0.15)
        (bx, by) = self._wait_for_image(_BB_CARD_SWAP_TEMPLATE, timeout = 30, error = False)
        if not bx:
            msg = 'Builder Base: troop cards not found after Find Now'
            logger.warning(msg)
            if cb:
                cb(msg)
            return False
        frame = self.window.screenshot()
        if frame is None:
            return False
        self._update_config_size(frame)
        (h, w) = frame.shape[:2]
        (cx, cy) = (w // 2, h // 2)
        self.input.move(cx, cy)
        if self.stop_event.wait(0.05):
            self._check_stop()
        self.input.scroll(cx, cy, 4)
        if self.stop_event.wait(0.15):
            self._check_stop()
        frame = self.window.screenshot()
        if frame is None:
            return False
        self._update_config_size(frame)
        abilities = self._deploy_bb_army(frame)
        if abilities is None:
            logger.warning('Builder Base: troop cards lost after zoom nudge / deploy failed')
            return False
        self._bb_fight_to_the_end(abilities)
        return True

    def _recover_safely(self):
        '''Home-screen recovery that cannot end the run (a long reward overlay raises).'''
        try:
            self._home_screen_recovery()
        except InterruptedError:
            raise
        except Exception:
            logger.error('Recovery failed; the next cycle starts from whatever screen is up', exc_info = True)

    def _safely(self, what, fn, *args):
        '''Run a between-raids hook; an error in it is logged, the farm loop goes on.'''
        try:
            return fn(*args)
        except InterruptedError:
            raise
        except Exception:
            logger.error('%s failed; the farm loop goes on', what, exc_info = True)
            return None

    
    def _bb_pan_down_left_from_center(self):
        '''Pan BB view down-left from screen center (~500px) to reveal the boat / elixir cart.'''
        self._check_stop()
        frame = self.window.screenshot()
        if frame is None or frame.size == 0:
            return None
        self._update_config_size(frame)
        (h, w) = frame.shape[:2]
        cx = w // 2 + random.randint(-25, 25)
        cy = h // 2 + random.randint(-25, 25)
        cx = max(8, min(w - 8, cx))
        cy = max(8, min(h - 8, cy))
        self.input.move(cx, cy, 0)
        self.input.mouse_up(cx, cy)
        if self.stop_event.wait(0.06):
            self._check_stop()
        step = 500
        x2 = max(8, min(w - 8, cx - step))
        y2 = max(8, min(h - 8, cy + step))
        self.input.mouse_down(cx, cy)
        self.input.human_move(cx, cy, x2, y2, duration = random.uniform(0.35, 0.55))
        self.input.mouse_up(x2, y2)
        if self.stop_event.wait(0.45):
            self._check_stop()
            return None

    
    def _bb_still_frame(self):
        '''A screenshot once the view has stopped moving (a pan glides on after the drag:
        live, the cart moved 45 px more after the frame a tap was aimed with), or the last
        one after :data:`_BB_STILL_TIMEOUT`.'''
        (last, small) = (None, None)
        deadline = time.monotonic() + _BB_STILL_TIMEOUT
        while True:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is not None:
                self._update_config_size(frame)
                now = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 100), interpolation = cv2.INTER_AREA).astype(np.int16)
                if small is not None and now.shape == small.shape and float(np.abs(now - small).mean()) < _BB_STILL_DIFF:
                    return frame
                (last, small) = (frame, now)
            if time.monotonic() >= deadline or self.stop_event.wait(0.25):
                return last

    def _find_bb_full_elixir_cart(self):
        '''The full elixir cart on the still view, or None: anywhere between the top HUD and
        the buttons (live, the cart showed at the top right before a pan, mid-right after).'''
        frame = self._bb_still_frame()
        if frame is None:
            return None
        (h, w) = frame.shape[:2]
        region = (0, int(0.1 * h), w, int(0.62 * h))
        for template in _BB_FULL_ELIXIR_CART_TEMPLATES:
            (x, y) = self.vision.find_template(frame, template, threshold = 0.8, region = region)
            if x:
                return (x, y)
        return None

    def _bb_collect_elixir_cart_after_attack(self):
        '''Back home after a battle: the elixir cart, when full, on the view as it is or else
        after a pan, tapped, then its Collect. Nothing else is tapped: the home village's
        "empty" point lands on Builder Base walls and obstacles.'''
        if self.stop_event.wait(0.35):
            return None
        cart = self._find_bb_full_elixir_cart()
        if cart is None:
            self._bb_pan_down_left_from_center()
            cart = self._find_bb_full_elixir_cart()
        if cart is None:
            logger.debug('Builder Base: elixir cart not full — nothing to collect')
            return None
        self.input.click(*cart, pause = 0.2)
        (coll_x, coll_y) = self._wait_for_image(_BB_COLLECT_TEMPLATE, timeout = 8, error = False)
        if coll_x:
            self.input.click(coll_x, coll_y, pause = 0.2)
            logger.info('Builder Base: elixir cart collected')
        else:
            logger.warning('Builder Base: collect.png not found after elixir cart')
        # The cart's window stays open after Collect (live: the next Battle tap only closed
        # it, and Find Now never came): its X closes it.
        if self.stop_event.wait(0.6):
            return None
        frame = self.window.screenshot()
        close = find_close(self.vision, frame) if frame is not None else None
        if close:
            self.input.click(*close, pause = 0.3)

    
    def _read_bb_bar(self, frame):
        '''``(cards, machine)`` still to deploy on the bar of ``frame``: the troop cards
        (:func:`~app.core.bb_strategy.read_bar`) and the machine card's point, or None.'''
        (h, _w) = frame.shape[:2]
        roi = VisionService.bottom_half_region(frame)
        swaps = VisionService.find_all_template_centers(frame, _BB_CARD_SWAP_TEMPLATE, region = roi, max_matches = 12, suppress_pad_frac = _BB_TEMPLATE_SUPPRESS_PAD)
        machine = next((p for p in (self.vision.find_template(frame, t, region = roi) for t in (_BB_BATTLE_MACHINE_TEMPLATE, _BB_FLYING_MACHINE_TEMPLATE)) if p[0]), None)
        if machine is not None and not bb_strategy.alive(frame, machine):
            machine = None  # a grey machine card: already out, or down for this stage
        lift = int(round(_BB_CARD_ABOVE_SWAP * h / 1600))  # 16:10 reference px; the bar scales with the height
        return (bb_strategy.read_bar(self.vision, frame, swaps, lift, machine[0] if machine else None), machine)

    def _land_bb_steps(self, steps, abilities):
        for step in steps:
            self._check_stop()
            if step.wait and self.stop_event.wait(step.wait):
                self._check_stop()
            self.input.click(*step.card, pause = 0.25, rand = False)
            self.input.click(*step.point, pause = _EDRAG_DELAY, rand = False)
            fired = step.profile.ability_on_landing
            if fired:  # its card again: the ability as it lands (the Bomber's Bouncing Bomb for the first wall)
                self.input.click(*step.card, pause = 0.2, rand = False)
                logger.info('Builder Base: %s ability as it lands', step.troop)
            abilities.add(step, time.monotonic(), fired = fired)

    def _bb_fronts(self, frame, cards, stage = bb_learning.FIRST):
        '''``(label, front)`` to attack from, best first: the sides of the base the scouting
        found (:mod:`app.core.bb_scout`) — for a P.E.K.K.A push, the side of the Multi
        Mortar first — then one top edge of the map as a last resort.'''
        h = frame.shape[0]
        fronts = []
        try:
            (scouting, entries) = self._bb_plan_entries(frame, cards, stage)
        except Exception:
            logger.warning('Builder Base: scouting failed', exc_info = True)
            (scouting, entries) = (None, [])
        if scouting is not None:
            for entry in entries[:_BB_SIDES_TRIED]:
                fronts.append((f'at {entry}, {bb_scout.side(scouting, entry)} of the base centred at {scouting.centre}',
                               bb_scout.front(scouting, entry)))
        else:
            logger.info('Builder Base: no base found on the screen — attacking from a map edge')
        side = random.choice(('left', 'right'))
        edge = bb_strategy.front_edge(self.config.get_point(side), self.config.get_point('top'), h)
        fronts.append((f'from the {side} edge of the map', bb_strategy.edge_front(edge, h)))
        return fronts

    def _bb_learner(self):
        learner = getattr(self, '_bb_plans', None)
        if learner is None:
            learner = self._bb_plans = bb_learning.PlanLearner.from_history(battle_history.load())
        return learner

    def _bb_plan_entries(self, frame, cards, stage = bb_learning.FIRST):
        '''``(scouting, entries)`` of the stage's attack plan (:mod:`app.core.bb_learning`):
        each stage draws its own among the plans that apply (the second base is another
        base, scored apart); a redeploy within the stage keeps it. The army is the first
        stage's: the second one's bar holds what is left of it.'''
        scouting = bb_scout.scout(frame)
        if scouting is None:
            return (None, [])
        plans = getattr(self, '_bb_stage_plans', None)
        if plans is None:
            plans = self._bb_stage_plans = {}
        opening = plans.get(bb_learning.FIRST)
        army = opening[0] if opening else (bb_learning.PEKKA if bb_strategy.pekka_push(cards) else bb_learning.OTHER)
        mortar = bb_scout.multi_mortar(frame, scouting) if army == bb_learning.PEKKA else None
        available = ['best', 'core', 'reach'] + (['mortar'] if mortar is not None else [])
        plan = plans.get(stage)
        if plan is None or plan[1] not in available:
            learner = self._bb_learner()
            plan = plans[stage] = (army, learner.choose(army, available, stage = stage))
            logger.info('Builder Base: stage %d attack plan "%s" (expected damage: %s)', stage, plan[1],
                        learner.summary(army, available, stage = stage))
        if plan[1] == 'mortar':
            logger.info('Builder Base: Multi Mortar at %s — the P.E.K.K.As go for it first', mortar)
            return (scouting, bb_scout.towards(scouting, mortar))
        if plan[1] in _BB_CORE_WEIGHTS:
            scouting = bb_scout.scout(frame, core_weight = _BB_CORE_WEIGHTS[plan[1]]) or scouting
        return (scouting, scouting.entries)

    def _bb_record_result(self, start):
        '''Read the results screen once settled, log it, and score the battle's plan.'''
        def capture():
            frame = self.window.screenshot()
            if frame is not None:
                self._update_config_size(frame)
            return frame
        result = bb_results.settled_result(capture, self.stop_event.wait)
        if result is None:
            logger.info('Builder Base: results screen not read')
            return None
        plans = getattr(self, '_bb_stage_plans', None) or {}
        (first, second) = (plans.get(bb_learning.FIRST), plans.get(bb_learning.SECOND))
        logger.info('Builder Base: %d star(s), %d %% damage, %s gold, %s trophies (plans %s, %ds)', result.stars, result.damage,
                    result.gold, result.trophies, ' then '.join(p[1] for p in (first, second) if p) or '-', int(time.monotonic() - start))
        record = dict(result.as_dict(), village = 'builder', session = getattr(self, '_session_id', None), seconds = int(time.monotonic() - start))
        if first or second:
            army = (first or second)[0]
            # "plan": the last stage's, as the history had it before the stages were scored apart
            record.update(army = army, plan = (second or first)[1])
            record.update({key: p[1] for (key, p) in (('plan1', first), ('plan2', second)) if p})
            self._bb_learner().record_battle(army, first[1] if first else None, second[1] if second else None, result.damage)
        battle_history.append(record)
        return result

    def _bb_swaps_shown(self, frame):
        return bool(VisionService.find_all_template_centers(frame, _BB_CARD_SWAP_TEMPLATE, region = VisionService.bottom_half_region(frame), max_matches = 1))

    def _bb_landed(self):
        '''A troop has landed: the swap buttons have left the bar.'''
        if self.stop_event.wait(_BB_LANDED_CHECK_AFTER):
            self._check_stop()
        frame = self.window.screenshot()
        return frame is None or not self._bb_swaps_shown(frame)

    def _deploy_bb_army(self, frame, stage = bb_learning.FIRST):
        '''Read the bar and play the plan of :mod:`app.core.bb_strategy`: the machine, then
        each troop by its role, along the side of the base the scouting picked for the
        ``stage``. Once the first troop is down, the rest follow; a first troop that did not
        land (its spot is no-deploy) goes again from the next side. A troop still on the bar
        after the deploy lands once more at the entry. Returns the stage's
        :class:`~app.core.bb_strategy.Abilities`, or None when no card is on the bar.'''
        (h, _w) = frame.shape[:2]
        (cards, machine) = self._read_bb_bar(frame)
        if not cards and machine is None:
            return None
        fronts = self._bb_fronts(frame, cards, stage)
        check = self._bb_swaps_shown(frame)  # before any troop lands, the swap buttons show
        abilities = bb_strategy.Abilities()
        for (k, (label, front)) in enumerate(fronts):
            steps = bb_strategy.plan(cards, machine, front)
            if k == 0:
                logger.info('Builder Base: deploying %s %s', ', '.join((s.troop or 'unknown') for s in steps), label)
            self._land_bb_steps(steps[:1], abilities)
            if not check or k == len(fronts) - 1 or self._bb_landed():
                break
            abilities.forget([steps[0].card], 0.05 * h)
            logger.warning('Builder Base: the first troop did not land at %s — attacking %s instead', steps[0].point, fronts[k + 1][0])
        self._land_bb_steps(steps[1:], abilities)
        if self.stop_event.wait(_BB_LANDED_CHECK_AFTER):
            self._check_stop()
        frame = self.window.screenshot()
        (left, _machine) = self._read_bb_bar(frame) if frame is not None else ([], None)
        if left:
            entry = front(0.0)
            logger.warning('Builder Base: %s still on the bar — landing at the entry %s', ', '.join(c.troop or 'unknown' for c in left), entry)
            abilities.forget([c.tap for c in left], 0.05 * h)
            self._land_bb_steps(bb_strategy.plan(left, None, lambda _offset: entry), abilities)
        return abilities

    def _bb_return_home_point(self, frame, ocr):
        '''Return Home of the results screen: the art at the bot's scale or another (drawn at
        0.9 on a 1227x767 GPG window), its label when ``ocr``; None during the fight.'''
        roi = VisionService.bottom_half_region(frame)

        def at(scale):
            (x, y, _score) = self.vision.find_template_with_confidence(frame, _BB_RETURN_HOME_TEMPLATE, threshold = 0.8, region = roi, scale = scale)
            return (x, y) if x is not None else None
        hit = self.vision.with_scale_fallback(at)
        if hit:
            return hit
        if ocr:
            (x, y) = self.vision.find_label(frame, 'Return Home', region = roi)
            if x is not None:
                return (x, y)
        return None

    def _bb_leave_results(self, point):
        '''Tap Return Home, then wait for the results screen to go. It stays up a moment as
        the village loads: the recovery that runs next used to find it still there and tap
        Return Home again (live: 19 battles in 20), and a late tap lands on the village, whose
        selection then eats the next Battle tap. Still there once a lost tap's delay is over,
        it is tapped once more. True once it is gone.'''
        self.input.click(*point, pause = 0.3)
        tapped = time.monotonic()
        again = False
        while time.monotonic() - tapped < _BB_RESULTS_LEAVE_TIMEOUT:
            if self.stop_event.wait(0.4):
                self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                continue
            self._update_config_size(frame)
            point = self._bb_return_home_point(frame, ocr = True)
            if point is None:
                return True
            if not again and time.monotonic() - tapped >= _TAP_EATEN_AFTER:
                logger.info('Builder Base: the results screen is still up — tapping Return Home again')
                self.input.click(*point, pause = 0.3)
                again = True
        logger.warning('Builder Base: the results screen did not go in %ds — leaving it to recovery', int(_BB_RESULTS_LEAVE_TIMEOUT))
        return False

    def _bb_speed_point(self, frame):
        '''The speed button of a stage's last minute while it reads 1x, or None (not shown
        yet, or already 4x).'''
        (x, y, _score) = self.vision.find_template_with_confidence(frame, _BB_SPEED_TEMPLATE, threshold = _BB_SPEED_MIN,
                                                                   region = VisionService.right_half_region(frame))
        return (x, y) if x is not None else None

    def _bb_fight_to_the_end(self, abilities):
        '''Play the battle out, never ending it early: fire the troop abilities at their moment
        (one per poll, see :class:`~app.core.bb_strategy.Abilities`), speed the last minute
        of each stage up to 4x, deploy whatever comes back to the bar (stage 2: survivors and
        reinforcements), and leave only from the results screen. End Battle and Surrender
        are never tapped. True once Return Home was tapped.'''
        start = time.monotonic()
        last_deploy = start
        next_speed = start
        next_ocr = start + _BB_RETURN_HOME_OCR_EVERY
        while time.monotonic() - start < _BB_BATTLE_MAX_SECONDS:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(0.5):
                    self._check_stop()
                continue
            self._update_config_size(frame)
            now = time.monotonic()
            point = self._bb_return_home_point(frame, ocr = now >= next_ocr)
            if now >= next_ocr:
                next_ocr = now + _BB_RETURN_HOME_OCR_EVERY
            if point:
                logger.info('Builder Base: battle over after %ds — returning home', int(now - start))
                try:
                    self._bb_record_result(start)  # lets the screen settle: its Return Home takes the tap then
                except InterruptedError:
                    raise
                except Exception:
                    logger.warning('Builder Base: could not record the result', exc_info = True)
                self._bb_leave_results(point)
                return True
            ability = abilities.next_tap(now, frame)
            if ability is not None:
                self.input.click(*ability.card, pause = 0.1, rand = False)  # the card again: the troop's ability
                logger.info('Builder Base: %s ability at %ds%s', ability.troop or 'unknown', int(now - start),
                            f' (health {ability.health:.0%})' if ability.health is not None else '')
            speed = self._bb_speed_point(frame) if now >= next_speed else None
            if speed:
                self.input.click(*speed, pause = 0.1)
                next_speed = now + _BB_SPEED_RETRY
                logger.info('Builder Base: last minute of the stage at %ds — speed 4x', int(now - start))
            if now - last_deploy >= _BB_REDEPLOY_AFTER and VisionService.find_all_template_centers(
                    frame, _BB_CARD_SWAP_TEMPLATE, region = VisionService.bottom_half_region(frame), max_matches = 1):
                logger.info('Builder Base: troops back on the bar (next stage) — deploying them')
                fresh = self._deploy_bb_army(frame, bb_learning.SECOND)
                if fresh is not None:
                    abilities = fresh  # the last stage's cards are gone: their abilities would tap the new ones
                    last_deploy = time.monotonic()
            if self.stop_event.wait(0.5):
                self._check_stop()
        logger.warning('Builder Base: no results screen after %ds — leaving it to recovery', _BB_BATTLE_MAX_SECONDS)
        return False

    def _find_match_and_attack(self, method_id):
        """One attack cycle. Returns ``'troop'`` (troops missing — retry later),
        ``'no_attack'`` (Battle / Find a Match / the battle screen never came up), or None."""
        battle_template = 'farmbattle.png'
        self._hv_base_loot = None  # what the attacked base holds, when the loot filter read it
        self._hv_loot_left = None  # what it still holds as the battle ends, read during the battle
        self._hv_quake = None  # (army, Earthquake placement) of this raid
        # Only inside the Battle card: the Ranked Battle card to its right must never be tapped.
        battle_card = (0, 0, int(self.config.width * _BATTLE_CARD_MAX_X), int(self.config.height))
        (fx, fy) = self._find_template_once(battle_template, region = battle_card)
        if fx:
            # A previous cycle left the battle-selection screen open (stolen tap / derail) —
            # use it directly instead of hunting for the home Attack button it covers.
            logger.info('Attack: battle-selection screen already open — continuing from Find a Match')
        else:
            (ax, ay) = self._wait_for_attack_with_nudge()
            if not ax:
                return 'no_attack'
            # Home screen confirmed (Attack visible) → the HUD is readable: record the
            # pre-attack loot baseline / accumulate the previous battle's gains.
            # [recovered: this call existed only in the wall path — with walls off the
            # loot tracker never ran (live repro: 3 battles, session totals stuck at 0)]
            self._loot_snapshot_before_attack()
            self.input.click(ax, ay, pause = 0.1)
            (fx, fy) = self._wait_for_image(battle_template, region = battle_card)
        if not fx:
            return 'no_attack'
        self.input.click(fx, fy, pause = 0.1)
        # A single tap here is unreliable: event popups (Card Hunt etc.) or a still-animating
        # screen can eat it. Verify the army screen (attack2) actually appeared; while the
        # Find a Match button is still on screen, the tap was stolen — tap again (the first
        # stolen tap also closes whatever popup ate it).
        (a2x, a2y) = self._wait_for_image('attack2.png', timeout = 5, error = False)
        for _ in range(3):
            if a2x:
                break
            (rfx, rfy) = self._find_template_once(battle_template, region = battle_card)
            if not rfx:
                break
            logger.info('%s still on screen — click was eaten (popup?); re-clicking', battle_template)
            self.input.click(rfx, rfy, pause = 0.1)
            (a2x, a2y) = self._wait_for_image('attack2.png', timeout = 5, error = False)
        if not a2x:
            (a2x, a2y) = self._wait_for_image('attack2.png')
        if method_id == 3 and not self._ensure_valkyrie_army_from_recipes():
            # Attack anyway with whatever is trained — a partial Valkyrie army still loots, and
            # bailing out here would leave the Find a Match screen open with nothing to recover it.
            msg = 'Valkyrie army not confirmed (slow screen or missing saved recipe) — attacking with current army'
            logger.warning(msg)
            cb = getattr(self, '_status_callback', None)
            if cb:
                cb(msg)
        if a2x:
            self.input.click(a2x, a2y, pause = 0.1)
        (bsx, _bsy) = self._wait_for_any_image(('surrender.png', 'endbattle.png'), timeout = 60, label_after = _BATTLE_LABEL_AFTER)
        if not bsx:
            # No battle screen (search fee unaffordable, a stolen tap): running the strategy
            # here would drag across whatever screen is up, then wait out every battle timer.
            return 'no_attack'
        # Battle prep: the base is on screen with its loot listed, and nothing has been
        # deployed yet — the only moment Next is still an option.
        self._skip_low_loot_bases()
        frame = self.window.screenshot()
        if frame is None:
            return None
        self._update_config_size(frame)
        (h, w) = frame.shape[:2]
        cy = h // 2
        cx = w // 2
        self.input.move(cx, cy)
        if self.stop_event.wait(0.05):
            return None
        self.input.scroll(cx, cy, 3)
        frame = self.window.screenshot()
        if frame is None:
            return None
        self._update_config_size(frame)
        strategy = self._get_strategy(method_id)
        strategy.event_handler = self._battle_rewards
        self._hv_battle_start = time.monotonic()
        result = strategy.execute(frame, self.stop_event)
        if getattr(strategy, 'quakes_cast', None) is False:
            self._hv_quake = None  # no Earthquake in the army: nothing to learn about their placement
        self._wait_for_battle_end(is_sneaky = method_id == 1)
        return 'troop' if result is False else None

    
    def _skip_low_loot_bases(self):
        '''On the battle-prep screen: press Next while the base holds less than the
        configured minimum loot.

        Each Next costs another search fee, so the number of skips per cycle is capped
        and the cap is the user's (Settings → Minimum loot to attack). Two things
        deliberately fall through to attacking rather than stalling the farm loop: a
        loot panel that cannot be read (OCR missing — the filter is an optimisation,
        not a safety rail) and a missing Next button.
        '''
        lf = getattr(self, '_loot_filter', None)
        if lf is None or not lf.enabled or getattr(self, '_loot_filter_off', False):
            return None
        if not get_template_path(TEMPLATE_NEXT_BASE).exists():
            self._loot_filter_off = True  # say it once, not once per raid
            msg = f'''Loot filter: {TEMPLATE_NEXT_BASE} not captured — attacking every base. Capture it in Settings → Clan assist → Capture templates.'''
            logger.warning(msg)
            cb = getattr(self, '_status_callback', None)
            if cb:
                cb(msg)
            return None
        for _ in range(max(1, int(lf.max_skips))):
            self._check_stop()
            loot = self._read_base_loot()
            if loot is None:
                logger.info('Loot filter: could not read this base loot (see the LootFilter lines) — attacking it')
                return None
            (gold, elixir, dark) = loot
            if meets(loot, lf):
                logger.info('Loot filter: base holds %s gold / %s elixir / %s dark — attacking', gold, elixir, dark)
                self._hv_base_loot = loot
                return None
            # Skipping costs a search fee, so a "too poor" verdict is confirmed on a
            # second read before paying it. A read that changes its mind means the
            # panel was still painting — attack rather than pay for a maybe.
            confirm = self._read_base_loot(polls = 2)
            if confirm is None or meets(confirm, lf):
                logger.info('Loot filter: second read of this base disagreed (%s vs %s) — attacking it', loot, confirm)
                self._hv_base_loot = confirm
                return None
            frame = self.window.screenshot()
            if frame is None:
                return None
            self._update_config_size(frame)
            (nx, ny) = self._next_base_point(frame) or (None, None)
            if not nx:
                logger.warning('Loot filter: %s gold / %s elixir is below %s but Next was not found — attacking this base', gold, elixir, lf.summary())
                return None
            self._bases_skipped = getattr(self, '_bases_skipped', 0) + 1
            logger.info('Loot filter: skipping a base with %s gold / %s elixir (want %s) — %d skipped this session', gold, elixir, lf.summary(), self._bases_skipped)
            cb = getattr(self, '_status_callback', None)
            if cb:
                cb(f'''Skipping base: {self._fmt_resource(gold)} gold / {self._fmt_resource(elixir)} elixir''')
            self._emit_state(skipped = self._bases_skipped)
            self.input.click(nx, ny, pause = 0.4)
            if not self._wait_for_next_base():
                logger.warning('Loot filter: the next base did not load — attacking whatever is on screen')
                return None
        logger.info('Loot filter: %d skips used on this cycle — attacking this base', lf.max_skips)

    def _next_base_point(self, frame):
        '''The battle-prep screen's Next button, at the bot's scale or another (the 16:10
        art is the 16:9 one scaled by the screen height, as most buttons are), or None.'''
        def at(scale):
            (x, y, _score) = self.vision.find_template_with_confidence(frame, TEMPLATE_NEXT_BASE, threshold = 0.8, scale = scale)
            return (x, y) if x is not None else None
        return self.vision.with_scale_fallback(at)

    def _battle_prep_visible(self, frame):
        '''True while the battle-prep controls (Surrender / End Battle) are on screen.'''
        for name in ('surrender.png', 'endbattle.png'):
            (x, _y) = self.vision.find_template(frame, name)
            if x:
                return True
        return False

    def _wait_for_next_base(self):
        '''After pressing Next: let the old base clear, then wait for the new one.

        Live repro: the loot read fired ~1s after Next, while the *old* battle-prep
        screen was still up, so it came back unreadable and the bot attacked a base that
        had not finished loading — "Troop sneaky not found!", because the deploy bar had
        not rendered either. Waiting for the controls to disappear first is what makes
        the wait that follows mean "the next base", not "the last one".
        '''
        for _ in range(_NEXT_CLEAR_POLLS):
            frame = self.window.screenshot()
            if frame is None:
                break
            self._update_config_size(frame)
            if not self._battle_prep_visible(frame):
                break
            if self.stop_event.wait(0.5):
                return False
        (sx, _sy) = self._wait_for_any_image(('surrender.png', 'endbattle.png'), timeout = 30, error = False)
        if not sx:
            return False
        if self.stop_event.wait(_NEXT_SETTLE_SECONDS):  # let the loot panel paint
            return False
        return True

    def _read_base_loot(self, polls = _LOOT_READ_POLLS, samples = _LOOT_READ_SAMPLES):
        '''OCR the enemy loot panel and fold several reads into one.

        Retries while the panel has not rendered yet, then keeps reading until it has
        ``samples`` successful reads to combine — a single read of this panel is wrong
        about half the time on a live client (dropped digit: 705,559 read as 70,559),
        and one low read is the difference between skipping a good base and raiding it.
        Returns the combined triplet, or None once the polls are spent.
        '''
        reads = []
        for _ in range(max(1, int(polls))):
            frame = self.window.screenshot()
            if frame is not None:
                self._update_config_size(frame)
                loot = read_enemy_loot(frame)
                if loot is not None:
                    reads.append(loot)
                    if len(reads) >= max(1, int(samples)):
                        break
            if self.stop_event.wait(0.35):
                break
        return combine_reads(reads)

    def _quake_learner(self):
        learner = getattr(self, '_hv_quakes', None)
        if learner is None:
            learner = self._hv_quakes = bb_learning.QuakeLearner.from_history(battle_history.load())
        return learner

    def _quake_placement(self, method_id):
        '''The raid's Earthquake placement (an ``EARTHQUAKE_METHOD_*``): the user's, or with
        *Learn* the one drawn from the raids so far (:class:`~app.core.bb_learning.QuakeLearner`).
        Kept with the army for the raid's result.'''
        method = getattr(self, '_earthquake_method', EARTHQUAKE_METHOD_CURVE)
        army = _HV_ARMIES.get(method_id, _HV_ARMIES[1])
        if method == EARTHQUAKE_METHOD_LEARN:
            learner = self._quake_learner()
            quake = learner.choose(army, bb_learning.QUAKES)
            logger.info('Earthquakes: %s placement, drawn (%s: %s)', quake, army, learner.summary(army, bb_learning.QUAKES))
        else:
            quake = 'random' if method == EARTHQUAKE_METHOD_RANDOM else 'curve'
        self._hv_quake = (army, quake)
        return EARTHQUAKE_METHOD_RANDOM if quake == 'random' else EARTHQUAKE_METHOD_CURVE

    def _get_strategy(self, method_id):
        cb = getattr(self, '_status_callback', None)
        eq = self._quake_placement(method_id)
        if method_id == 1:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, 'sneaky', 15, status_callback = cb, earthquake_method = eq)
        if method_id == 2:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, 'superminion', 3.1, status_callback = cb, earthquake_method = eq)
        if method_id == 3:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, 'valkyrie', 5.5, status_callback = cb, earthquake_method = eq)
        if method_id == 4:
            return EdragStrategy(self.input, self.vision, self.config, self.stop_event, status_callback = cb, earthquake_method = eq)
        return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, 'sneaky', 15, status_callback = cb, earthquake_method = eq)

    
    def _wait_for_battle_end(self, is_sneaky):
        if is_sneaky:
            if self.stop_event.wait(3):
                return None
            (sx, sy) = self._wait_for_image('surrender.png', timeout = 2, error = False)
            if sx:
                self.input.click(sx, sy, pause = 0.1)
                return None
            (bx, by) = self._wait_for_image('endbattle.png', timeout = 2, error = False)
            if bx:
                self.input.click(bx, by, pause = 0.1)
                return None
            return None
        self._play_out_battle()

    def _play_out_battle(self):
        '''Let the raid take the loot. The base's available loot (top left) is read every
        second: once it has stopped dropping for :data:`_LOOT_STALL` s with a star won (End
        Battle shows), the battle is ended; with no star yet (Surrender) and nothing coming
        after :data:`_BATTLE_GIVE_UP` s, it is surrendered, as before. Ending at the first
        star, as the bot did, left 1.2M of 2.1M on a live base. A battle that ends by itself
        goes to its results screen: nothing is tapped.'''
        start = time.monotonic()
        last_drop = start
        best = None  # the lowest plausible available loot read so far
        first = None  # a first read, kept until the next agrees: a misread can come first
        self._hv_loot_left = None
        plausible = lambda new, old: all(o * 0.5 <= n <= o for (n, o) in zip(new, old))
        while time.monotonic() - start < _BATTLE_LONGEST:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(0.5):
                    self._check_stop()
                continue
            self._update_config_size(frame)
            now = time.monotonic()
            rewards = getattr(self, '_battle_rewards', None)
            if rewards is not None and rewards.handle(frame):
                continue  # an event's reward overlay, cleared: look again
            if any(self.vision.find_template(frame, t)[0] for t in ('returnhome.png', 'chestclaim.png')):
                return None  # over by itself
            loot = read_enemy_loot(frame)
            if loot is not None and best is None:
                if first is not None and plausible(loot, first):
                    best = loot
                else:
                    first = loot  # live: 709379 read 7093790 once
            elif loot is not None and loot != best and plausible(loot, best):
                last_drop = now  # a drop, not a misread (live: 735196 read 7093790 once)
                best = loot
            self._hv_loot_left = best
            bottom = VisionService.bottom_half_region(frame)
            stalled = now - last_drop >= _LOOT_STALL
            (ex, ey) = self.vision.find_template(frame, 'endbattle.png', region = bottom)
            if ex and stalled:
                logger.info('Battle: the loot stopped coming (%s left) — End Battle after %ds', best, int(now - start))
                self.input.click(ex, ey, pause = 0.1)
                return None
            if not ex and stalled and now - start >= _BATTLE_GIVE_UP:
                (sx, sy) = self.vision.find_template(frame, 'surrender.png', region = bottom)
                if sx:
                    logger.info('Battle: no star and no loot coming after %ds — Surrender', int(now - start))
                    self.input.click(sx, sy, pause = 0.1)
                    return None
            if self.stop_event.wait(_LOOT_POLL):
                self._check_stop()
        frame = self.window.screenshot()  # past the battle's own length: whatever way out shows
        for name in ('endbattle.png', 'surrender.png'):
            (x, y) = self.vision.find_control(frame, name, region = self._search_region_for_template(frame, name, None, None, 200)) if frame is not None else (None, None)
            if x:
                self.input.click(x, y, pause = 0.1)
                return None

    
    def _return_home(self):
        '''Dismiss Okay if present, then click ``returnhome.png`` (+ ``returnhome2.png`` on 16:10) or run the
        ``chestclaim.png`` flow (mutually exclusive). Okay is polled in the same loop, so a battle that
        ended without a confirm dialog no longer waits out a 10 s Okay timeout first.'''
        (kind, hx, hy) = self._wait_for_return_home_or_chest_claim(timeout = 20, dismiss_okay = True)
        if kind == 'return' and hx:
            self._hv_record_result()
            self.input.click(hx, hy, pause = 0.1)
        elif kind == 'chest' and hx:
            logger.info('Post-battle UI: chestclaim.png (replacing return home); running chest flow')
            self.input.click(hx, hy, pause = 0.2)
            if self.stop_event.wait(0.35):
                return None
            self._tap_empty_until_chest_continue()

    
    def _hv_record_result(self):
        '''Read the raid's results screen once settled, log it, write the battle to the
        history, and score its Earthquake placement by the share of the base's loot taken.'''
        def capture():
            frame = self.window.screenshot()
            if frame is not None:
                self._update_config_size(frame)
            return frame
        for look in range(2):  # Return Home shows: the damage paints with it, or a moment after
            frame = capture()
            if frame is not None and hv_results.read_result(frame) is not None:
                break
            if look or self.stop_event.wait(0.5):
                logger.info('Battle: results screen not read')
                return None
        result = bb_results.settled_result(capture, self.stop_event.wait, read = hv_results.read_result)
        if result is None:
            logger.info('Battle: results screen not read')
            return None
        (army, quake) = getattr(self, '_hv_quake', None) or (None, None)
        share = hv_results.loot_share(result, left = getattr(self, '_hv_loot_left', None), held = getattr(self, '_hv_base_loot', None))
        start = getattr(self, '_hv_battle_start', None)
        seconds = int(time.monotonic() - start) if start is not None else None
        logger.info("Battle: %d star(s), %d %% damage, +%s gold / +%s elixir / +%s dark (%s of the base's loot; Earthquakes: %s)",
                    result.stars, result.damage, result.gold, result.elixir, result.dark,
                    f'{share:.0%}' if share is not None else 'unknown share', quake or 'none')
        record = dict(result.as_dict(), village = 'home', session = getattr(self, '_session_id', None), seconds = seconds)
        if army:
            record['army'] = army
        if quake:
            record['plan'] = quake
        if share is not None:
            record['loot'] = round(100 * share)
            if army and quake:
                self._quake_learner().record(army, quake, 100 * share)
        battle_history.append(record)
        self._hv_result_recorded = True
        return result

    def _wait_for_return_home_or_chest_claim(self, timeout = 10, dismiss_okay = False):
        '''
Poll one frame for ``returnhome.png`` (+ ``returnhome2.png`` on 16:10 only) then ``chestclaim.png`` (only one should match),
then, after :data:`_LABEL_FALLBACK_AFTER`, their "Return Home" / "Claim Reward" labels (redrawn buttons).
With ``dismiss_okay``, an ``okay.png`` confirm on the way is clicked first (at most twice).
Returns (``"return"`` | ``"chest"``, x, y) or (None, None, None) on timeout.
'''
        start = time.time()
        okay_clicks = 0
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(0.5):
                    return (None, None, None)
                continue
            self._update_config_size(frame)
            if self._battle_rewards.handle(frame):
                continue
            if dismiss_okay and okay_clicks < 2:
                (ox, oy) = self.vision.find_template(frame, 'okay.png')
                if ox:
                    self.input.click(ox, oy, pause = 0.1)
                    okay_clicks += 1
                    continue
            (rx, ry) = (None, None)
            returnhome_tpls = ('returnhome.png', 'returnhome2.png') if self.config.aspect_key == ASPECT_16_10 else ('returnhome.png',)
            for tpl in returnhome_tpls:
                (rx, ry) = self.vision.find_template(frame, tpl)
                if rx:
                    break  # [recovered: decompiler dropped this break, letting the last template overwrite a match]
            if rx:
                return ('return', rx, ry)
            (cx, cy) = self.vision.find_template(frame, 'chestclaim.png')
            if cx:
                return ('chest', cx, cy)
            if time.time() - start >= _LABEL_FALLBACK_AFTER:
                bottom = VisionService.bottom_half_region(frame)
                (rx, ry) = self.vision.find_label(frame, 'Return Home', region = bottom)
                if rx:
                    logger.info('Return Home art not matched; clicking its label read by OCR')
                    return ('return', rx, ry)
                (cx, cy) = self.vision.find_label(frame, 'Claim Reward', region = bottom)
                if cx:
                    return ('chest', cx, cy)
            if self.stop_event.wait(0.5):
                return (None, None, None)
        logger.warning('Timeout waiting for returnhome.png / returnhome2.png (16:10) or chestclaim.png')
        return (None, None, None)

    
    def _random_point_chest_tap_through(self):
        '''Random point near center-right of the capture for chest tap-through (±85 px from anchor).'''
        (w, h) = (self.config.width, self.config.height)  # [recovered: pycdc reversed STORE_FAST_STORE_FAST pairs]
        if w <= 1 or h <= 1:
            (w, h) = (self.config.ref_width, self.config.ref_height)
        cx = int(w * 0.75)
        cy = h // 2
        j = 85
        return (max(0, min(w - 1, cx + random.randint(-j, j))), max(0, min(h - 1, cy + random.randint(-j, j))))

    
    def _tap_empty_until_chest_continue(self):
        '''After ``chestclaim`` was clicked: tap center-right (±85px) until ``chestcontinue.png``, then click it (home).'''
        CHEST_TAP_TIMEOUT = 120
        deadline = time.time() + CHEST_TAP_TIMEOUT
        while time.time() < deadline:
            self._check_stop()
            (nx, ny) = self._random_point_chest_tap_through()
            self.input.click_at(nx, ny, rand = False)
            t0 = time.time()
            if self.stop_event.wait(0.15):
                return None
            frame2 = self.window.screenshot()
            if not frame2 is None:
                self._update_config_size(frame2)
                (tx, ty) = self.vision.find_template(frame2, 'chestcontinue.png')
                if tx:
                    logger.info('Chest reward: chestcontinue.png found; clicking (expect home village)')
                    self.input.click(tx, ty, pause = 0.25)
                    return None
            elapsed = time.time() - t0
            to_wait = max(0.05, 0.5 - elapsed)
            if self.stop_event.wait(to_wait):
                return None
        logger.warning(f'''chestcontinue.png not seen within {int(CHEST_TAP_TIMEOUT)}s after chest claim; continuing bot loop''')  # [recovered: decompiler misnested this inside the loop, ending the tap-through after one tap]
        return None

    
    def _is_star_bonus_claimed(self):
        '''True if neither emptystar nor glowstar matches strongly (bonus claimed / not shown).'''
        frame = self.window.screenshot()
        if frame is None:
            return False
        self._update_config_size(frame)
        for template in ('emptystar.png', 'glowstar.png'):
            (_, _, confidence) = self.vision.find_template_with_confidence(frame, template, threshold = 0)  # [recovered + verified against original bytecode]
            if confidence >= _STAR_BONUS_THRESHOLD:
                return False
        return True

    
    def _is_bb_star_bonus_finished(self):
        '''True when ``bstar.png`` is not visible in the bottom half (BB star bonus attacks done).'''
        frame = self.window.screenshot()
        if frame is None:
            return False
        self._update_config_size(frame)
        bot_roi = VisionService.bottom_half_region(frame)
        (_, _, confidence) = self.vision.find_template_with_confidence(frame, _BB_STAR_BONUS_TEMPLATE, threshold = 0.0, region = bot_roi)  # [recovered + verified against original bytecode]
        return confidence < _STAR_BONUS_THRESHOLD

    
    def _home_screen_recovery(self):
        '''Ensures we are back at home screen. Escapes popups, stray screens, live battles, and end screens.'''
        for _ in range(20):
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(1):
                    return None
                continue
            self._update_config_size(frame)
            # First: the game dims everything behind this dialog, and the buttons under it
            # (End Battle, Return Home...) still match, so any earlier check would eat the pass.
            (lx, ly) = self.vision.find_template(frame, 'reload.png') if get_template_path('reload.png').exists() else (None, None)
            if not lx:
                (lx, ly) = reconnect_button(self.vision, frame) or (None, None)
            if lx:
                now = time.monotonic()
                first = getattr(self, '_reload_first_seen', None)
                if first is None:
                    self._reload_first_seen = now
                    logger.warning('Recovery: connection-lost dialog detected — waiting %ds before reloading (another device may be using the account)', _RELOAD_GRACE_SECONDS)
                    # Wait it out here: spread over farm cycles, the grace costs four failed
                    # cycles and stops a timed run right as the game reconnects.
                    if self.stop_event.wait(_RELOAD_GRACE_SECONDS):
                        return None
                    continue
                if now - first >= _RELOAD_GRACE_SECONDS:
                    logger.warning('Recovery: connection-lost dialog persisted — clicking RELOAD')
                    self.input.click(lx, ly, pause = 1.0)
                    self._reload_first_seen = None
                    if self.stop_event.wait(10):
                        return None
                if self.stop_event.wait(2):
                    return None
                continue
            if self._battle_rewards.handle(frame):
                continue
            if self._dismiss_okay_or_exit_on_frame(frame):
                if self.stop_event.wait(0.3):
                    return None
                continue
            (sx, sy) = self._live_battle_button(frame)
            if sx:
                logger.info('Recovery: live battle — surrendering to get home')
                self.input.click(sx, sy, pause = 0.3)
                if self.stop_event.wait(0.5):
                    return None
                continue
            returnhome_tpls = ('returnhome.png', 'returnhome2.png') if self.config.aspect_key == ASPECT_16_10 else ('returnhome.png',)
            (rx, ry) = (None, None)
            for tpl in returnhome_tpls:
                (rx, ry) = self.vision.find_template(frame, tpl)
                if rx:
                    break
            if rx:
                logger.info('Recovery: clicking Return Home')
                self.input.click(rx, ry, pause = 0.3)
                if self.stop_event.wait(0.5):
                    return None
                continue
            if self._home_hud_visible(frame):
                self._reload_first_seen = None
                return None
            # Not home: a redrawn Return Home button is still labelled "Return Home".
            (rx, ry) = self.vision.find_label(frame, 'Return Home', region = VisionService.bottom_half_region(frame))
            if rx:
                logger.info('Recovery: clicking Return Home (label read by OCR)')
                self.input.click(rx, ry, pause = 0.3)
                if self.stop_event.wait(0.5):
                    return None
                continue
            self.stop_event.wait(1)
        return None

    
    def _switch_account_and_load_home(self, username):
        '''Open Settings → Change user, OCR-click username, wait for home. Raises on failure.'''
        cb = getattr(self, '_status_callback', None)
        msg = f'''Multi-run: switching to {username!r}'''
        logger.info(msg)
        if cb:
            cb(msg)
        if not self._open_game_settings():
            raise RuntimeError('Multi-run: Settings not found (the profile at the top left, then its Settings tab)')
        (cux, cuy) = self._wait_for_image('changeuser.png', timeout = 10, error = False)
        if not cux:
            _dump_debug_frame(self.window.screenshot(), 'settings')
            self._close_windows()
            raise RuntimeError('Multi-run: the switch-account button (changeuser.png) is not in Settings — a frame of that screen is in the debug folder')
        self.input.click(cux, cuy, pause = 1)
        (ucx, ucy) = self._wait_for_player_name(username, timeout = 25, match_alnum_only = True, fuzzy_min_ratio = 0.8)
        if not ucx:
            err = f'''Multi-run: could not find username "{username}" on screen (OCR)'''
            logger.error(err)
            if cb:
                cb(err)
            raise RuntimeError(err)
        self.input.click(ucx, ucy, pause = 0.2)
        if self.stop_event.wait(1):
            self._check_stop()
        (ax, ay) = self._wake_home_and_wait_for_attack(timeout = 30)
        if not ax:
            err = f'''Multi-run: Home Village not ready after loading {username!r} (builder.png|gbuilder.png / attack.png timeout after login / leaving Builder Base)'''
            logger.error(err)
            if cb:
                cb(err)
            raise RuntimeError(err)
        self._loot_prev_resources = None

    
    def _open_game_settings(self):
        '''The game's Settings, where the Supercell ID switch is. The October 2026 HUD keeps
        them in the profile: its badge at the top left, then the profile window's Settings
        tab (its tabs, at the top: My Profile, Social, Inbox, Settings). The old HUD had a
        gear (``settings.png``). True once Settings was tapped; a profile window left open
        without a Settings tab read is closed again.'''
        frame = self.window.screenshot()
        if frame is None:
            return False
        self._update_config_size(frame)
        if not is_october_hud(frame):
            (stx, sty) = self._wait_for_image('settings.png', timeout = 10, error = False)
            if not stx:
                return False
            self.input.click(stx, sty, pause = 0.25)
            return True
        (h, w) = frame.shape[:2]
        self.input.click(int(_PROFILE_BADGE[0] * h), int(_PROFILE_BADGE[1] * h), pause = 0.6, rand = False)
        for _ in range(10):  # ~5 s for the profile window
            self._check_stop()
            frame = self.window.screenshot()
            if frame is not None:
                self._update_config_size(frame)
                (fh, fw) = frame.shape[:2]
                (x, y) = self.vision.find_label(frame, 'Settings', region = (fw // 3, 0, fw - fw // 3, int(_PROFILE_TABS_Y * fh)))
                if x:
                    self.input.click(x, y, pause = 0.5, rand = False)
                    return True
            if self.stop_event.wait(0.5):
                self._check_stop()
        _dump_debug_frame(frame, 'profile')
        self._close_windows()
        return False

    def _close_windows(self):
        '''Tap the X on top until none shows (at most three windows).'''
        for _ in range(3):
            frame = self.window.screenshot()
            point = find_close(self.vision, frame) if frame is not None else None
            if point is None:
                return None
            self.input.click(*point, pause = 0.5, rand = False)

    def _wake_home_and_wait_for_attack(self, timeout = 30):
        '''
After switching accounts: dismiss idle UI, then poll the **top half** for village type
(``mbuilder.png`` = Builder Base; ``builder.png`` or ``gbuilder.png`` = Home Village). If Builder Base,
leave via :meth:`_leave_builder_base_with_nboat`. When Home Village is detected, return
``attack.png`` coordinates from the **bottom half** (battle bar) once visible — same
template as :meth:`_find_match_and_attack` uses to start battles.
Each iteration dismisses ``okay.png`` / ``exit.png`` if present, then village / attack logic; else nudge.
'''
        frame = self.window.screenshot()
        self._update_config_size(frame)
        empty_pt = self.config.get_point('empty')
        self.input.click(pause = 0.2, *empty_pt)
        self.input.scroll(*self._scroll_point(), 20)
        delay = random.uniform(0.1, 0.3)
        if self.stop_event.wait(delay):
            return (None, None)
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if not frame is None:
                self._update_config_size(frame)
                if self._dismiss_okay_or_exit_on_frame(frame):
                    if self.stop_event.wait(0.25):
                        return (None, None)
                    continue
                chip_roi = VisionService.bottom_half_region(frame)
                (mx, my) = self.vision.find_template(frame, 'mbuilder.png', region = chip_roi)
                if mx:
                    logger.info('Account loaded in Builder Base (mbuilder.png); leaving to Home Village')
                    cb = getattr(self, '_status_callback', None)
                    if cb:
                        cb('Multi-run: Builder Base on login — leaving (nboat)')
                    self._leave_builder_base_with_nboat(settle_before_drag = False)
                    if self.stop_event.wait(1):
                        return (None, None)
                    continue
                if self._home_hud_visible(frame):
                    bot_roi = VisionService.bottom_half_region(frame)
                    (ax, ay) = self.vision.find_control(frame, 'attack.png', region = bot_roi, ocr = time.time() - start >= _LABEL_FALLBACK_AFTER)
                    if ax:
                        return (ax, ay)
            self._nudge_view_to_reveal_attack()
            if self.stop_event.wait(0.35):
                return (None, None)
        return (None, None)  # [recovered: decompiler put an unconditional return inside the loop, so only one poll ever ran]

    
    def _detect_village_type(self, frame = None):
        '''Return ``"home"``, ``"builder"``, or ``None`` from the builder portraits (bottom right
        since Oct 2026). The Home Village's chip shows the next free builder's face, the
        goblin's when the others are busy (live: builder.png 0.59), so its home is also told,
        like :meth:`_home_hud_visible` does, by the Battle and Build buttons with no trace of
        the Builder Base's master builder (live: 0.6 on the Home Village, 0.9+ on its own).'''
        if frame is None:
            frame = self.window.screenshot()
        if frame is None or frame.size == 0:
            return None
        self._update_config_size(frame)
        chip_roi = VisionService.bottom_half_region(frame)
        (mx, my) = self.vision.find_template(frame, 'mbuilder.png', region = chip_roi)
        if mx:
            return 'builder'
        (hx, hy) = self._find_home_village_builder(frame, chip_roi)
        if hx:
            return 'home'
        if self.vision.find_template(frame, 'attack.png', region = chip_roi)[0] and self.vision.find_template(frame, 'build.png', region = chip_roi)[0] \
                and not self.vision.find_template(frame, 'mbuilder.png', threshold = _NO_MASTER_BUILDER, region = chip_roi)[0]:
            return 'home'
        return None

    
    def _go_to_builder_base_with_boat(self):
        '''Home Village → Builder Base via ``boat.png``.'''
        self._check_stop()
        self._zoom_out_max()
        (bx, by) = self._wait_for_image('boat.png', timeout = 15, error = False)
        if not bx:
            logger.warning('boat.png not found — cannot switch to Builder Base')
            return False
        self.input.click(bx, by, pause = 0.25)
        if self.stop_event.wait(1):
            return False
        (mx, my) = self._wait_for_image('mbuilder.png', timeout = 15, error = False)
        if not mx:
            logger.warning('mbuilder.png not found after boat — may still be in Home Village')
            return False
        return True

    
    def _zoom_out_max(self):
        '''Wheel the camera all the way out. The boat and the collect bubbles are world
        objects: their templates match at the widest zoom, and at the game's default zoom
        they are ~1.35x bigger (live 16:10) and the boat is off screen.'''
        self.input.scroll(*self._scroll_point(), 20)
        if self.stop_event.wait(0.3):
            self._check_stop()

    def _ensure_correct_village(self, builder_base):
        '''Before farming: switch villages if the wrong builder portrait is showing.'''
        self._check_stop()
        self.input.click(pause = 0.15, *self.config.get_point('empty'))
        if self.stop_event.wait(0.2):
            return None
        self._zoom_out_max()
        village = self._detect_village_type()
        for _ in range(_VILLAGE_DETECT_RETRIES):  # a popup or the zoom still settling
            if village is not None or self.stop_event.wait(0.8):
                break
            village = self._detect_village_type()
        if builder_base:
            if village == 'builder':
                return None
            if village == 'home':
                logger.info('Startup: in Home Village but Builder Base was selected — taking boat')
                self._go_to_builder_base_with_boat()
                return None
            logger.warning('Startup: could not detect village (expected Builder Base)')
            return None
        if village == 'home':
            return None
        if village == 'builder':
            logger.info('Startup: in Builder Base but Home Village was selected — leaving (nboat)')
            self._leave_builder_base_with_nboat()
            return None
        logger.warning('Startup: could not detect village (expected Home Village)')

    
    def _leave_builder_base_with_nboat(self, settle_before_drag = True):
        '''
Pan down-left from screen center (~500px), then click ``nboat.png`` to return to Home Village.
Does not check ``mbuilder.png`` first — call only when a BB→HV trip is intended.

``settle_before_drag``: small delay after prior UI (e.g. collect clicks) before capturing
dimensions and dragging.
'''
        self._check_stop()
        if settle_before_drag and self.stop_event.wait(0.75):
            self._check_stop()
        logger.info('Leaving Builder Base (drag + nboat)')
        cb = getattr(self, '_status_callback', None)
        if cb:
            cb('Multi-run: leaving Builder Base (nboat)')
        self._zoom_out_max()
        self._bb_pan_down_left_from_center()
        (nx, ny) = self._wait_for_image('nboat.png', timeout = 12, error = False)
        if nx:
            self.input.click(nx, ny, pause = 0.25)
            return None
        logger.warning('nboat.png not found after Builder Base drag — may still be in Builder Base')

    
    def _multi_run_collect_home_village_resources(self):
        '''Multi-run: tap Home Village collect bubbles if visible, before taking the boat to Builder Base.'''
        cb = getattr(self, '_status_callback', None)
        logger.info('Multi-run: Home Village collect (hgold, helixir, hdelixir)')
        if cb:
            cb('Multi-run: Home Village collect')
        self._zoom_out_max()
        for tpl in ('hgold.png', 'helixir.png', 'hdelixir.png'):
            self._check_stop()
            (rx, ry) = self._find_template_once(tpl, threshold = 0.7)
            if not rx:
                continue
            self.input.click(rx, ry, pause = 0.15)

    
    def _multi_run_builder_base_after_session(self):
        """
Multi-run only: after an account's farming session, collect Home Village resources if icons
appear, open the secondary base via boat, collect builder resources if icons appear,
optionally run the clock boost chain, then leave Builder Base.
"""
        self._multi_run_collect_home_village_resources()
        cb = getattr(self, '_status_callback', None)
        msg = 'Multi-run: Builder Base (boat → collect)'
        logger.info(msg)
        if cb:
            cb(msg)
        self._zoom_out_max()
        (bx, by) = self._wait_for_image('boat.png', timeout = 15, error = False)
        if not bx:
            logger.warning('Multi-run: boat.png not found — skipping Builder Base step')
            return None
        self.input.click(bx, by, pause = 0.2)
        if self.stop_event.wait(1):
            self._check_stop()
        for tpl in ('bgold.png', 'belixir.png', 'bgem.png'):
            self._check_stop()
            (rx, ry) = self._find_template_once(tpl, threshold = 0.7)
            if not rx:
                continue
            self.input.click(rx, ry, pause = 0.15)
        self._check_stop()
        (cx, cy) = self._wait_for_image('bclock.png', timeout = 2, error = False)
        if cx:
            self.input.click(cx, cy, pause = 0.2)
            if self.stop_event.wait(1):
                self._check_stop()
            (cbx, cby) = self._wait_for_image('clockboost.png', timeout = 10, error = False)
            if cbx:
                self.input.click(cbx, cby, pause = 0.2)
            if self.stop_event.wait(1):
                self._check_stop()
            (bux, buy) = self._wait_for_image('boost.png', timeout = 10, error = False)
            if bux:
                self.input.click(bux, buy, pause = 0.15)
        self._leave_builder_base_with_nboat(settle_before_drag = True)

    
    def _frame_shows_supercell_login_prompt(self, frame):
        """True if OCR sees the Supercell ID login line (list scroll won't help)."""
        if frame is None or frame.size == 0:
            return False
        words = self.vision.find_words_ocr(frame)
        blob = ' '.join([ w.text for w in words ]).lower()
        if 'supercell id' in blob:
            return True
        if 'log in' in blob and 'supercell' in blob:
            return True
        return False

    
    def _scroll_player_list_with_drag(self, frame):
        '''Drag ~200px upward from lower-right (client coords) to scroll the change-user list.'''
        if frame is None or frame.size == 0:
            return None
        (h, w) = frame.shape[:2]
        x1 = int(w * 0.86) + random.randint(-15, 15)
        x1 = max(int(w * 0.72), min(w - 8, x1))
        y1 = int(h * 0.86) + random.randint(-12, 12)
        y1 = max(int(h * 0.55), min(h - 12, y1))
        y2 = max(int(h * 0.12), y1 - 200)
        x2 = x1
        self.input.mouse_down(x1, y1)
        self.input.human_move(x1, y1, x2, y2, duration = random.uniform(0.28, 0.42))
        self.input.mouse_up(x2, y2)

    
    def _wait_for_player_name(self, text, timeout = 25, error = True, region = None, **ocr_kwargs):
        '''
Poll screenshots until OCR finds ``text`` (substring match) and return its click center;
after each failed OCR pass, drag upward in the lower-right to scroll the account list.
Raises RuntimeError while the "Log in to Supercell ID" prompt shows instead.

OCR is limited to the right half of the window unless ``region`` is passed explicitly.
'''
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(0.5):
                    return (None, None)
                continue
            self._update_config_size(frame)
            roi = region if not region is None else VisionService.right_half_region(frame)
            (x, y) = self.vision.find_word_on_screen(frame, text, region = roi, **ocr_kwargs)
            if x:
                return (x, y)
            if self._frame_shows_supercell_login_prompt(frame):
                msg = f'''Multi-run: "Log in to Supercell ID" is showing and {text!r} was not found — log in or dismiss that screen, then retry.'''
                logger.warning(msg)
                cb = getattr(self, '_status_callback', None)
                if cb:
                    cb(msg)
                raise RuntimeError(msg)
            self._scroll_player_list_with_drag(frame)
            if self.stop_event.wait(0.45):
                return (None, None)
            if error:
                logger.warning(f'''Timeout waiting for player name OCR match: {text!r}''')
        return (None, None)

    
    def _dismiss_open_popup(self, allow_okay = True):
        '''Best-effort close of whatever popup is on screen (okay/exit) so the flow underneath is usable again.'''
        frame = self.window.screenshot()
        if frame is None:
            return False
        self._update_config_size(frame)
        return self._dismiss_okay_or_exit_on_frame(frame, allow_okay = allow_okay)


    def _ensure_valkyrie_army_from_recipes(self):
        '''If Valkyrie army template is missing, load it from Saved Recipes. Returns False on failure.'''
        (vx, vy) = self._wait_for_image('valkarmy.png', timeout = 3, error = False)
        if vx:
            return True
        (sx, sy) = self._wait_for_image('savedrecipes.png')
        if not sx:
            logger.warning('Saved Recipes button not found while ensuring Valkyrie army')
            return False
        self.input.click(sx, sy, pause = 0.2)
        (rx, ry) = self._wait_for_image('valkrecipe.png')
        if not rx:
            logger.warning('Valkyrie recipe template not found')
            self._dismiss_open_popup()  # close the recipes popup we opened
            return False
        (ux, uy) = self._wait_for_image('use.png', y_anchor = ry, y_slop = 200)
        if not ux:
            logger.warning('Use button not found near Valkyrie recipe row')
            self._dismiss_open_popup()  # close the recipes popup we opened
            return False
        self.input.click(ux, uy, pause = 0.2)
        if self.stop_event.wait(0.35):
            return False
        (vx2, _) = self._wait_for_image('valkarmy.png', timeout = 5, error = False)
        if not vx2:
            logger.warning('valkarmy.png still not visible after applying saved recipe')
            return False
        return True

    
    def _search_region_for_template(self, frame, template, region = None, y_anchor = None, y_slop = 200):
        if not region is None:
            return region
        if not y_anchor is None:
            (h, w) = frame.shape[:2]
            y0 = max(0, y_anchor - y_slop)
            y1 = min(h, y_anchor + y_slop)
            return (0, y0, w, y1 - y0)
        if template in TOP_HALF_BOT_TEMPLATES:
            return VisionService.top_half_region(frame)
        if template in BOTTOM_HALF_BOT_TEMPLATES:
            return VisionService.bottom_half_region(frame)

    
    def _find_template_once(self, template, region = None, y_anchor = None, y_slop = 200, threshold = 0.8):
        '''One screenshot; match template or return (None, None). No polling.'''
        self._check_stop()
        frame = self.window.screenshot()
        if frame is None:
            return (None, None)
        self._update_config_size(frame)
        search_region = self._search_region_for_template(frame, template, region, y_anchor, y_slop)
        return self.vision.find_template(frame, template, threshold = threshold, region = search_region)

    
    def _wait_for_any_image(self, templates, timeout = 10, error = True, threshold = 0.8, region = None, region_from_frame = None, label_after = _LABEL_FALLBACK_AFTER):
        '''First ordered template match wins (checked left-to-right each frame).'''
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(0.5):
                    return (None, None)
                continue
            self._update_config_size(frame)
            if self._battle_rewards.handle(frame):
                continue
            ocr = time.time() - start >= label_after
            search_region = region
            if search_region is None and region_from_frame is not None:  # [recovered: both conditions were inverted]
                search_region = region_from_frame(frame)
            for template in templates:
                tpl_region = search_region
                if tpl_region is None:
                    tpl_region = self._search_region_for_template(frame, template, None, None, 200)
                (x, y) = self.vision.find_control(frame, template, threshold = threshold, region = tpl_region, ocr = ocr)
                if x:  # [recovered: was an unconditional `return`, so only the first template was ever checked]
                    return (x, y)
            if self.stop_event.wait(0.5):
                return (None, None)
        if error:
            logger.warning(f'''Timeout waiting for any of {templates}''')
        return (None, None)

    
    def _wait_for_image(self, template, timeout = 10, error = True, region = None, y_anchor = None, y_slop = 200, threshold = 0.8, label_after = _LABEL_FALLBACK_AFTER):
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(0.5):
                    return (None, None)
                continue
            self._update_config_size(frame)
            if self._battle_rewards.handle(frame):
                continue
            search_region = self._search_region_for_template(frame, template, region, y_anchor, y_slop)
            ocr = time.time() - start >= label_after
            (x, y) = self.vision.find_control(frame, template, threshold = threshold, region = search_region, ocr = ocr)
            if x:
                return (x, y)
            if self.stop_event.wait(0.5):
                return (None, None)
        if error:
            logger.warning(f'''Timeout waiting for {template}''')
        return (None, None)


