import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from scanner import config as cfg, engine as en, events, market_calendar as mc, prices, run, universe


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
    monkeypatch.setattr(run.mc, "closed_days", lambda w: set())
    (tmp_path / "latest.json").write_text('{"asof":"2026-11-20"}')
    monkeypatch.setattr(run.universe, "build", lambda w: (_ for _ in ()).throw(RuntimeError("Yahoo down")))
    with pytest.raises(SystemExit):
        run.main()
    assert json.loads((tmp_path / "latest.json").read_text())["asof"] == "2026-11-20"
    st = json.loads((tmp_path / "status.json").read_text())
    assert st["ok"] is False and "Yahoo down" in st["message"]


def test_missing_index_day_is_filled_but_never_overwritten():
    d = pd.to_datetime(["2026-11-20", "2026-11-23", "2026-11-25"])
    e = pd.Series([1.0, 99.0], index=pd.to_datetime(["2026-11-24", "2026-11-25"]))
    out = prices.with_missing(pd.Series([10.0, 11.0, 12.0], index=d), e)
    assert out.tolist() == [10.0, 11.0, 1.0, 12.0] and out.index.is_monotonic_increasing


HK = prices.HKT
XMAS = {"2026-12-25"}


@pytest.mark.parametrize("when,exp", [
    ((2026, 11, 27, 14, 22), date(2026, 11, 26)),   # Friday afternoon, still trading
    ((2026, 11, 27, 3, 10), date(2026, 11, 26)),    # a run ten hours late
    ((2026, 11, 27, 17, 47), date(2026, 11, 27)),
    ((2026, 11, 29, 12, 0), date(2026, 11, 27)),    # Sunday
    ((2026, 12, 24, 17, 0), date(2026, 12, 24)),    # half day is a session
    ((2026, 12, 25, 20, 0), date(2026, 12, 24)),    # holiday
])
def test_expected_session(when, exp):
    assert mc.expected_session(datetime(*when, tzinfo=HK), XMAS) == exp


def test_sessions_after_skips_weekends_and_holidays():
    assert mc.sessions_after(date(2026, 12, 24), date(2026, 12, 28), XMAS) == 1


def test_parse_holidays():
    ev = [{"dtstart": [f"202601{d:02d}", {}], "summary": "x"} for d in range(1, 15)]
    body = "\ufeff".encode() + json.dumps({"vcalendar": [{"vevent": ev}]}).encode()
    assert mc.parse_holidays(body)[0] == "2026-01-01"


def test_order_type_and_wide_stop():
    df = bars()
    r = en.raw(df, df["close"])
    r.update(new_high=False, hi20=r["close"] * 1.02, atr=r["close"] * 0.02)
    assert en.plan(r, "Breakout")["order"] == "above"
    assert en.plan(r, "Pullback in Uptrend")["order"] == "between"
    assert en.plan(r, "Breakout")["too_wide"] is False
    r.update(atr=r["close"] * 0.12, swing_low=r["close"] * 0.5)
    p = en.plan(r, "Breakout")
    assert p["risk_pct"] > cfg.MAX_RISK_PCT and p["too_wide"] is True


def test_results_flag_window_and_manual_file(tmp_path):
    asof = date(2026, 11, 26)
    assert events.upcoming([(date(2026, 11, 30), "Results")], asof, set())[0] == date(2026, 11, 30)
    assert events.upcoming([(date(2026, 12, 15), "Results"), (date(2026, 11, 25), "Results")], asof, set()) is None
    f = tmp_path / "events.csv"
    f.write_text("code,date,note\n1566,2026-11-30,Results\nbad,line,\n")
    out = {"asof": "2026-11-26", "stocks": [{"code": 1566, "setup": "Breakout", "warn": []},
                                            {"code": 5, "setup": None}]}
    w = []
    events.attach(out, set(), w, fetch=lambda codes, w: {}, path=f)
    assert out["stocks"][0]["results"] == "2026-11-30" and out["stocks"][0]["warn"] == ["Results due 30 Nov"]
    assert "results" not in out["stocks"][1] and len(w) == 1


def test_thinner_or_older_download_never_replaces():
    old = {"asof": "2026-11-26", "coverage": 0.96}
    run.check_replace(None, old)
    run.check_replace(old, {"asof": "2026-11-26", "coverage": 0.95})
    run.check_replace(old, {"asof": "2026-11-27", "coverage": 0.80})
    for bad in ({"asof": "2026-11-25", "coverage": 0.99}, {"asof": "2026-11-26", "coverage": 0.80}):
        with pytest.raises(RuntimeError):
            run.check_replace(old, bad)


def test_partial_market_cap_reply_is_rejected(tmp_path):
    full = {f"{i:04d}.HK": {"mcap": 5e9} for i in range(900)}
    prev = tmp_path / "caps.json"
    prev.write_text(json.dumps(full))
    universe.check_caps(full, prev)
    with pytest.raises(ValueError):
        universe.check_caps(dict(list(full.items())[:500]), prev)


def test_scan_needs_index_close_for_the_day():
    uni, b, hsi = world()
    with pytest.raises(RuntimeError, match="no index close"):
        run.scan(uni, 1, b, hsi.iloc[:-1], "HSI", [])


def _fake_main(tmp_path, monkeypatch, expected, argv=()):
    """Run main() on synthetic data ending 20 Nov, with the calendar saying `expected` has closed."""
    uni, b, hsi = world()
    monkeypatch.setattr(run, "DATA", tmp_path)
    monkeypatch.setattr(run.mc, "closed_days", lambda w: set())
    monkeypatch.setattr(run.mc, "expected_session", lambda now, c: expected)
    monkeypatch.setattr(run.universe, "build", lambda w: (uni, 2400))
    monkeypatch.setattr(run.prices, "download", lambda s: b)
    monkeypatch.setattr(run.prices, "drop_unfinished", lambda d: d)
    monkeypatch.setattr(run.prices, "index_close", lambda need: (hsi, "HSI"))
    monkeypatch.setattr(run.events, "attach", lambda *a, **k: None)
    code = 0
    try:
        run.main(argv)
    except SystemExit as e:
        code = e.code
    return code, json.loads((tmp_path / "status.json").read_text()) if (tmp_path / "status.json").exists() else None


def test_late_data_is_published_but_reported_then_left_alone(tmp_path, monkeypatch):
    code, status = _fake_main(tmp_path, monkeypatch, date(2026, 11, 23))
    first = (tmp_path / "latest.json").read_text()
    assert code == 1 and status["ok"] is False and "only reach 2026-11-20" in status["message"]
    assert json.loads(first)["asof"] == "2026-11-20"
    code, _ = _fake_main(tmp_path, monkeypatch, date(2026, 11, 23))
    assert code == 1 and (tmp_path / "latest.json").read_text() == first    # timestamp not refreshed


def test_current_data_succeeds_and_scheduled_rerun_is_skipped(tmp_path, monkeypatch):
    code, status = _fake_main(tmp_path, monkeypatch, date(2026, 11, 20))
    assert code == 0 and status["ok"] is True
    monkeypatch.setattr(run.universe, "build", lambda w: pytest.fail("should have skipped"))
    run.main(["--if-stale"])
