# main.py
import ccxt
import pandas as pd
import ta
from datetime import datetime, timedelta, timezone
import json
import os
import requests

# --- Telegram Bot Setup ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"⚠️ Failed to send Telegram message: {e}")

# --- 1. Setup exchange (via CCXT) ---
exchange = ccxt.kucoin()

# --- 2. Function to fetch OHLCV ---
def get_ohlcv(symbol="BTC/USDT", timeframe="15m", limit=500):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
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

        if high == max(df["high"].iloc[i-lookback:i+lookback+1]):
            zones.append({"type": "supply", "level": high, "volume": vol})

        if low == min(df["low"].iloc[i-lookback:i+lookback+1]):
            zones.append({"type": "demand", "level": low, "volume": vol})
    return zones

# --- 6. Trade setup detection ---
def detect_setups(df, trend, zones, tf):
    last = df.iloc[-1]
    close = last["close"]
    ema20 = last["EMA20"]
    ema50 = last["EMA50"]

    setups = []

    if trend == "Neutral trend":
        print(f"🔍 No signal: Trend is neutral on {tf} timeframe.")
        return setups

    entry_price = ema20 + 0.8 * (ema50 - ema20)

    if trend == "Bearish trend":
        valid_zones = [z for z in zones if z["type"] == "demand" and z["level"] < close]
        if close < ema20 and valid_zones:
            valid_zones.sort(key=lambda z: abs(z["level"] - close))
            nearest_zone = valid_zones[0]
            setups.append({
                "symbol": "BTC/USDT",
                "timeframe": tf,
                "type": "Short",
                "entry": float(entry_price),
                "sl": float(ema50 * 1.003),
                "tp1": float(close - (ema50 - ema20) * 2),
                "tp2": float(nearest_zone["level"]),
                "signal_time": last["timestamp"].isoformat(),
                "status": "pending",
                "entry_time": None,
                "exit_time": None,
                "exit_reason": None,
                "refinements": 1
            })

    elif trend == "Bullish trend":
        valid_zones = [z for z in zones if z["type"] == "supply" and z["level"] > close]
        if close > ema20 and valid_zones:
            valid_zones.sort(key=lambda z: abs(z["level"] - close))
            nearest_zone = valid_zones[0]
            setups.append({
                "symbol": "BTC/USDT",
                "timeframe": tf,
                "type": "Long",
                "entry": float(entry_price),
                "sl": float(ema50 * 0.997),
                "tp1": float(close + (ema20 - ema50) * 2),
                "tp2": float(nearest_zone["level"]),
                "signal_time": last["timestamp"].isoformat(),
                "status": "pending",
                "entry_time": None,
                "exit_time": None,
                "exit_reason": None,
                "refinements": 1
            })

    return setups

# --- 7. Safe JSON Loader ---
def load_trades(filename="trades.json"):
    if not os.path.exists(filename):
        return {}
    try:
        with open(filename, "r") as f:
            data = f.read().strip()
            if not data:
                return {}
            return json.loads(data)
    except Exception:
        return {}

# --- 8. Save trades to JSON (with refinements logic) ---
def save_trade(trade_id, trade_data, tf):
    filename = "trades.json"
    trades = load_trades(filename)

    # Refinement logic only for 15m
    if tf == "15m":
        for t_id, t in list(trades.items()):
            if t["timeframe"] == tf and t["type"] == trade_data["type"] and t["status"] == "pending":
                if t.get("refinements", 1) < 3:
                    trade_data["refinements"] = t.get("refinements", 1) + 1
                    print(f"🔄 Refinement {trade_data['refinements']} replacing {t_id}")
                    del trades[t_id]
                else:
                    print(f"🚫 Max refinements reached for {tf} {trade_data['type']} - keeping last signal.")
                    return
    else:
        # For 1h and 4h: only allow one pending trade per direction
        for t_id, t in list(trades.items()):
            if t["timeframe"] == tf and t["type"] == trade_data["type"] and t["status"] == "pending":
                print(f"🚫 Pending trade already exists for {tf} {trade_data['type']}. Skipping new one.")
                return

    trades[trade_id] = trade_data
    with open(filename, "w") as f:
        json.dump(trades, f, indent=4)

    print(f"💾 Saved trade {trade_id}")

    # Convert UTC to Colombia time (UTC-5)
    try:
        utc_time = datetime.fromisoformat(trade_data['signal_time'].replace("Z", "+00:00"))
        col_time = utc_time.astimezone(timezone(timedelta(hours=-5)))
        readable_time = col_time.strftime("%a, %b %d %Y - %H:%M (COL)")
    except Exception:
        readable_time = trade_data['signal_time']  # fallback

    # Send Telegram alert
    alert_msg = (
        f"📢 New Trade Alert!\n"
        f"Pair: {trade_data['symbol']}\n"
        f"Timeframe: {tf}\n"
        f"Type: {trade_data['type']}\n"
        f"Entry: {trade_data['entry']:.2f}\n"
        f"SL: {trade_data['sl']:.2f}\n"
        f"TP1: {trade_data['tp1']:.2f}\n"
        f"TP2: {trade_data['tp2']:.2f}\n"
        f"Status: {trade_data['status']}\n"
        f"Refinements: {trade_data.get('refinements', 1)}\n"
        f"Signal Time: {readable_time}"
    )
    send_telegram_message(alert_msg)

