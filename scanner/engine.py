"""Pure calculations: indicators, factors, setups, trade plans, regime. No network here."""
import math

import numpy as np
import pandas as pd

from . import config as cfg


# ------------------------------------------------------------------ indicators
def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().iloc[-1]
    if dn == 0:
        return 50.0 if up == 0 else 100.0
    return 100 - 100 / (1 + up / dn)


def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean().iloc[-1]


# ------------------------------------------------------------------ HKEX price ticks
TICKS = ((0.25, 0.001), (10, 0.005), (20, 0.01), (50, 0.02), (100, 0.05), (200, 0.1), (500, 0.2),
         (1000, 0.5), (2000, 1.0), (5000, 2.0), (math.inf, 5.0))


def tick(p):
    return next(t for lim, t in TICKS if p < lim)


def to_tick(p, how="nearest"):
    t = tick(p)
    k = p / t
    k = math.floor(k + 1e-9) if how == "down" else math.ceil(k - 1e-9) if how == "up" else round(k)
    return round(k * t, 3)


# ------------------------------------------------------------------ filter + raw values
def liquidity(df, days):
    """None if the stock passes, else the name of the gate it fails. df: bars on session days only."""
    last = df.reindex(days[-cfg.TRADED_SESSIONS:])
    if last["volume"].fillna(0).le(0).any() or last["close"].isna().any():
        return "traded"
    if df["close"].iloc[-1] < cfg.MIN_PRICE:
        return "price"
    if (last["close"] * last["volume"]).mean() < cfg.MIN_AVG_TURNOVER:
        return "turnover"
    if len(df) < cfg.MIN_HISTORY:
        return "history"
    if df["close"].pct_change().tail(cfg.TRADED_SESSIONS).abs().max() > cfg.MAX_ONE_DAY_MOVE:
        return "bad data"
    return None


def raw(df, hsi):
    """All the numbers for one stock, from bars up to and including the scan date."""
    df = df.copy()
    for c in ("open", "high", "low"):
        df[c] = df[c].fillna(df["close"])
    df["high"] = df[["high", "close"]].max(axis=1)
    df["low"] = df[["low", "close"]].min(axis=1)
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    px, rng = c.iloc[-1], h.iloc[-1] - l.iloc[-1]
    e10, e20, e50 = (ema(c, n).iloc[-1] for n in (10, 20, 50))
    prior_high, hi20 = h.iloc[-21:-1].max(), h.iloc[-20:].max()
    a = atr(df)
    return dict(
        close=px, chg=px / c.iloc[-2] - 1, ret5=px / c.iloc[-6] - 1, ret10=px / c.iloc[-11] - 1,
        ret20=px / c.iloc[-21] - 1, rs20=(px / c.iloc[-21] - 1) - (hsi.iloc[-1] / hsi.iloc[-21] - 1),
        ema10=e10, ema20=e20, ema50=e50, trend_n=int(px > e10) + int(px > e20) + int(e20 > e50),
        prior_high=prior_high, hi20=hi20, new_high=bool(px > prior_high), dist_high=px / hi20 - 1,
        breakout=px / prior_high - 1, rvol=v.iloc[-1] / v.iloc[-21:-1].mean(), rsi=rsi(c), atr=a,
        close_pos=(px - l.iloc[-1]) / rng if rng > 0 else 0.5,
        ext=(px - e20) / a if a > 0 else 0.0, swing_low=l.tail(cfg.SWING_LOW_SESSIONS).min(),
        turnover=(c * v).tail(20).mean(), above20ma=bool(px > c.tail(cfg.BREADTH_MA).mean()),
        spark=[float(f"{x:.5g}") for x in c.tail(cfg.SPARK_POINTS)])


# ------------------------------------------------------------------ factor scores
def rsi_fit(r):
    """100 inside the ideal band, sliding to 0 at 20 points below it or 15 above it."""
    if r < cfg.RSI_LOW:
        return max(0.0, 100 - (cfg.RSI_LOW - r) * 5)
    if r > cfg.RSI_HIGH:
        return max(0.0, 100 - (r - cfg.RSI_HIGH) * 100 / 15)
    return 100.0


def volume_value(rvol, chg):
    """Heavy volume only counts in favour on an up day; on a down day it counts against."""
    return rvol if chg >= 0 else -rvol


def percentile(s):
    n = len(s)
    return (s.rank(method="average") - 1) / (n - 1) * 100 if n > 1 else pd.Series(50.0, index=s.index)


def factor_table(t):
    vals = pd.DataFrame({
        "ret5": t["ret5"], "ret10": t["ret10"], "rs20": t["rs20"], "trend": t["trend_n"],
        "breakout": t["breakout"], "volume": [volume_value(a, b) for a, b in zip(t["rvol"], t["chg"])],
        "rsi": t["rsi"].map(rsi_fit), "close": t["close_pos"]}, index=t.index)
    return vals.apply(percentile)


