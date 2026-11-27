"""Daily bars from Yahoo. Prices are split-adjusted, not dividend-adjusted (same as the chart)."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from . import config as cfg

HKT = ZoneInfo("Asia/Hong_Kong")


def _batch(symbols):
    df = yf.download(symbols, period=cfg.HISTORY_PERIOD, interval="1d", auto_adjust=False,
                     progress=False, group_by="ticker", threads=True)
    out = {}
    for s in symbols:
        if s not in df.columns.get_level_values(0):
            continue
        d = df[s][["Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower)
        d = d.dropna(subset=["close"])
        if len(d):
            d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
            out[s] = d[~d.index.duplicated(keep="last")]
    return out


def download(symbols):
    got, todo = {}, list(symbols)
    for rnd in range(cfg.DOWNLOAD_ROUNDS):
        for i in range(0, len(todo), cfg.BATCH_SIZE):
            try:
                got.update(_batch(todo[i:i + cfg.BATCH_SIZE]))
            except Exception as e:
                print(f"  batch failed: {e!r}")
            time.sleep(1)
        todo = [s for s in todo if s not in got]
        print(f"  round {rnd + 1}: {len(got)} downloaded, {len(todo)} missing")
        if not todo:
            break
        time.sleep(15 * (rnd + 1))
    return got


def fill_recent(close, sym):
    """Yahoo sometimes drops the latest daily index bar; rebuild it from hourly closes."""
    try:
        h = yf.Ticker(sym).history(period="5d", interval="1h")["Close"].dropna()
        h.index = h.index.tz_convert(HKT).tz_localize(None).normalize()
        return with_missing(close, h.groupby(level=0).last())
    except Exception as e:
        print(f"  hourly {sym}: {e!r}")
        return close


def with_missing(close, extra):
    """Add days that `close` lacks; never overwrite a day it already has."""
    return pd.concat([close, extra[~extra.index.isin(close.index)]]).sort_index()


def index_close(need):
    """Hang Seng Index closes that include `need`; Tracker Fund (2800) stands in if ^HSI does not."""
    for sym, label in (("^HSI", "Hang Seng Index"), ("2800.HK", "Tracker Fund 2800 (HSI proxy)")):
        for _ in range(3):
            try:
                d = _batch([sym]).get(sym)
                if d is not None and len(d) > cfg.HSI_MA + 10:
                    close = fill_recent(d["close"], sym)
                    if need in close.index:
                        return close, label
                    print(f"  {sym}: no close for {need.date()}")
                    break
            except Exception as e:
                print(f"  {sym}: {e!r}")
            time.sleep(5)
    raise RuntimeError(f"no Hang Seng Index or Tracker Fund close for {need.date()}")


def drop_unfinished(df, now=None):
    """Ignore today's bar until the close has been published: EOD data only."""
    now = now or datetime.now(HKT)
    cut = pd.Timestamp(now.date())
    if (now.hour, now.minute) < cfg.EOD_READY:
        cut -= pd.Timedelta(days=1)
    return df[df.index <= cut]


def sessions(volume):
    """Trading days = dates when at least half of all names traded (holiday/typhoon-proof)."""
    n = (volume > 0).sum(axis=1)
    days = n[n >= 0.5 * n.tail(60).median()].index
    if len(days) < cfg.MIN_HISTORY:
        raise RuntimeError("not enough trading sessions in the download")
    latest, typical = n[days[-1]], n[days[-21:-1]].median()
    if latest < cfg.MIN_COVERAGE * typical:
        raise RuntimeError(f"{days[-1].date()} looks incomplete: {latest} of ~{typical:.0f} names have data")
    return days
