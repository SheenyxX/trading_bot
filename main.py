# main.py
import ccxt
import pandas as pd
import ta
from datetime import datetime, timedelta, timezone
import json
import os
import requests
import uuid

# --- Telegram Bot Setup (from environment variables) ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def send_telegram_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ Telegram credentials not set, skipping alert.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"⚠️ Failed to send Telegram message: {e}")


# --- 1. Setup exchange (KuCoin via CCXT) ---
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
def analyze_trend(df, lookback=3):
    """Check EMA alignment with short smoothing to reduce flip-flops"""
    if df["EMA20"].iloc[-lookback:].mean() > df["EMA50"].iloc[-lookback:].mean():
        return "Bullish trend"
    elif df["EMA20"].iloc[-lookback:].mean() < df["EMA50"].iloc[-lookback:].mean():
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
        return setups

    entry_price = ema20 + 0.8 * (ema50 - ema20)

    if trend == "Bearish trend":
        valid_zones = [z for z in zones if z["type"] == "demand" and z["level"] < close]
        if close < ema20 and valid_zones:
            valid_zones.sort(key=lambda z: abs(z["level"] - close))
            nearest_zone = valid_zones[0]
            ema_spread = abs(ema20 - ema50)
            ema_target = close - ema_spread * 2
            zone_target = nearest_zone["level"]
            tp1 = max(ema_target, zone_target)
            tp2 = min(ema_target, zone_target)

            setups.append({
                "symbol": "BTC/USDT",
                "timeframe": tf,
                "type": "Short",
                "entry": float(entry_price),
                "sl": float(ema50 * 1.003),
                "ema_target": float(ema_target),
                "nearest_demand_zone": float(zone_target),
                "tp1": float(tp1),
                "tp2": float(tp2),
                "signal_time": last["timestamp"].isoformat(),
                "status": "pending",
                "entry_time": None,
                "exit_time": None,
                "exit_reason": None
            })

    elif trend == "Bullish trend":
        valid_zones = [z for z in zones if z["type"] == "supply" and z["level"] > close]
        if close > ema20 and valid_zones:
            valid_zones.sort(key=lambda z: abs(z["level"] - close))
            nearest_zone = valid_zones[0]
            ema_spread = abs(ema20 - ema50)
            ema_target = close + ema_spread * 2
            zone_target = nearest_zone["level"]
            tp1 = min(ema_target, zone_target)
            tp2 = max(ema_target, zone_target)

            setups.append({
                "symbol": "BTC/USDT",
                "timeframe": tf,
                "type": "Long",
                "entry": float(entry_price),
                "sl": float(ema50 * 0.997),
                "ema_target": float(ema_target),
                "nearest_supply_zone": float(zone_target),
                "tp1": float(tp1),
                "tp2": float(tp2),
                "signal_time": last["timestamp"].isoformat(),
                "status": "pending",
                "entry_time": None,
                "exit_time": None,
                "exit_reason": None
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

# --- 8. Save trades to JSON ---
def save_trade(trade_id, trade_data, tf):
    filename = "trades.json"
    trades = load_trades(filename)

    if trade_id not in trades:
        trades[trade_id] = trade_data
        with open(filename, "w") as f:
            json.dump(trades, f, indent=4)
        print(f"💾 Saved trade {trade_id}")

        try:
            utc_time = datetime.fromisoformat(trade_data['signal_time'].replace("Z", "+00:00"))
            col_time = utc_time.astimezone(timezone(timedelta(hours=-5)))
            readable_time = col_time.strftime("%a, %b %d %Y - %H:%M (COL)")
        except Exception:
            readable_time = trade_data['signal_time']

        zone_info = ""
        if trade_data['type'] == "Long" and 'nearest_supply_zone' in trade_data:
            zone_info = f"\nSupply Zone: {trade_data['nearest_supply_zone']:.2f}"
        elif trade_data['type'] == "Short" and 'nearest_demand_zone' in trade_data:
            zone_info = f"\nDemand Zone: {trade_data['nearest_demand_zone']:.2f}"
        if 'ema_target' in trade_data:
            zone_info += f"\nEMA Target: {trade_data['ema_target']:.2f}"

        alert_msg = (
            f"📢 New Trade Alert!\n"
            f"Pair: {trade_data['symbol']}\n"
            f"Timeframe: {tf}\n"
            f"Type: {trade_data['type']}\n"
            f"Entry: {trade_data['entry']:.2f}\n"
            f"SL: {trade_data['sl']:.2f}\n"
            f"TP1: {trade_data['tp1']:.2f}\n"
            f"TP2: {trade_data['tp2']:.2f}{zone_info}\n"
            f"Status: {trade_data['status']}\n"
            f"Signal Time: {readable_time}"
        )
        send_telegram_message(alert_msg)

# --- 9. Update trade status (unchanged) ---
def update_trades_status(symbol, df, filename="trades.json"):
    trades = load_trades(filename)
    updated = False

    latest_high = df["high"].iloc[-1]
    latest_low = df["low"].iloc[-1]
    latest_time = df["timestamp"].iloc[-1]

    for trade_id, trade in trades.items():
        status = trade.get("status", "pending")
        try:
            signal_time = datetime.fromisoformat(trade["signal_time"].replace("Z", "+00:00"))
        except Exception:
            signal_time = None
        if signal_time and latest_time <= signal_time:
            continue

        if status == "pending":
            if trade["type"] == "Long" and latest_low <= trade["entry"]:
                trade["status"] = "open"
                trade["entry_time"] = datetime.utcnow().isoformat()
                updated = True
                send_telegram_message(f"✅ Trade Update!\nPair: {trade['symbol']}\nType: {trade['type']}\nEntry: {trade['entry']:.2f}\nStatus: OPEN")
            elif trade["type"] == "Short" and latest_high >= trade["entry"]:
                trade["status"] = "open"
                trade["entry_time"] = datetime.utcnow().isoformat()
                updated = True
                send_telegram_message(f"✅ Trade Update!\nPair: {trade['symbol']}\nType: {trade['type']}\nEntry: {trade['entry']:.2f}\nStatus: OPEN")

        elif status == "open":
            latest_close = df["close"].iloc[-1]
            if (trade["type"] == "Long" and latest_close <= trade["sl"]) or \
               (trade["type"] == "Short" and latest_close >= trade["sl"]):
                trade["status"] = "closed"
                trade["exit_reason"] = "Stop Loss hit"
                trade["exit_time"] = datetime.utcnow().isoformat()
                updated = True
                send_telegram_message(f"❌ Trade Update!\nPair: {trade['symbol']}\nType: {trade['type']}\nStatus: CLOSED (SL)")
            elif (trade["type"] == "Long" and latest_close >= trade["tp2"]) or \
                 (trade["type"] == "Short" and latest_close <= trade["tp2"]):
                trade["status"] = "closed"
                trade["exit_reason"] = "Take Profit hit"
                trade["exit_time"] = datetime.utcnow().isoformat()
                updated = True
                send_telegram_message(f"🎯 Trade Update!\nPair: {trade['symbol']}\nType: {trade['type']}\nStatus: CLOSED (TP)")

    if updated:
        with open(filename, "w") as f:
            json.dump(trades, f, indent=4)

# --- 10. Display Active Trades ---
def display_active_trades(tf, filename="trades.json"):
    trades = load_trades(filename)
    active_trades = {
        trade_id: trade for trade_id, trade in trades.items() 
        if trade.get("timeframe") == tf and trade.get("status") in ["pending", "open"]
    }
    if active_trades:
        print(f"📋 Active Trades for {tf}:")
        for trade_id, trade in active_trades.items():
            status_emoji = "⏳" if trade["status"] == "pending" else "🔄"
            try:
                signal_time = datetime.fromisoformat(trade["signal_time"].replace("Z", "+00:00"))
                time_diff = datetime.now(timezone.utc) - signal_time
                hours_ago = int(time_diff.total_seconds() / 3600)
                time_ago = f"{hours_ago}h ago" if hours_ago > 0 else "Recent"
            except:
                time_ago = "Unknown"
            print(f"  {status_emoji} {trade['type']} | Status: {trade['status'].upper()}")
            print(f"     Entry: {trade['entry']:.2f} | SL: {trade['sl']:.2f} | TP1: {trade['tp1']:.2f} | TP2: {trade['tp2']:.2f}")
            if trade['type'] == "Long" and 'nearest_supply_zone' in trade:
                print(f"     EMA Target: {trade.get('ema_target', 'N/A'):.2f} | Supply Zone: {trade['nearest_supply_zone']:.2f}")
            elif trade['type'] == "Short" and 'nearest_demand_zone' in trade:
                print(f"     EMA Target: {trade.get('ema_target', 'N/A'):.2f} | Demand Zone: {trade['nearest_demand_zone']:.2f}")
            print(f"     Signal: {time_ago}")
            if trade["status"] == "open" and trade.get("entry_time"):
                try:
                    entry_time = datetime.fromisoformat(trade["entry_time"].replace("Z", "+00:00"))
                    entry_diff = datetime.now(timezone.utc) - entry_time
                    entry_hours = int(entry_diff.total_seconds() / 3600)
                    entry_ago = f"{entry_hours}h ago" if entry_hours > 0 else "Recently"
                    print(f"     Opened: {entry_ago}")
                except:
                    pass
            print()
    else:
        print(f"📋 No active trades for {tf}")


# --- Helper: get anchor trend ---
def get_anchor_trend(all_trends):
    """
    Determine anchor trend.
    - 4h Bullish/Bearish overrides everything
    - else fallback to 1h Bullish/Bearish
    - else None
    """
    if all_trends.get("4h") in ["Bullish trend", "Bearish trend"]:
        return "4h", all_trends["4h"]
    if all_trends.get("1h") in ["Bullish trend", "Bearish trend"]:
        return "1h", all_trends["1h"]
    return None, None


# --- Enhanced Main Run Loop with hierarchy ---
timeframes = {"15m": 778, "1h": 490, "4h": 188}

all_trends = {}
all_data = {}
all_setups = {}

# Pass 1: collect data & raw setups
for tf, limit in timeframes.items():
    print(f"\n=== {tf} timeframe ===")
    df = get_ohlcv("BTC/USDT", timeframe=tf, limit=limit)
    df = add_ema(df)
    trend = analyze_trend(df)
    zones = detect_liquidity_zones(df)
    setups = detect_setups(df, trend, zones, tf)

    all_trends[tf] = trend
    all_data[tf] = (df, zones)
    all_setups[tf] = setups

    print(f"Latest Close: {df['close'].iloc[-1]:,.2f}")
    print(f"EMA20: {df['EMA20'].iloc[-1]:,.2f}")
    print(f"EMA50: {df['EMA50'].iloc[-1]:,.2f}")
    print(f"Trend: {trend}")

# Determine anchor trend
anchor_tf, anchor_trend = get_anchor_trend(all_trends)
if anchor_tf:
    print(f"\n📌 Anchor timeframe: {anchor_tf} | Trend: {anchor_trend}")
else:
    print("\n⚠️ No valid anchor trend (all Neutral) → skipping trades")

# Pass 2: filter setups by anchor alignment
for tf, (df, zones) in all_data.items():
    setups = []
    trend = all_trends[tf]

    if anchor_tf is None:
        print(f"⚠️ {tf} skipped (no anchor trend)")
    elif tf == anchor_tf:
        setups = all_setups[tf]
    else:
        if trend == anchor_trend:
            setups = all_setups[tf]
        else:
            print(f"⚠️ {tf} setups skipped (not aligned with {anchor_tf})")

    # Update statuses before new setups
    update_trades_status("BTC/USDT", df)

    # Save new setups
    if setups:
        print("📊 New Setup(s) Detected:")
        for setup in setups:
            print(f"- {setup['type']} | Entry: {setup['entry']:.2f}, SL: {setup['sl']:.2f}, TP1: {setup['tp1']:.2f}, TP2: {setup['tp2']:.2f}")
            unique_id = str(uuid.uuid4())[:8]
            trade_id = f"BTCUSDT_{tf}_{df['timestamp'].iloc[-1].strftime('%Y%m%d_%H%M%S')}_{setup['type'][0]}_{unique_id}"
            save_trade(trade_id, setup, tf)
    else:
        print("📊 No new setups detected")

    # Display active trades
    display_active_trades(tf)
    print("-" * 50)