def penalties(r):
    p_rsi = 0.0
    if r["rsi"] > cfg.RSI_PENALTY_FROM:
        p_rsi = min(cfg.RSI_PENALTY_MAX,
                    cfg.RSI_PENALTY_BASE + (r["rsi"] - cfg.RSI_PENALTY_FROM) * cfg.RSI_PENALTY_PER_POINT)
    p_ext = min(cfg.OVEREXT_PENALTY_MAX, max(0.0, r["ext"] - cfg.OVEREXT_ATR) * cfg.OVEREXT_PENALTY_PER_ATR)
    return p_rsi, p_ext


def score(pct, pen, weights=None):
    w = weights or cfg.WEIGHTS
    tot = sum(w.values())
    base = sum(pct[k] * w[k] for k in w) / tot if tot else 0.0
    return min(100.0, max(0.0, base - pen))


# ------------------------------------------------------------------ setups
def setup(r):
    """The setup tag, or None (a stock with no setup is scored but never shown as a pick)."""
    if r["new_high"] and r["trend_n"] >= 2:
        return "Breakout"
    if (r["rvol"] >= cfg.VOL_SURGE and r["chg"] >= cfg.IGNITION_MIN_GAIN
            and r["close_pos"] >= cfg.CLOSE_STRENGTH and r["close"] > r["ema20"]):
        return "Volume Ignition"
    if r["dist_high"] >= -cfg.NEAR_HIGH and r["trend_n"] == 3:
        return "Breakout"
    if (r["ema20"] > r["ema50"] and r["close"] > r["ema50"]
            and -cfg.PULLBACK_MAX_DEPTH <= r["dist_high"] < -cfg.NEAR_HIGH
            and abs(r["close"] - r["ema20"]) <= cfg.PULLBACK_EMA_ATR * r["atr"]):
        return "Pullback in Uptrend"
    return None


def plan(r, tag):
    """Entry zone, stop, target. Risk is measured from the TOP of the zone (worst fill)."""
    px, a = r["close"], r["atr"]
    if tag == "Breakout" and not r["new_high"]:            # still below resistance: wait for the break
        lo = to_tick(r["hi20"], "down") + tick(r["hi20"])
        hi, note = lo + 0.25 * a, "Buy only on a break above the 20-day high"
    elif tag == "Breakout":
        lo, hi, note = max(r["prior_high"], px - 0.5 * a), px + 0.25 * a, "Broke out; hold above the old high"
    elif tag == "Pullback in Uptrend":
        lo, hi, note = px - 0.5 * a, px + 0.1 * a, "Buy near the 20 EMA"
    else:
        lo, hi, note = px - 0.5 * a, px + 0.25 * a, "Avoid chasing above the zone"
    lo, hi = to_tick(lo, "nearest"), to_tick(hi, "up")
    atr_stop, swing = hi - cfg.STOP_ATR * a, r["swing_low"] - tick(r["swing_low"])
    use_swing = cfg.SWING_MIN_ATR * a <= hi - swing < cfg.STOP_ATR * a
    stop = to_tick(swing if use_swing else atr_stop, "down")
    target = to_tick(hi + cfg.TARGET_R * (hi - stop), "nearest")
    return dict(entry_lo=lo, entry_hi=hi, stop=stop, target=target, hold=cfg.HOLD_DAYS[tag], note=note,
                stop_basis="Swing low" if use_swing else f"{cfg.STOP_ATR:g} ATR",
                risk_pct=round((1 - stop / hi) * 100, 1))


def chips(r):
    out = []
    if r["new_high"]:
        out.append("New 20D high")
    elif r["dist_high"] >= -cfg.NEAR_HIGH:
        out.append(f"{abs(r['dist_high']) * 100:.1f}% off 20D high")
    if r["rvol"] >= cfg.VOL_SURGE:
        out.append(f"Vol {r['rvol']:.1f}x" + (" (down day)" if r["chg"] < 0 else ""))
    if r["trend_n"] == 3:
        out.append("EMA 10/20/50 aligned")
    if r["rs20"] >= 0.05:
        out.append(f"{r['rs20'] * 100:+.0f}% vs HSI 20D")
    if r["ret5"] >= 0.03:
        out.append(f"5D {r['ret5'] * 100:+.0f}%")
    if cfg.RSI_LOW <= r["rsi"] <= cfg.RSI_HIGH:
        out.append(f"RSI {r['rsi']:.0f}")
    if r["close_pos"] >= cfg.CLOSE_STRENGTH:
        out.append("Strong close")
    warn = []
    if r["rsi"] > cfg.RSI_PENALTY_FROM:
        warn.append(f"RSI {r['rsi']:.0f} overbought")
    if r["ext"] > cfg.OVEREXT_ATR:
        warn.append(f"{r['ext']:.1f} ATR above 20 EMA")
    return out, warn


# ------------------------------------------------------------------ regime
def regime(hsi, breadth):
    ma = hsi.tail(cfg.HSI_MA).mean()
    above = bool(hsi.iloc[-1] > ma)
    if above and breadth >= cfg.BREADTH_ON:
        label = "Risk-On"
    elif not above and breadth < cfg.BREADTH_OFF:
        label = "Risk-Off"
    else:
        label = "Neutral"
    return dict(label=label, hsi=round(float(hsi.iloc[-1]), 2), hsi_ma=round(float(ma), 2), above_ma=above,
                hsi_chg=float(hsi.iloc[-1] / hsi.iloc[-2] - 1), breadth=float(breadth))
