# main.py
import ccxt
import pandas as pd
import ta
from datetime import datetime, timezone
import json
import os

# =========================
# 0) Config
# =========================
SYMBOL = "BTC/USDT"
TRADE_LOG_PATH = "trades.json"
# If a setup is not touched within N candles, mark as expired (None = disabled)
EXPIRY_CANDLES = None  # set to e.g. 5 later if you want the "timer" behavior
# When entry & TP/SL occur in the same candle, which fills first? ("SL-first" or "TP-first")
INTRABAR_FILL_PRIORITY = "SL-first"  # conservative default

# --- 1. Setup exchange (Binance via CCXT) ---
exchange = ccxt.kucoin()

# --- 2. Function to fetch OHLCV ---
def get_ohlcv(symbol=SYMBOL, timeframe="15m", limit=500):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    # Keep everything in UTC for consistency
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df

# --- 3. Function to add EMAs ---
def add_ema(df, ema_periods=[20, 50]):
    for period in ema_periods:
        df[f"EMA{period}"] = ta.trend.ema_indicator(df["close"], window=period)
    return df

# --- 4. Trend Analysis ---
def analyze_trend(df):
    last = df.iloc[-1]
    if last["EMA20"] > last["EMA50"]:
        return "Bullish trend"
    elif last["EMA20"] < last["EMA50"]:
        return "Bearish trend"
    else:
        return "Neutral trend"

# --- 5. Detect Liquidity Zones ---
def detect_liquidity_zones(df, lookback=50):
    zones = []
    for i in range(lookback, len(df) - lookback):
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]
        vol = df["volume"].iloc[i]

        if high == max(df["high"].iloc[i - lookback : i + lookback + 1]):
            zones.append({"type": "supply", "level": float(high), "volume": float(vol)})

        if low == min(df["low"].iloc[i - lookback : i + lookback + 1]):
            zones.append({"type": "demand", "level": float(low), "volume": float(vol)})
    return zones

# --- 6. Trade setup detection (UNCHANGED) ---
def detect_setups(df, trend, zones):
    last = df.iloc[-1]
    close = last["close"]
    ema20 = last["EMA20"]
    ema50 = last["EMA50"]

    setups = []
    if trend == "Neutral trend":
        return setups

    # Entry anchored near EMA50 (your original formula)
    entry_price = ema20 + 0.8 * (ema50 - ema20)

    if trend == "Bearish trend":
        valid_zones = [z for z in zones if z["type"] == "demand" and z["level"] < close]
        if close < ema20 and valid_zones:
            valid_zones.sort(key=lambda z: abs(z["level"] - close))
            nearest_zone = valid_zones[0]
            setups.append({
                "type": "Short",
                "entry": float(entry_price),
                "sl": float(ema50 * 1.003),
                "tp1": float(close - (ema50 - ema20) * 2),
                "tp2": float(nearest_zone["level"]),
            })

    elif trend == "Bullish trend":
        valid_zones = [z for z in zones if z["type"] == "supply" and z["level"] > close]
        if close > ema20 and valid_zones:
            valid_zones.sort(key=lambda z: abs(z["level"] - close))
            nearest_zone = valid_zones[0]
            setups.append({
                "type": "Long",
                "entry": float(entry_price),
                "sl": float(ema50 * 0.997),
                "tp1": float(close + (ema20 - ema50) * 2),
                "tp2": float(nearest_zone["level"]),
            })
    return setups

