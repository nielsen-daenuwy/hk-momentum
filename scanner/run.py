"""Run one scan:  python -m scanner.run

Success -> writes site/data/latest.json.  Failure -> latest.json is left alone, so the site keeps
showing the last good scan, and site/data/status.json records what went wrong.  A run that gets
newer prices than are published, but not the latest session, publishes them AND reports failure.

--if-stale : do nothing if the published scan already covers the latest session (scheduled runs)."""
import hashlib
import json
import math
import os
import sys
import traceback
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as cfg, engine as en, events, market_calendar as mc, prices, universe

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


def rules_id():
    """Changes whenever config.py does, so a settings change is always re-published."""
    return hashlib.sha1(Path(cfg.__file__).read_bytes()).hexdigest()[:8]


def check_replace(old, new):
    """Refuse to overwrite published results with older or noticeably thinner ones."""
    if not old:
        return
    if old["asof"] > new["asof"]:
        raise RuntimeError(f"new data ({new['asof']}) is older than what is already published")
    if old["asof"] == new["asof"] and new["coverage"] < old.get("coverage", 0) - 0.03:
        raise RuntimeError(f"new download covers {new['coverage']:.0%} of stocks, the published one "
                           f"{old['coverage']:.0%}; keeping the published one")


def scan(uni, n_listed, bars, hsi, hsi_label, warnings, closed=frozenset()):
    """All inputs are already downloaded -> the JSON payload."""
    if len(bars) < cfg.MIN_COVERAGE * len(uni):
        raise RuntimeError(f"only {len(bars)} of {len(uni)} stocks downloaded")
    vol = pd.DataFrame({s: d["volume"] for s, d in bars.items()})
    days = prices.sessions(vol)
    asof = days[-1]
    if asof not in hsi.index:
        raise RuntimeError(f"no index close for {asof.date()}")
    gaps = [d.date() for d in pd.bdate_range(days[-cfg.TRADED_SESSIONS], asof)
            if mc.is_session(d.date(), closed) and d not in days]
    if gaps:
        warnings.append("no usable prices for " + ", ".join(f"{d.day} {d:%b}" for d in gaps)
                        + "; calculations skip those days")
    coverage = float((vol.loc[asof] > 0).sum() / len(uni))
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
    near = (str(asof.date() - timedelta(days=30)), str(asof.date() + timedelta(days=400)))
    return dict(asof=str(asof.date()), generated_at=datetime.now(prices.HKT).isoformat(timespec="seconds"),
                rules=rules_id(), coverage=coverage, max_risk=cfg.MAX_RISK_PCT, event_window=cfg.EVENT_WINDOW,
                eod_ready=list(cfg.EOD_READY), closed_days=sorted(d for d in closed if near[0] <= d <= near[1]),
                regime=reg, funnel=funnel, rejected=dict(fails), weights=cfg.WEIGHTS, labels=cfg.LABELS,
                picks=cfg.PICKS, breadth_rules=[cfg.BREADTH_ON, cfg.BREADTH_OFF], hsi_ma_days=cfg.HSI_MA,
                warnings=warnings, stocks=stocks)


def main(argv=()):
    clock = datetime.now(prices.HKT)
    now = clock.isoformat(timespec="seconds")
    try:
        warnings = []
        closed = mc.closed_days(warnings)
        expected = mc.expected_session(clock, closed).isoformat()
        latest = DATA / "latest.json"
        old = json.loads(latest.read_text()) if latest.exists() else None
        same_rules = bool(old) and old.get("rules") == rules_id()
        if "--if-stale" in argv and same_rules and old["asof"] >= expected:
            print(f"already current: published {old['asof']}, latest session {expected}")
            return
        uni, n = universe.build(warnings)
        print(f"{n} Main Board equities, {len(uni)} with market cap >= {cfg.MIN_MARKET_CAP / 1e9:g}bn")
        bars = {s: prices.drop_unfinished(d) for s, d in prices.download(list(uni.index)).items()}
        bars = {s: d for s, d in bars.items() if len(d)}
        days = prices.sessions(pd.DataFrame({s: d["volume"] for s, d in bars.items()}))
        hsi, label = prices.index_close(days[-1])
        out = scan(uni, n, bars, prices.drop_unfinished(hsi), label, warnings, closed)
        behind = out["asof"] < expected
        # Behind and nothing newer than what is up: leave the published file (and its timestamp) alone.
        if not (behind and same_rules and out["asof"] <= old["asof"]):
            events.attach(out, closed, warnings)
            check_replace(old, out)
            write(latest, out)
            report(out)
        if behind:
            raise RuntimeError(f"prices only reach {out['asof']} but the {expected} session has closed")
        write(DATA / "status.json", dict(ok=True, checked_at=now, expected=expected, message="ok"))
    except Exception as e:
        traceback.print_exc()
        write(DATA / "status.json", dict(ok=False, checked_at=now, message=str(e)[:300]))
        sys.exit(1)


def report(out):
    print(f"{out['asof']}: {out['regime']['label']}, funnel {out['funnel']}, rejected {out['rejected']}")
    setups = [s for s in out["stocks"] if s["setup"]]
    wide = [s["name"] for s in setups if s["plan"]["too_wide"]]
    print(f"stop wider than {cfg.MAX_RISK_PCT:g}%: {len(wide)} setups not shown {wide[:8]}")
    for s in [s for s in setups if not s["plan"]["too_wide"]][:cfg.PICKS[out["regime"]["label"]]]:
        p = s["plan"]
        print(f"  {s['tv']:<11}{s['name']:<18}{s['score']:>6.1f}  {s['setup']:<20} {p['order']:<8}{p['entry_lo']}-"
              f"{p['entry_hi']} stop {p['stop']} ({p['risk_pct']}%) {s['warn']}")


if __name__ == "__main__":
    main(sys.argv[1:])
