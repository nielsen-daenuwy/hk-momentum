# HK Momentum Scanner

A free public page that ranks Hong Kong Main Board stocks for long-only swing trades held 2 to 7 days, using end-of-day data only.

GitHub Actions runs the Python scan every weekday at 17:30 HKT and writes `site/data/latest.json`. The page in `site/` is plain
HTML, CSS and JavaScript on GitHub Pages. The SCAN button loads that file. It does not fetch live prices.

To put it online, follow [DEPLOY.md](DEPLOY.md).

**Not investment advice. This model has not been backtested.** An earlier backtest of a related 10-day Hong Kong momentum model
(`hkswing`, a separate project) found no edge after costs, so treat the picks as a list to research.

## Change the settings

Everything is in [`scanner/config.py`](scanner/config.py). Edit it on GitHub (pencil icon), commit, and the site rescans and
republishes by itself.

| I want to | Change |
|---|---|
| Require more liquidity | `MIN_AVG_TURNOVER`, `MIN_PRICE`, `MIN_MARKET_CAP`, `TRADED_SESSIONS` |
| Change the default factor weights | `WEIGHTS` |
| Change the RSI band or penalties | `RSI_LOW`, `RSI_HIGH`, `RSI_PENALTY_*`, `OVEREXT_*` |
| Change stops and targets | `STOP_ATR`, `SWING_LOW_SESSIONS`, `TARGET_R` |
| Show more or fewer picks | `PICKS` |
| Change the regime rules | `HSI_MA`, `BREADTH_ON`, `BREADTH_OFF` |

## Liquidity filter

Main Board ordinary shares with an HKD counter, from HKEX's List of Securities. A stock must have average turnover of at least
HK$20m over 20 sessions, a price of at least HK$1, market cap of at least HK$2bn, and a trade on each of the last 20 sessions.
Two extra checks protect the numbers: at least 60 bars of history, and no one-day move above 60% in the last 20 sessions (usually
an unadjusted split).

## Factors

Each factor is ranked 0 to 100 against every other liquid stock. The score is the weighted average, minus penalties.

| Factor | Default weight | What is ranked |
|---|---|---|
| 5-day return | 15 | Close vs 5 sessions ago |
| 10-day return | 15 | Close vs 10 sessions ago |
| 20-day vs HSI | 20 | 20-day return minus the Hang Seng's |
| Trend | 15 | How many hold: close > 10 EMA, close > 20 EMA, 20 EMA > 50 EMA |
| Breakout | 15 | Close relative to the previous 20-day high |
| Volume surge | 10 | Volume vs its 20-day average, counted against the stock on a down day |
| RSI fit | 5 | Full marks for RSI(14) of 55 to 75, fading outside it |
| Close strength | 5 | Where the close sits in the day's range |

Penalties: RSI above 80 costs 5 points plus 1 per RSI point (maximum 20). Each ATR beyond 2 ATR above the 20 EMA costs 8 points
(maximum 20).

Subtracting the same index return from every stock does not change their order, so "20-day vs HSI" ranks the same as a plain
20-day return. The index comparison is still useful on the reason chip.

## Setups

Only stocks with a setup appear as picks. The first match wins.

| Setup | Rule | Suggested hold |
|---|---|---|
| Breakout (new high) | Close above the previous 20-day high, at least 2 of 3 trend checks | 3-7 days |
| Volume Ignition | Volume 1.5x or more, up 2% or more, close in the top 30% of the range and above the 20 EMA | 2-4 days |
| Breakout (near high) | Within 3% of the 20-day high, all 3 trend checks. Entry sits above the high | 3-7 days |
| Pullback in Uptrend | 20 EMA above 50 EMA, 3% to 12% below the 20-day high, within 1 ATR of the 20 EMA | 3-5 days |

**Stop:** the 10-day swing low when it is 1 to 1.5 ATR below the entry, otherwise 1.5 ATR. **Target:** 2R. Risk is measured from the
top of the entry zone, so a worse fill than that breaks the 2R. Prices are rounded to HKEX tick sizes.

## Market regime

- **Risk-On** (20 picks): HSI above its 50-day average and at least 50% of liquid stocks above their 20-day average
- **Risk-Off** (8 picks and a warning): HSI below its 50-day average and fewer than 40% above
- **Neutral** (15 picks): anything else

## When something goes wrong

| Problem | What happens |
|---|---|
| Holiday or typhoon | No new session is found, so the last trading day stays up with its date |
| Some downloads fail | Retried 3 times. Under 85% coverage the scan stops and the old results stay |
| HKEX list or market caps unavailable | The saved copy in `cache/` is used and the page says so |
| The whole scan fails | Tried 3 times, 5 minutes apart. The page keeps the last good scan and shows a notice |
| The page cannot load the data | A message and a working SCAN button |

## Known limits

- Yahoo is an unofficial source. It sometimes misses a day for a stock, mostly recent listings, and the 20-session rule then
  leaves that stock out.
- Market cap is Yahoo's whole-company figure, so for H shares it usually includes the A shares.
- Prices are adjusted for splits but not dividends, the same as a default chart. A large ex-dividend day looks like a fall.
- GitHub can start scheduled jobs late, sometimes by more than 30 minutes, and occasionally skips one.

## Run it on your computer

```bash
python3.12 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python -m scanner.run
```

```bash
.venv/bin/python -m http.server 8791 --directory site
```

Then open http://localhost:8791. Run the tests with `.venv/bin/python -m pytest`.

## Files

```
.github/workflows/scan.yml   nightly scan and publish
scanner/config.py            every setting
scanner/universe.py          HKEX list, market cap, sector
scanner/prices.py            Yahoo downloads, trading calendar
scanner/engine.py            indicators, factors, setups, trade plans, regime
scanner/run.py               puts it together, writes the JSON
site/                        the web page
site/data/latest.json        last good scan
site/data/status.json        result of the last attempt
cache/                       fallback copies of the stock list
tests/                       automated checks, run before every scan
```
