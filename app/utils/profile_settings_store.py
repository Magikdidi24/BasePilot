'''Profile preferences (JSON) under LOCALAPPDATA\\BasePilot, next to ``player_list.json``.'''
from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from typing import List, Optional
from app.utils.common import ensure_dir, get_user_app_data_dir
EARTHQUAKE_METHOD_CURVE = 'Curve Placement'
EARTHQUAKE_METHOD_RANDOM = 'Random Placement'
EARTHQUAKE_METHOD_LEARN = 'Learn (the one that loots more)'  # drawn each raid: app.core.bb_learning.QuakeLearner
EARTHQUAKE_METHOD_OPTIONS = (EARTHQUAKE_METHOD_CURVE, EARTHQUAKE_METHOD_RANDOM, EARTHQUAKE_METHOD_LEARN)
SETTINGS_FILENAME = 'settings.json'
WALL_UPGRADE_THRESHOLD_M_DEFAULT = 3
WALL_UPGRADE_THRESHOLD_M_MAX = 20
BB_WALL_THRESHOLD_K_DEFAULT = 0  # Builder Base walls: 0 = only when a storage is full
BB_WALL_THRESHOLD_K_MAX = 20000  # thousands of Builder Base gold or elixir
RESERVE_BUILDERS_DEFAULT = 1
RESERVE_BUILDERS_MAX = 5
UPGRADE_ORDER_PRICIEST = 'priciest'
UPGRADE_ORDER_CHEAPEST = 'cheapest'
UPGRADE_ORDER_OPTIONS = (UPGRADE_ORDER_PRICIEST, UPGRADE_ORDER_CHEAPEST)
# Clan assist (see app/core/clan.py). The chat button carries no text and no
# template, so it is calibrated once per install and stored as a fraction of the
# capture — that survives window resizes, and the aspect key it was picked on is
# kept alongside so a 16:9 <-> 16:10 switch can be called out instead of clicking
# a stale spot.
CLAN_DONATE_TROOP_AUTO = 'auto'
CLAN_DONATE_TROOP_OPTIONS = (CLAN_DONATE_TROOP_AUTO, 'valkyries', 'sneaky goblins', 'super minions', 'edrags')
CLAN_DONATE_COUNT_DEFAULT = 0  # 0 = donate until the game greys the troop out
CLAN_DONATE_COUNT_MAX = 10
CLAN_MIN_ELIXIR_K_DEFAULT = 500  # donating costs elixir to replace; keep a floor
CLAN_MIN_ELIXIR_K_MAX = 20000
CLAN_DONATE_INTERVAL_M_DEFAULT = 0  # 0 = donate after every raid
CLAN_DONATE_INTERVAL_M_MIN = 0
CLAN_DONATE_INTERVAL_M_MAX = 60
CLAN_REQUEST_INTERVAL_M_DEFAULT = 30
CLAN_REQUEST_INTERVAL_M_MIN = 5
CLAN_REQUEST_INTERVAL_M_MAX = 240
# Loot filter (see app/core/loot_filter.py): the minimum a base must hold to be worth
# the army and the minutes. Thousands, so the UI stays readable; 0 disables the check.
# 0 = off: opt-in, because every Next costs a search fee and a default would change farming for everyone.
ATTACK_MIN_GOLD_K_DEFAULT = 0
ATTACK_MIN_ELIXIR_K_DEFAULT = 0
ATTACK_MIN_LOOT_K_MAX = 5000
ATTACK_MIN_DARK_K_DEFAULT = 0
ATTACK_MIN_DARK_K_MAX = 200  # dark elixir, in thousands too: a base holds 1-30k
ATTACK_MAX_SKIPS_DEFAULT = 10
ATTACK_MAX_SKIPS_MAX = 50

