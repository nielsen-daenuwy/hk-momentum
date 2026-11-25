import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from scanner import config as cfg, engine as en, prices, run


def bars(n=120, start=10.0, drift=0.003, vol=5e6, seed=0, end="2026-11-20"):
    rng = np.random.default_rng(seed)
    c = start * np.cumprod(1 + drift + rng.normal(0, 0.012, n))
    idx = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame({"open": c * 0.998, "high": c * 1.01, "low": c * 0.985, "close": c,
                         "volume": vol * rng.uniform(0.8, 1.2, n)}, index=idx)


def world(k=40):
    b = {f"{i:04d}.HK": bars(seed=i, drift=0.001 * (i % 5 - 1)) for i in range(1, k + 1)}
    uni = pd.DataFrame([dict(symbol=s, code=int(s[:4]), name=f"N{s[:4]}", long="", sector="Other", mcap=5e9)
                        for s in b]).set_index("symbol")
    return uni, b, bars(start=20000, drift=0, seed=99)["close"]


def test_percentile_0_to_100_and_ties():
    p = en.percentile(pd.Series([1, 2, 2, 3]))
    assert p.iloc[0] == 0 and p.iloc[3] == 100 and p.iloc[1] == p.iloc[2] == 50


@pytest.mark.parametrize("r,exp", [(55, 100), (65, 100), (75, 100), (45, 50), (30, 0), (90, 0)])
def test_rsi_fit(r, exp):
    assert en.rsi_fit(r) == pytest.approx(exp)


def test_penalties():
    assert en.penalties(dict(rsi=80, ext=2.0)) == (0, 0)
    a, b = en.penalties(dict(rsi=85, ext=3.0))
    assert a == 10 and b == 8
    assert en.penalties(dict(rsi=100, ext=50)) == (cfg.RSI_PENALTY_MAX, cfg.OVEREXT_PENALTY_MAX)


def test_heavy_volume_on_a_down_day_is_not_rewarded():
    assert en.volume_value(3, 0.02) > en.volume_value(1, 0.02) > en.volume_value(3, -0.02)


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 50.0))
    assert en.rsi(up) == 100 and en.rsi(up[::-1]) == pytest.approx(0)
    assert en.rsi(pd.Series([5.0] * 40)) == 50


def test_ticks():
    assert en.to_tick(398.87) == 398.8 and en.to_tick(5.0762, "up") == 5.08 and en.to_tick(29.35, "down") == 29.34


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("tag", list(cfg.HOLD_DAYS))
def test_plan_is_always_ordered_and_2r(seed, tag):
    df = bars(seed=seed)
    r = en.raw(df, df["close"])
    if tag == "Pullback in Uptrend":
        r["new_high"] = False
    p = en.plan(r, tag)
    assert p["stop"] < p["entry_lo"] <= p["entry_hi"] < p["target"]
    risk = p["entry_hi"] - p["stop"]
    assert (p["target"] - p["entry_hi"]) / risk == pytest.approx(2, abs=0.1)
    assert risk <= cfg.STOP_ATR * r["atr"] + en.tick(p["stop"]) * 2


def test_liquidity_gates():
    df = bars()
    d = df.index
    assert en.liquidity(df, d) is None
    assert en.liquidity(df.assign(volume=1000), d) == "turnover"
    assert en.liquidity(df.assign(close=df["close"] / 100), d) == "price"
    assert en.liquidity(df.drop(d[-5]), d) == "traded"
    assert en.liquidity(df.tail(40), d) == "history"
    split = df.copy(); split.iloc[-5:, :4] *= 3
    assert en.liquidity(split, d) == "bad data"


def test_regime():
    up, down = pd.Series(np.arange(100.0, 200)), pd.Series(np.arange(200.0, 100, -1))
    assert en.regime(up, 0.6)["label"] == "Risk-On"
    assert en.regime(down, 0.3)["label"] == "Risk-Off"
    assert en.regime(up, 0.3)["label"] == en.regime(down, 0.6)["label"] == "Neutral"


def test_unfinished_bar_is_dropped():
    df = bars(end="2026-11-24")
    noon = datetime(2026, 11, 24, 12, 0, tzinfo=prices.HKT)
    eve = datetime(2026, 11, 24, 17, 30, tzinfo=prices.HKT)
    assert prices.drop_unfinished(df, noon).index[-1].day == 23
    assert prices.drop_unfinished(df, eve).index[-1].day == 24


def test_holiday_is_not_a_session_and_partial_day_aborts():
    v = pd.DataFrame({f"s{i}": bars()["volume"] for i in range(20)})
    hol = v.copy(); hol.iloc[-3] = np.nan
    assert v.index[-3] not in prices.sessions(hol)
    part = v.copy(); part.iloc[-1, :6] = np.nan
    with pytest.raises(RuntimeError, match="incomplete"):
        prices.sessions(part)


def test_scan_payload():
    uni, b, hsi = world()
    out = run.clean(run.scan(uni, 2400, b, hsi, "HSI", []))
    json.dumps(out, allow_nan=False)
    assert [s["score"] for s in out["stocks"]] == sorted((s["score"] for s in out["stocks"]), reverse=True)
    assert all(0 <= s["score"] <= 100 for s in out["stocks"])
    assert all(("plan" in s) == bool(s["setup"]) for s in out["stocks"])


def test_too_many_missing_downloads_aborts():
    uni, b, hsi = world()
    with pytest.raises(RuntimeError, match="only"):
        run.scan(uni, 1, dict(list(b.items())[:20]), hsi, "HSI", [])


def test_failure_keeps_old_results(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "DATA", tmp_path)
    (tmp_path / "latest.json").write_text('{"asof":"2026-11-20"}')
    monkeypatch.setattr(run.universe, "build", lambda w: (_ for _ in ()).throw(RuntimeError("Yahoo down")))
    with pytest.raises(SystemExit):
        run.main()
    assert json.loads((tmp_path / "latest.json").read_text())["asof"] == "2026-11-20"
    st = json.loads((tmp_path / "status.json").read_text())
    assert st["ok"] is False and "Yahoo down" in st["message"]
