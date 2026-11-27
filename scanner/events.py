"""Results announcements close to the scan date - the biggest gap risk on a short hold.

Two sources, neither complete: Yahoo's calendar, and events.csv which you can edit by hand.
No flag does NOT mean no announcement is due.
"""
import csv
from datetime import date
from pathlib import Path

import yfinance as yf

from . import config as cfg
from .market_calendar import sessions_after

MANUAL = Path(__file__).resolve().parent.parent / "events.csv"


def manual(warnings, path=MANUAL):
    """-> {code: [(date, note)]} from events.csv (columns: code,date,note)."""
    out = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                out.setdefault(int(row["code"]), []).append(
                    (date.fromisoformat(row["date"].strip()), (row.get("note") or "").strip() or "Results"))
            except (KeyError, TypeError, ValueError):
                warnings.append(f"events.csv: could not read the line {dict(row)}")
    return out


def yahoo(codes, warnings):
    out, failed = {}, 0
    for code in codes:
        try:
            dates = yf.Ticker(f"{code:04d}.HK").calendar.get("Earnings Date") or []
            out[code] = [(d, "Results") for d in dates if isinstance(d, date)]
        except Exception:
            failed += 1
    if codes and failed > 0.3 * len(codes):
        warnings.append(f"results dates: Yahoo failed for {failed} of {len(codes)} stocks")
    return out


def upcoming(events, asof, closed):
    """The first event from the scan date up to EVENT_WINDOW sessions ahead, or None."""
    near = sorted(e for e in events if e[0] >= asof and sessions_after(asof, e[0], closed) <= cfg.EVENT_WINDOW)
    return near[0] if near else None


def attach(out, closed, warnings, fetch=yahoo, path=MANUAL):
    """Add results flags to every stock that has a setup."""
    asof = date.fromisoformat(out["asof"])
    picks = [s for s in out["stocks"] if s["setup"]]
    found, own = fetch([s["code"] for s in picks], warnings), manual(warnings, path)
    for s in picks:
        e = upcoming(found.get(s["code"], []) + own.get(s["code"], []), asof, closed)
        if e:
            s["results"] = e[0].isoformat()
            s["warn"] = [f"{e[1]} due {e[0].day} {e[0]:%b}"] + s["warn"]
