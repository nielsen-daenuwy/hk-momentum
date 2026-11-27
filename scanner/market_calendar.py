"""Which days the Hong Kong market trades, so a late or thin download cannot pass as current.

Holidays are the government's general holidays (1823), which HKEX follows. Half-days (eves of
Christmas, New Year and Lunar New Year) are trading days. Since 23 September 2024 the market
stays open through typhoons and black rainstorms; list any exceptional closure in EXTRA_CLOSED.
"""
import json
from datetime import date, timedelta

import requests

from . import config as cfg
from .universe import cached


def parse_holidays(content):
    events = json.loads(content.decode("utf-8-sig"))["vcalendar"][0]["vevent"]
    days = sorted({f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in (e["dtstart"][0] for e in events)})
    if len(days) < 10:
        raise ValueError(f"holiday file looks wrong: {len(days)} days")
    return days


def _fetch():
    r = requests.get(cfg.HOLIDAY_URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return parse_holidays(r.content)


def closed_days(warnings):
    """-> set of 'YYYY-MM-DD' weekdays and others on which there is no session."""
    try:
        days = set(cached("holidays.json", _fetch, warnings))
    except Exception as e:
        warnings.append(f"holiday list unavailable ({e}); a holiday may look like missing data")
        days = set()
    return days | set(cfg.EXTRA_CLOSED)


def is_session(d, closed):
    return d.weekday() < 5 and d.isoformat() not in closed


def expected_session(now, closed):
    """The most recent session whose closing prices should be available at `now` (HKT)."""
    d = now.date()
    if (now.hour, now.minute) < cfg.EOD_READY:
        d -= timedelta(days=1)
    while not is_session(d, closed):
        d -= timedelta(days=1)
    return d


def sessions_after(start, end, closed):
    """Number of sessions after `start`, up to and including `end`."""
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        n += is_session(d, closed)
    return n
