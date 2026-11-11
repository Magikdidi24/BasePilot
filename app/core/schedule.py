'''Daily start times (Run page → Schedule → Start at set times): the runs the app starts
by itself, with the Run page's settings, while it is open.

A start time is due from its minute for :data:`LATE` (the app checks every few seconds; a
run going on at that time, or a PC waking from sleep, starts it a little later), and once a
day: ``last`` is when the last scheduled start fired. Times are local, written ``HH:MM``
and separated by commas or spaces ("8:00, 13:30 21:00").
'''
import re
from datetime import datetime, time, timedelta
from typing import List, Optional, Sequence, Tuple

LATE = timedelta(minutes = 10)
_TIME = re.compile(r'^(\d{1,2})[:hH.](\d{2})$')


def parse_times(text) -> Tuple[List[time], List[str]]:
    '''``(times, bad)``: the start times written in ``text``, sorted and each once, and the
    words that are no time.'''
    (times, bad) = (set(), [])
    for word in re.split(r'[,;\s]+', str(text or '').strip()):
        if not word:
            continue
        m = _TIME.match(word)
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            times.add(time(int(m.group(1)), int(m.group(2))))
        else:
            bad.append(word)
    return (sorted(times), bad)


def format_times(times: Sequence[time]) -> str:
    return ', '.join(t.strftime('%H:%M') for t in times)


def _occurrences(now: datetime, times: Sequence[time]):
    '''Each time's start on the day before ``now``, that day, and the day after.'''
    for days in (-1, 0, 1):
        day = (now + timedelta(days = days)).date()
        for t in times:
            yield datetime.combine(day, t)


def due(now: datetime, times: Sequence[time], last: Optional[datetime] = None) -> Optional[datetime]:
    '''The start due at ``now`` (the latest one passed less than :data:`LATE` ago that has
    not fired since), or None.'''
    passed = [at for at in _occurrences(now, times) if timedelta(0) <= now - at < LATE and (last is None or last < at)]
    return max(passed) if passed else None


def next_start(now: datetime, times: Sequence[time]) -> Optional[datetime]:
    '''The next start after ``now``, or None without times.'''
    ahead = [at for at in _occurrences(now, times) if at > now]
    return min(ahead) if ahead else None
