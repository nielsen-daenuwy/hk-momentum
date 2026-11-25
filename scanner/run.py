"""Run one scan:  python -m scanner.run

Success -> writes site/data/latest.json.  Failure -> latest.json is left alone, so the site keeps
showing the last good scan, and site/data/status.json records what went wrong."""
import json
import math
import os
import sys
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as cfg, engine as en, prices, universe

DATA = Path(__file__).resolve().parent.parent / "site" / "data"


def clean(o):
    """Plain JSON types; NaN/inf become null (NaN is not valid JSON and would break the page)."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return round(float(o), 5) if math.isfinite(o) else None
    return o


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean(obj), ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    os.replace(tmp, path)


def scan(uni, n_listed, bars, hsi, hsi_label, warnings):
    """All inputs are already downloaded -> the JSON payload."""
    if len(bars) < cfg.MIN_COVERAGE * len(uni):
        raise RuntimeError(f"only {len(bars)} of {len(uni)} stocks downloaded")
    vol = pd.DataFrame({s: d["volume"] for s, d in bars.items()})
    days = prices.sessions(vol)
    asof = days[-1]
    stale = (asof - hsi.index.max()).days
    if stale > 4:
        raise RuntimeError(f"HSI data is {stale} days behind the stock data")
    if asof not in hsi.index:
        warnings.append(f"no index close for {asof.date()}; previous close used")
    hsi = hsi[hsi.index <= asof].reindex(days).ffill().dropna()

    fails, rows = Counter(), {}
    for sym in uni.index:
        if sym not in bars:
            fails["download"] += 1
            continue
        df = bars[sym]
        df = df[df.index.isin(days) & (df["volume"] > 0)]
        why = en.liquidity(df, days) if len(df) else "traded"
        if why:
            fails[why] += 1
            continue
        rows[sym] = en.raw(df, hsi)
    if len(rows) < 30:
        raise RuntimeError(f"only {len(rows)} stocks passed the liquidity filter: {dict(fails)}")
    t = pd.DataFrame.from_dict(rows, orient="index")
    for c in ("close", "ret5", "ret10", "rs20", "rvol", "rsi", "atr", "ema50"):
        t[c] = t[c].astype(float)
    bad = t[["ret10", "rs20", "breakout", "rvol", "rsi", "atr", "close_pos", "ext"]].astype(float)
    ok = np.isfinite(bad).all(axis=1) & (t["atr"] > 0)
    fails["bad data"] += int((~ok).sum())
    t = t[ok]
    pct = en.factor_table(t)
    reg = en.regime(hsi, t["above20ma"].mean())
    reg["index_name"] = hsi_label

    stocks = []
    for sym in t.index:
        r, u, p = t.loc[sym].to_dict(), uni.loc[sym], pct.loc[sym].to_dict()
        pr, pe = en.penalties(r)
        tag = en.setup(r)
        good, warn = en.chips(r)
        s = dict(code=u["code"], tv=f"HKEX:{u['code']}", name=u["name"], long=u["long"], sector=u["sector"],
                 mcap=u["mcap"], close=r["close"], chg=r["chg"], ret5=r["ret5"], ret10=r["ret10"],
                 rs20=r["rs20"], rsi=r["rsi"], rvol=r["rvol"], turnover=round(r["turnover"]),
                 pct={k: round(v, 1) for k, v in p.items()}, pen=round(pr + pe, 1),
                 score=round(en.score(p, pr + pe), 2), setup=tag)
        if tag:
            s.update(plan=en.plan(r, tag), chips=good, warn=warn, spark=r["spark"])
        stocks.append(s)
    stocks.sort(key=lambda s: -s["score"])
    have_px = len(uni) - fails["download"]
    funnel = [["HKEX Main Board equities", n_listed],
              [f"Market cap at least HK${cfg.MIN_MARKET_CAP / 1e9:g}bn", len(uni)],
              ["Price history downloaded", have_px],
              ["Passed the liquidity filter", len(stocks)],
              ["Showing a setup", sum(1 for s in stocks if s["setup"])]]
    return dict(asof=str(asof.date()), generated_at=datetime.now(prices.HKT).isoformat(timespec="seconds"),
                regime=reg, funnel=funnel, rejected=dict(fails), weights=cfg.WEIGHTS, labels=cfg.LABELS,
                picks=cfg.PICKS, breadth_rules=[cfg.BREADTH_ON, cfg.BREADTH_OFF], hsi_ma_days=cfg.HSI_MA,
                warnings=warnings, stocks=stocks)


def main():
    now = datetime.now(prices.HKT).isoformat(timespec="seconds")
    try:
        warnings = []
        uni, n = universe.build(warnings)
        print(f"{n} Main Board equities, {len(uni)} with market cap >= {cfg.MIN_MARKET_CAP / 1e9:g}bn")
        bars = {s: prices.drop_unfinished(d) for s, d in prices.download(list(uni.index)).items()}
        bars = {s: d for s, d in bars.items() if len(d)}
        hsi, label = prices.index_close()
        out = scan(uni, n, bars, prices.drop_unfinished(hsi), label, warnings)
        old = DATA / "latest.json"
        if old.exists() and json.loads(old.read_text())["asof"] > out["asof"]:
            raise RuntimeError(f"new data ({out['asof']}) is older than what is already published")
        write(old, out)
        msg = "ok" if out["asof"] == now[:10] else f"No new session; latest trading day is {out['asof']}"
        write(DATA / "status.json", dict(ok=True, checked_at=now, message=msg))
        print(f"{out['asof']}: {out['regime']['label']}, funnel {out['funnel']}, rejected {out['rejected']}")
        for s in [s for s in out["stocks"] if s["setup"]][:cfg.PICKS[out["regime"]["label"]]]:
            print(f"  {s['tv']:<11}{s['name']:<18}{s['score']:>6.1f}  {s['setup']:<20} {s['plan']['entry_lo']}-"
                  f"{s['plan']['entry_hi']} stop {s['plan']['stop']} target {s['plan']['target']} {s['chips']} {s['warn']}")
    except Exception as e:
        traceback.print_exc()
        write(DATA / "status.json", dict(ok=False, checked_at=now, message=str(e)[:300]))
        sys.exit(1)


if __name__ == "__main__":
    main()