@dataclass
class ProfileSettings:
    earthquake_method: 'str' = EARTHQUAKE_METHOD_CURVE
    wall_upgrade_threshold_m: 'int' = WALL_UPGRADE_THRESHOLD_M_DEFAULT
    reserve_builders: 'int' = RESERVE_BUILDERS_DEFAULT
    upgrade_order: 'str' = UPGRADE_ORDER_PRICIEST
    clan_dry_run: 'bool' = True  # first run on a fresh calibration reads and clicks nothing
    clan_chat_point: 'Optional[List[float]]' = None  # [fx, fy] fractions of the capture
    clan_chat_point_aspect: 'Optional[str]' = None
    clan_donate_troop: 'str' = CLAN_DONATE_TROOP_AUTO
    clan_donate_count: 'int' = CLAN_DONATE_COUNT_DEFAULT  # 0 = until the troop greys out
    clan_min_elixir_k: 'int' = CLAN_MIN_ELIXIR_K_DEFAULT  # 0 = donate whatever the HUD says
    clan_donate_interval_m: 'int' = CLAN_DONATE_INTERVAL_M_DEFAULT
    clan_request_interval_m: 'int' = CLAN_REQUEST_INTERVAL_M_DEFAULT
    attack_min_gold_k: 'int' = ATTACK_MIN_GOLD_K_DEFAULT
    attack_min_elixir_k: 'int' = ATTACK_MIN_ELIXIR_K_DEFAULT
    attack_min_dark_k: 'int' = ATTACK_MIN_DARK_K_DEFAULT
    attack_max_skips: 'int' = ATTACK_MAX_SKIPS_DEFAULT  # Next presses per attack cycle; 0 = attack anything
    bb_wall_threshold_k: 'int' = BB_WALL_THRESHOLD_K_DEFAULT


def get_settings_path():
    dest = get_user_app_data_dir() / SETTINGS_FILENAME
    ensure_dir(dest.parent)
    return dest


def _normalize_earthquake_method(raw):
    if raw in EARTHQUAKE_METHOD_OPTIONS:
        return str(raw)
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s == 'random placement':
            return EARTHQUAKE_METHOD_RANDOM
        if s == 'curve placement':
            return EARTHQUAKE_METHOD_CURVE
        if s.startswith('learn'):
            return EARTHQUAKE_METHOD_LEARN
    return EARTHQUAKE_METHOD_CURVE


def _normalize_wall_threshold_m(raw):
    '''Millions of gold/elixir that trigger wall upgrades; 0 = only when storages are full.'''
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):  # OverflowError: int(inf)
        return WALL_UPGRADE_THRESHOLD_M_DEFAULT
    return max(0, min(WALL_UPGRADE_THRESHOLD_M_MAX, value))


def _normalize_upgrade_order(raw):
    if isinstance(raw, str) and raw.strip().lower() in UPGRADE_ORDER_OPTIONS:
        return raw.strip().lower()
    return UPGRADE_ORDER_PRICIEST


def _normalize_reserve_builders(raw):
    '''Builders the auto-upgrader must leave free (the wall flow spends through them).
    0 = every free builder may be used; walls-maxed accounts want 0.'''
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):  # OverflowError: int(inf)
        return RESERVE_BUILDERS_DEFAULT
    return max(0, min(RESERVE_BUILDERS_MAX, value))


def _normalize_clan_chat_point(raw):
    '''``[fx, fy]`` fractions of the capture, or None when not calibrated. Anything
    outside 0..1 is a stale/foreign value and is dropped rather than clicked.'''
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    try:
        (fx, fy) = (float(raw[0]), float(raw[1]))
    except (TypeError, ValueError, OverflowError):  # OverflowError: float() of an int past 1.8e308
        return None
    if not 0 <= fx <= 1 or not 0 <= fy <= 1:
        return None
    return [fx, fy]


def _normalize_clan_chat_point_aspect(raw):
    from app.config import ASPECT_16_9, ASPECT_16_10
    if isinstance(raw, str) and raw.strip() in (ASPECT_16_9, ASPECT_16_10):
        return raw.strip()
    return None


def _normalize_clan_donate_troop(raw):
    if isinstance(raw, str) and raw.strip().lower() in CLAN_DONATE_TROOP_OPTIONS:
        return raw.strip().lower()
    return CLAN_DONATE_TROOP_AUTO


def _normalize_int(raw, default, low, high):
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):  # OverflowError: int(inf)
        return default
    return max(low, min(high, value))


