"""All settings live in this one file. Change a number, commit, and the next scan uses it."""

# ---------------------------------------------------------------- 1. LIQUIDITY FILTER
MIN_AVG_TURNOVER = 20_000_000     # HK$, average daily turnover over the window below
MIN_PRICE = 1.00                  # HK$
MIN_MARKET_CAP = 2_000_000_000    # HK$
TRADED_SESSIONS = 20              # must have traded on every one of the last N sessions
MIN_HISTORY = 60                  # bars needed so the 50 EMA means something
MAX_ONE_DAY_MOVE = 0.60           # bigger 1-day moves in the window are treated as bad data

# ---------------------------------------------------------------- 2. FACTORS
VOL_SURGE = 1.5                   # x 20-day average volume
NEAR_HIGH = 0.03                  # "close to the 20-day high" means within 3%
RSI_LOW, RSI_HIGH = 55, 75        # ideal RSI(14) band
RSI_PENALTY_FROM = 80
CLOSE_STRENGTH = 0.70             # close in the top 30% of the day's range
OVEREXT_ATR = 2.0                 # ATRs above the 20 EMA before the penalty starts

# Default weights. They do not need to add up to 100 - the score is a weighted average.
WEIGHTS = {
    "ret5": 15, "ret10": 15, "rs20": 20, "trend": 15,
    "breakout": 15, "volume": 10, "rsi": 5, "close": 5,
}
LABELS = {
    "ret5": "5-day return", "ret10": "10-day return", "rs20": "20-day vs HSI",
    "trend": "Trend (EMAs)", "breakout": "Breakout", "volume": "Volume surge",
    "rsi": "RSI fit", "close": "Close strength",
}
# Points deducted from the 0-100 score
RSI_PENALTY_BASE, RSI_PENALTY_PER_POINT, RSI_PENALTY_MAX = 5, 1.0, 20
OVEREXT_PENALTY_PER_ATR, OVEREXT_PENALTY_MAX = 8, 20

# ---------------------------------------------------------------- 3. SETUPS
IGNITION_MIN_GAIN = 0.02          # Volume Ignition needs a day up at least this much
PULLBACK_MAX_DEPTH = 0.12         # Pullback: 3%..12% below the 20-day high ...
PULLBACK_EMA_ATR = 1.0            # ... and within this many ATRs of the 20 EMA

# ---------------------------------------------------------------- 4. TRADE PLAN
STOP_ATR = 1.5
SWING_LOW_SESSIONS = 10
SWING_MIN_ATR = 1.0               # ignore a swing low closer than this (noise would hit it)
TARGET_R = 2.0
HOLD_DAYS = {"Breakout": "3-7 days", "Pullback in Uptrend": "3-5 days", "Volume Ignition": "2-4 days"}

# ---------------------------------------------------------------- 5. MARKET REGIME
HSI_MA = 50
BREADTH_MA = 20
BREADTH_ON = 0.50                 # Risk-On: HSI above its MA and breadth at least this
BREADTH_OFF = 0.40                # Risk-Off: HSI below its MA and breadth under this
PICKS = {"Risk-On": 20, "Neutral": 15, "Risk-Off": 8}

# ---------------------------------------------------------------- 6. DATA
HISTORY_PERIOD = "9mo"
BATCH_SIZE = 80
DOWNLOAD_ROUNDS = 3               # retry rounds for tickers that came back empty
MIN_COVERAGE = 0.85               # abort (keep the old results) if fewer names download
EOD_READY = (16, 30)              # HKT; before this, today's unfinished bar is ignored
SPARK_POINTS = 30
HKEX_LIST_URL = ("https://www.hkex.com.hk/eng/services/trading/securities/"
                 "securitieslists/ListOfSecurities.xlsx")
