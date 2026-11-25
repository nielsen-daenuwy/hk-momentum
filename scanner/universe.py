"""Which stocks exist, and how big they are.

HKEX list of securities -> Main Board ordinary equities (HKD counter).
Yahoo bulk screener     -> market cap and sector.
Both are cached in cache/ so one bad download does not stop the scan.
"""
import io
import json
import time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
from yfinance import EquityQuery as Q

from . import config as cfg

CACHE = Path(__file__).resolve().parent.parent / "cache"
SECTORS = ["Basic Materials", "Communication Services", "Consumer Cyclical", "Consumer Defensive",
           "Energy", "Financial Services", "Healthcare", "Industrials", "Real Estate",
           "Technology", "Utilities"]


def retry(fn, tries=3, wait=10):
    for k in range(tries):
        try:
            return fn()
        except Exception as e:
            if k == tries - 1:
                raise
            print(f"  retrying after: {e!r}")
            time.sleep(wait * (k + 1))


def cached(name, fn, warnings):
    path = CACHE / name
    try:
        data = retry(fn)
        CACHE.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False))
        return data
    except Exception as e:
        if path.exists():
            warnings.append(f"{name}: live download failed, using the last saved copy")
            return json.loads(path.read_text())
        raise RuntimeError(f"{name} unavailable and no saved copy: {e!r}") from e


def parse_list(content):
    """HKEX xlsx -> {code: short name}. 'Equity Securities (Main Board)' already leaves out
    ETFs, REITs, warrants, CBBCs, GEM, trading-only stocks and depositary receipts."""
    raw = pd.read_excel(io.BytesIO(content), header=None, dtype=str)
    head = next(i for i in range(10) if "Stock Code" in raw.iloc[i].values)
    df = raw.iloc[head + 1:].copy()
    df.columns = raw.iloc[head]
    ok = ((df["Category"].str.strip() == "Equity")
          & (df["Sub-Category"].str.strip() == "Equity Securities (Main Board)")
          & (df["Trading Currency"].str.strip() == "HKD"))
    df = df[ok]
    out = {str(int(c)): n.strip() for c, n in zip(df["Stock Code"], df["Name of Securities"])}
    if len(out) < 1500:
        raise ValueError(f"HKEX list looks wrong: only {len(out)} Main Board equities")
    return out


def hkex_list():
    r = requests.get(cfg.HKEX_LIST_URL, timeout=90, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return parse_list(r.content)


def _screen(*extra):
    out, off = [], 0
    while True:
        q = Q("and", [Q("eq", ["exchange", "HKG"]),
                      Q("gt", ["intradaymarketcap", int(cfg.MIN_MARKET_CAP * 0.9)]), *extra])
        r = yf.screen(q, size=250, offset=off, sortField="intradaymarketcap", sortAsc=False)
        out += r["quotes"]
        off += 250
        if off >= r["total"] or not r["quotes"]:
            return out


def yahoo_caps():
    info = {}
    for q in _screen():
        if q.get("marketCap"):
            info[q["symbol"]] = {"mcap": q["marketCap"], "long": q.get("longName") or "", "sector": "Other"}
    for s in SECTORS:
        for q in _screen(Q("eq", ["sector", s])):
            if q["symbol"] in info:
                info[q["symbol"]]["sector"] = s
    if len(info) < 300:
        raise ValueError(f"Yahoo returned only {len(info)} market caps")
    return info


def build(warnings):
    """-> (DataFrame[symbol: code, name, long, sector, mcap], number of Main Board equities)"""
    listed = cached("hkex_list.json", hkex_list, warnings)
    caps = cached("yahoo_caps.json", yahoo_caps, warnings)
    rows = [dict(symbol=f"{int(c):04d}.HK", code=int(c), name=n, **caps[f"{int(c):04d}.HK"])
            for c, n in listed.items() if f"{int(c):04d}.HK" in caps]
    df = pd.DataFrame(rows).set_index("symbol")
    return df[df["mcap"] >= cfg.MIN_MARKET_CAP], len(listed)