def _settings_from(get):
    '''ProfileSettings with every field read through ``get(field, default)`` and brought into
    range, for load (the file) and save alike.'''
    return ProfileSettings(
        earthquake_method = _normalize_earthquake_method(get('earthquake_method', None)),
        wall_upgrade_threshold_m = _normalize_wall_threshold_m(get('wall_upgrade_threshold_m', WALL_UPGRADE_THRESHOLD_M_DEFAULT)),
        reserve_builders = _normalize_reserve_builders(get('reserve_builders', RESERVE_BUILDERS_DEFAULT)),
        upgrade_order = _normalize_upgrade_order(get('upgrade_order', UPGRADE_ORDER_PRICIEST)),
        clan_dry_run = bool(get('clan_dry_run', True)),  # the one default get must supply: bool(None) is False
        clan_chat_point = _normalize_clan_chat_point(get('clan_chat_point', None)),
        clan_chat_point_aspect = _normalize_clan_chat_point_aspect(get('clan_chat_point_aspect', None)),
        clan_donate_troop = _normalize_clan_donate_troop(get('clan_donate_troop', CLAN_DONATE_TROOP_AUTO)),
        clan_donate_count = _normalize_int(get('clan_donate_count', None), CLAN_DONATE_COUNT_DEFAULT, 0, CLAN_DONATE_COUNT_MAX),
        clan_min_elixir_k = _normalize_int(get('clan_min_elixir_k', None), CLAN_MIN_ELIXIR_K_DEFAULT, 0, CLAN_MIN_ELIXIR_K_MAX),
        clan_donate_interval_m = _normalize_int(get('clan_donate_interval_m', None), CLAN_DONATE_INTERVAL_M_DEFAULT, CLAN_DONATE_INTERVAL_M_MIN, CLAN_DONATE_INTERVAL_M_MAX),
        clan_request_interval_m = _normalize_int(get('clan_request_interval_m', None), CLAN_REQUEST_INTERVAL_M_DEFAULT, CLAN_REQUEST_INTERVAL_M_MIN, CLAN_REQUEST_INTERVAL_M_MAX),
        attack_min_gold_k = _normalize_int(get('attack_min_gold_k', None), ATTACK_MIN_GOLD_K_DEFAULT, 0, ATTACK_MIN_LOOT_K_MAX),
        attack_min_elixir_k = _normalize_int(get('attack_min_elixir_k', None), ATTACK_MIN_ELIXIR_K_DEFAULT, 0, ATTACK_MIN_LOOT_K_MAX),
        attack_min_dark_k = _normalize_int(get('attack_min_dark_k', None), ATTACK_MIN_DARK_K_DEFAULT, 0, ATTACK_MIN_DARK_K_MAX),
        attack_max_skips = _normalize_int(get('attack_max_skips', None), ATTACK_MAX_SKIPS_DEFAULT, 0, ATTACK_MAX_SKIPS_MAX),
        bb_wall_threshold_k = _normalize_int(get('bb_wall_threshold_k', None), BB_WALL_THRESHOLD_K_DEFAULT, 0, BB_WALL_THRESHOLD_K_MAX))


def load_profile_settings():
    path = get_settings_path()
    if not path.is_file():
        return ProfileSettings()

    try:
        raw = json.loads(path.read_text(encoding = 'utf-8-sig'))  # -sig: Notepad's UTF-8 with BOM too
        if not isinstance(raw, dict):
            return ProfileSettings()
        return _settings_from(raw.get)
    except (ValueError, OSError):  # bad JSON or UTF-8, an int of over 4300 digits: all ValueErrors
        return ProfileSettings()  # [recovered: decompiler turned this into `return None`, crashing every caller on a corrupt settings.json]



def save_profile_settings(settings):
    path = get_settings_path()
    path.parent.mkdir(parents = True, exist_ok = True)
    normalized = _settings_from(lambda field, default: getattr(settings, field, default))
    payload = asdict(normalized)
    path.write_text(json.dumps(payload, indent = 2), encoding = 'utf-8')