# =========================
# 7) Trade persistence & lifecycle
# =========================
def load_trades():
    if os.path.exists(TRADE_LOG_PATH):
        with open(TRADE_LOG_PATH, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_trades(trades):
    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(trades, f, indent=2)

def _iso_utc(ts: pd.Timestamp) -> str:
    # Ensure ISO with timezone
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.isoformat()

def trade_already_logged(trades, tf, signal_time_iso, trade_type):
    # Avoid duplicates on the same bar/timeframe/type
    for tid, t in trades.items():
        if t.get("timeframe") == tf and t.get("signal_time") == signal_time_iso and t.get("type") == trade_type and t.get("symbol") == SYMBOL:
            return True
    return False

def record_new_setups(trades, tf, setups, signal_ts_utc):
    created_ids = []
    st_iso = _iso_utc(signal_ts_utc)
    for setup in setups:
        if trade_already_logged(trades, tf, st_iso, setup["type"]):
            continue
        trade_id = f"{SYMBOL.replace('/','')}_{tf}_{signal_ts_utc.strftime('%Y%m%d_%H%M%S')}_{setup['type'][0]}"
        trades[trade_id] = {
            "symbol": SYMBOL,
            "timeframe": tf,
            "type": setup["type"],     # "Long" / "Short"
            "entry": float(setup["entry"]),
            "sl": float(setup["sl"]),
            "tp1": float(setup["tp1"]),
            "tp2": float(setup["tp2"]),
            "signal_time": st_iso,     # when setup was created
            "status": "pending",       # pending -> active -> won_tp1/lost_sl/expired
            "entry_time": None,
            "exit_time": None,
            "exit_reason": None
        }
        created_ids.append(trade_id)
    return created_ids

def _hit_same_candle(long_or_short, row_high, row_low, entry, tp, sl):
    """Return outcome if TP/SL touched in same candle as (or after) entry.
       Uses INTRABAR_FILL_PRIORITY to resolve both-hit cases.
       Returns 'tp', 'sl', or None."""
    tp_hit = row_high >= tp if long_or_short == "Long" else row_low <= tp
    sl_hit = row_low <= sl if long_or_short == "Long" else row_high >= sl
    if tp_hit and sl_hit:
        return "sl" if INTRABAR_FILL_PRIORITY.lower().startswith("sl") else "tp"
    if tp_hit:
        return "tp"
    if sl_hit:
        return "sl"
    return None

def update_trades_for_timeframe(df, tf, trades):
    """Update trades (for this timeframe) from the bar AFTER signal_time forward."""
    updates = []
    # Create index by timestamp for quick lookup
    df = df.reset_index(drop=True)
    ts_series = df["timestamp"]

    for tid, t in trades.items():
        if t.get("symbol") != SYMBOL or t.get("timeframe") != tf:
            continue
        status = t.get("status")
        if status in ("won_tp1", "lost_sl", "expired"):
            continue  # already closed

        # Parse times
        sig_ts = pd.to_datetime(t["signal_time"], utc=True)
        # Find first index >= signal bar
        mask = ts_series >= sig_ts
        if not mask.any():
            continue  # our data window doesn't include this yet

        sig_idx = mask.idxmax()
        # Start checking from the NEXT candle to avoid look-ahead bias
        start_i = sig_idx + 1
        if start_i >= len(df):
            continue

        entry = float(t["entry"])
        sl = float(t["sl"])
        tp1 = float(t["tp1"])
        side = t["type"]  # "Long" or "Short"

        # Compute expiry window if enabled
        expire_after = EXPIRY_CANDLES if isinstance(EXPIRY_CANDLES, int) and EXPIRY_CANDLES > 0 else None
        bars_checked = 0

        entered = (status == "active")
        entry_i = None

        for i in range(start_i, len(df)):
            row = df.iloc[i]
            high = float(row["high"])
            low = float(row["low"])
            row_ts = row["timestamp"]

            if not entered:
                # Check entry touch (retrace to entry level)
                touched = (low <= entry <= high)
                if touched:
                    # Enter at entry price; mark active
                    t["status"] = "active"
                    t["entry_time"] = _iso_utc(row_ts)
                    entered = True
                    entry_i = i
                    # On the SAME candle, also check if TP/SL hit after entry (ambiguous -> use priority)
                    outcome = _hit_same_candle(side, high, low, entry, tp1, sl)
                    if outcome == "tp":
                        t["status"] = "won_tp1"
                        t["exit_time"] = _iso_utc(row_ts)
                        t["exit_reason"] = "tp1"
                        updates.append((tid, "entered+won_tp1"))
                        break
                    elif outcome == "sl":
                        t["status"] = "lost_sl"
                        t["exit_time"] = _iso_utc(row_ts)
                        t["exit_reason"] = "sl"
                        updates.append((tid, "entered+lost_sl"))
                        break
                    # else continue to future candles for exit
                else:
                    bars_checked += 1
                    if expire_after is not None and bars_checked >= expire_after:
                        t["status"] = "expired"
                        t["exit_time"] = _iso_utc(row_ts)
                        t["exit_reason"] = "not_hit"
                        updates.append((tid, "expired"))
                        break
            else:
                # Already active: look for TP1 or SL
                if side == "Long":
                    # If both touched in same candle, apply priority
                    outcome = _hit_same_candle(side, high, low, entry, tp1, sl)
                    if outcome == "tp":
                        t["status"] = "won_tp1"
                        t["exit_time"] = _iso_utc(row_ts)
                        t["exit_reason"] = "tp1"
                        updates.append((tid, "won_tp1"))
                        break
                    elif outcome == "sl":
                        t["status"] = "lost_sl"
                        t["exit_time"] = _iso_utc(row_ts)
                        t["exit_reason"] = "sl"
                        updates.append((tid, "lost_sl"))
                        break
                else:  # Short
                    outcome = _hit_same_candle(side, high, low, entry, tp1, sl)
                    if outcome == "tp":
                        t["status"] = "won_tp1"
                        t["exit_time"] = _iso_utc(row_ts)
                        t["exit_reason"] = "tp1"
                        updates.append((tid, "won_tp1"))
                        break
                    elif outcome == "sl":
                        t["status"] = "lost_sl"
                        t["exit_time"] = _iso_utc(row_ts)
                        t["exit_reason"] = "sl"
                        updates.append((tid, "lost_sl"))
                        break

    return updates

# =========================
# 8) Main Run Loop
# =========================
timeframes = {
    "15m": 778,
    "1h": 490,
    "4h": 188
}

for tf, limit in timeframes.items():
    print(f"\n=== {tf} timeframe ===")
    df = get_ohlcv(SYMBOL, timeframe=tf, limit=limit)
    df = add_ema(df)
    trend = analyze_trend(df)
    zones = detect_liquidity_zones(df)
    setups = detect_setups(df, trend, zones)

    print(f"Latest Close: {df['close'].iloc[-1]:,.2f}")
    print(f"EMA20: {df['EMA20'].iloc[-1]:,.2f}")
    print(f"EMA50: {df['EMA50'].iloc[-1]:,.2f}")
    print(f"Trend: {trend}")

    if setups:
        print("📊 Current Setup(s):")
        for setup in setups:
            print(f"- {setup['type']} | Entry: {setup['entry']:.2f}, SL: {setup['sl']:.2f}, TP1: {setup['tp1']:.2f}, TP2: {setup['tp2']:.2f}")
    else:
        print("📊 No immediate setups detected")

    # --- NEW: persist setups & update lifecycle
    trades = load_trades()

    # Freeze new setups from this bar (no duplicates for same tf/bar/type)
    new_ids = record_new_setups(trades, tf, setups, df["timestamp"].iloc[-1])
    for tid in new_ids:
        print(f"💾 Saved trade {tid}")

    # Update existing trades for this timeframe using the latest data
    updates = update_trades_for_timeframe(df, tf, trades)
    if updates:
        for tid, what in updates:
            print(f"✅ Updated {tid}: {what}")

    save_trades(trades)
