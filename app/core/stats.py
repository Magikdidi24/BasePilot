'''Session statistics from the battle history (:mod:`app.utils.battle_history`): what the
Stats page shows, and its CSV export.

A session is one Start: its records carry the same ``session`` (the start time, ISO).
Home Village records are the loot of a raid (``gold``, ``elixir``, ``dark``); Builder Base
ones its result (``stars``, ``damage``, ``gold``, ``trophies``, the attack ``plan``).
'''
import csv
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

CSV_COLUMNS = ('t', 'session', 'village', 'stars', 'damage', 'gold', 'elixir', 'dark', 'trophies', 'plan', 'army', 'seconds')


@dataclass
class SessionSummary:
    start: datetime
    village: str  # "home", "builder" or "both"
    battles: int
    gold: int
    elixir: int
    dark: int
    hours: float  # from the session's start to its last battle (at least a minute)
    stars: Optional[float] = None  # Builder Base: average per battle
    damage: Optional[float] = None  # Builder Base: average %

    def per_hour(self, amount):
        return amount / self.hours if self.hours > 0 else 0.0


def _when(text):
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def sessions(records):
    '''One :class:`SessionSummary` per session, newest first. Records from before sessions
    were stamped are grouped by day.'''
    groups = {}
    for r in records:
        t = _when(r.get('t'))
        if t is None:
            continue
        key = r.get('session') or t.strftime('%Y-%m-%dT00:00:00')
        groups.setdefault(key, []).append((t, r))
    out = []
    for (key, items) in groups.items():
        start = _when(key) or min(t for (t, _r) in items)
        start = min(start, min(t for (t, _r) in items))
        last = max(t for (t, _r) in items)
        villages = {r.get('village') for (_t, r) in items}
        builder = [r for (_t, r) in items if r.get('village') == 'builder']
        total = lambda k: int(sum(int(r.get(k) or 0) for (_t, r) in items))
        out.append(SessionSummary(
            start = start, village = villages.pop() if len(villages) == 1 else 'both', battles = len(items),
            gold = total('gold'), elixir = total('elixir'), dark = total('dark'),
            hours = max(1 / 60, (last - start).total_seconds() / 3600),
            stars = sum(int(r.get('stars') or 0) for r in builder) / len(builder) if builder else None,
            damage = sum(int(r.get('damage') or 0) for r in builder) / len(builder) if builder else None))
    return sorted(out, key = lambda s: s.start, reverse = True)


def builder_damage(records, last = 40):
    '''(damage %, stars) of the last ``last`` Builder Base battles, oldest first.'''
    battles = [(int(r.get('damage') or 0), int(r.get('stars') or 0)) for r in records if r.get('village') == 'builder' and 'damage' in r]
    return battles[-last:]


def write_csv(records, path):
    '''Every record as a CSV row (:data:`CSV_COLUMNS`), oldest first.'''
    with open(path, 'w', newline = '', encoding = 'utf-8') as f:
        writer = csv.DictWriter(f, fieldnames = CSV_COLUMNS, extrasaction = 'ignore')
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, '') for k in CSV_COLUMNS})