# --- 9. Update trade status (with expiry) ---
def update_trades_status(symbol, df, filename="trades.json"):
    trades = load_trades(filename)
    updated = False

    latest_high = df["high"].iloc[-1]
    latest_low = df["low"].iloc[-1]
    latest_time = df["timestamp"].iloc[-1]

    expiry_time = {
        "15m": timedelta(hours=2),
        "1h": timedelta(hours=12),
        "4h": timedelta(days=3)
    }

    now = datetime.utcnow().replace(tzinfo=timezone.utc)

    for trade_id, trade in trades.items():
        status = trade.get("status", "pending")

        try:
            signal_time = datetime.fromisoformat(trade["signal_time"].replace("Z", "+00:00"))
        except Exception:
            signal_time = None

        if status == "pending":
            # Expiry check
            if signal_time and now - signal_time > expiry_time[trade["timeframe"]]:
                trade["status"] = "expired"
                trade["exit_reason"] = "Signal expired"
                trade["exit_time"] = now.isoformat()
                updated = True
                send_telegram_message(f"⌛ Trade expired: {trade['symbol']} {trade['timeframe']} {trade['type']}")

            # Entry check
            elif trade["type"] == "Long" and latest_low <= trade["entry"]:
                trade["status"] = "open"
                trade["entry_time"] = now.isoformat()
                updated = True
                send_telegram_message(f"✅ Trade OPENED (Long): {trade['symbol']} @ {trade['entry']:.2f}")
            elif trade["type"] == "Short" and latest_high >= trade["entry"]:
                trade["status"] = "open"
                trade["entry_time"] = now.isoformat()
                updated = True
                send_telegram_message(f"✅ Trade OPENED (Short): {trade['symbol']} @ {trade['entry']:.2f}")

        elif status == "open":
            latest_close = df["close"].iloc[-1]
            if (trade["type"] == "Long" and latest_close <= trade["sl"]) or \
               (trade["type"] == "Short" and latest_close >= trade["sl"]):
                trade["status"] = "closed"
                trade["exit_reason"] = "Stop Loss hit"
                trade["exit_time"] = now.isoformat()
                updated = True
                send_telegram_message(f"❌ Trade CLOSED (SL): {trade['symbol']}")
            elif (trade["type"] == "Long" and latest_close >= trade["tp2"]) or \
                 (trade["type"] == "Short" and latest_close <= trade["tp2"]):
                trade["status"] = "closed"
                trade["exit_reason"] = "Take Profit hit"
                trade["exit_time"] = now.isoformat()
                updated = True
                send_telegram_message(f"🎯 Trade CLOSED (TP): {trade['symbol']}")

    if updated:
        with open(filename, "w") as f:
            json.dump(trades, f, indent=4)

# --- Main Run Loop ---
timeframes = {
    "15m": 778,
    "1h": 490,
    "4h": 188
}

for tf, limit in timeframes.items():
    print(f"\n=== {tf} timeframe ===")
    df = get_ohlcv("BTC/USDT", timeframe=tf, limit=limit)
    df = add_ema(df)
    trend = analyze_trend(df)
    zones = detect_liquidity_zones(df)
    setups = detect_setups(df, trend, zones, tf)

    latest_close = df['close'].iloc[-1]

    print(f"Latest Close: {latest_close:,.2f}")
    print(f"EMA20: {df['EMA20'].iloc[-1]:,.2f}")
    print(f"EMA50: {df['EMA50'].iloc[-1]:,.2f}")
    print(f"Trend: {trend}")

    if setups:
        print("📊 Current Setup(s):")
        for setup in setups:
            print(
                f"- {setup['type']} | Entry: {setup['entry']:.2f}, "
                f"SL: {setup['sl']:.2f}, TP1: {setup['tp1']:.2f}, TP2: {setup['tp2']:.2f}, "
                f"Refinements: {setup.get('refinements', 1)}"
            )
            trade_id = f"BTCUSDT_{tf}_{df['timestamp'].iloc[-1].strftime('%Y%m%d_%H%M%S')}_{setup['type'][0]}"
            save_trade(trade_id, setup, tf)
    else:
        print(f"📊 No immediate setups detected for {tf} timeframe.")

    update_trades_status("BTC/USDT", df)
