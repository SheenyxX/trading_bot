# main.py
import ccxt
import pandas as pd
import ta
from datetime import datetime, timedelta, timezone
import json
import os
import requests
import hashlib

# --- Telegram Bot Setup ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def send_telegram_message(text):
    """Send message to Telegram bot"""
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ Telegram credentials not set")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"⚠️ Failed to send Telegram message: {e}")

# --- Exchange Setup ---
exchange = ccxt.kucoin()

# --- Fetch OHLCV ---
def get_ohlcv(symbol="BTC/USDT", timeframe="15m", limit=500):
    """Fetch OHLCV data from exchange"""
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df

# --- Add Indicators ---
def add_indicators(df):
    """Add EMA20, EMA50, and ATR indicators"""
    df["EMA20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["EMA50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ATR"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)
    return df

# --- Detect Liquidity Zones ---
def detect_liquidity_zones(df, lookback=50):
    """Detect supply and demand zones at swing highs/lows"""
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

# --- Calculate EMA50 Slope ---
def calculate_ema_slope(df, window=20):
    """Calculate EMA50 slope percentage over window"""
    ema_now = df["EMA50"].iloc[-1]
    ema_past = df["EMA50"].iloc[-window]
    return ((ema_now - ema_past) / ema_past) * 100

# --- Adaptive Trade Setup Detection ---
def detect_adaptive_setup(df, tf, zones):
    """
    Adaptive entry logic based on EMA50 slope:
    - Strong trends: Entry between EMAs (40% from EMA50)
    - Weak/Ranging: Fibonacci retracement (57.5% of swing range)
    - ATR-based SL: 1.5x ATR
    - TPs: 2R and 3R
    - TP2 snaps to nearest liquidity zone
    """
    setups = []
    last = df.iloc[-1]
    slope = calculate_ema_slope(df)
    atr = df["ATR"].iloc[-1]
    ema20 = last["EMA20"]
    ema50 = last["EMA50"]
    
    # Classify market condition
    if slope > 0.8:
        strategy = "strong_up"
    elif slope > 0.3:
        strategy = "weak_up"
    elif slope > -0.3:
        strategy = "ranging"
    elif slope > -0.8:
        strategy = "weak_down"
    else:
        strategy = "strong_down"

    # Determine direction
    if strategy == "ranging":
        direction = "Long" if ema20 > ema50 else "Short"
    else:
        direction = "Long" if "up" in strategy else "Short"

    # Calculate entry price
    if "strong" in strategy:
        # Strong trend: Entry between EMAs (40% from EMA50)
        if direction == "Long":
            entry_price = ema50 + 0.4 * (ema20 - ema50)
        else:
            entry_price = ema50 - 0.4 * (ema50 - ema20)
    else:
        # Weak/Ranging: Fibonacci retracement (57.5% of swing)
        lookback = 50
        recent_high = max(df["high"].iloc[-lookback:])
        recent_low = min(df["low"].iloc[-lookback:])
        swing_range = recent_high - recent_low
        
        if direction == "Long":
            entry_price = recent_low + 0.575 * swing_range
        else:
            entry_price = recent_high - 0.575 * swing_range

    # ATR-based stop loss (1.5x ATR)
    if direction == "Long":
        sl = entry_price - 1.5 * atr
        tp1 = entry_price + 2 * (entry_price - sl)  # 2R
        tp2 = entry_price + 3 * (entry_price - sl)  # 3R
    else:
        sl = entry_price + 1.5 * atr
        tp1 = entry_price - 2 * (sl - entry_price)  # 2R
        tp2 = entry_price - 3 * (sl - entry_price)  # 3R

    # Snap TP2 to nearest liquidity zone
    if direction == "Long":
        valid_zones = [z for z in zones if z["type"] == "supply" and z["level"] > tp2]
        if valid_zones:
            nearest_zone = min(valid_zones, key=lambda z: abs(z["level"] - tp2))
            tp2 = nearest_zone["level"]
    else:
        valid_zones = [z for z in zones if z["type"] == "demand" and z["level"] < tp2]
        if valid_zones:
            nearest_zone = min(valid_zones, key=lambda z: abs(z["level"] - tp2))
            tp2 = nearest_zone["level"]

    # Generate unique trade ID
    signal_time = df["timestamp"].iloc[-1].isoformat()
    timestamp_str = df["timestamp"].iloc[-1].strftime('%Y%m%d_%H%M%S')
    entry_hash = hashlib.md5(str(entry_price).encode()).hexdigest()[:8]
    trade_id = f"BTCUSDT_{tf}_{timestamp_str}_{direction[0]}_{entry_hash}"

    # Calculate risk-reward ratio
    risk = abs(entry_price - sl)
    reward = abs(tp1 - entry_price)
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0

    # Build trade structure (schema-compliant for dashboard)
    setups.append({
        "trade_id": trade_id,
        "symbol": "BTC/USDT",
        "timeframe": tf,
        "type": direction,
        "status": "pending",
        "strategy": strategy,
        "slope": round(slope, 2),
        "entry": float(entry_price),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp2": float(tp2),
        "rr_ratio": rr_ratio,
        "signal_time": signal_time,
        "entry_time": None,
        "exit_time": None,
        "exit_reason": None,
        "duration_minutes": None,
        "outcome": None
    })
    
    return setups

# --- Load Trades ---
def load_trades(filename="trades.json"):
    """Load trades from JSON file"""
    if not os.path.exists(filename):
        return {}
    try:
        with open(filename, "r") as f:
            data = f.read().strip()
            if not data:
                return {}
            return json.loads(data)
    except Exception as e:
        print(f"⚠️ Error loading trades: {e}")
        return {}

# --- Save Trade ---
def save_trade(trade, filename="trades.json"):
    """Save trade to JSON and send Telegram notification"""
    trades = load_trades(filename)
    
    if trade["trade_id"] in trades:
        return
    
    trades[trade["trade_id"]] = trade
    
    with open(filename, "w") as f:
        json.dump(trades, f, indent=4)

    # Telegram notification
    msg = (
        f"📢 New Trade Signal\n"
        f"🆔 {trade['trade_id']}\n\n"
        f"Pair: {trade['symbol']}\n"
        f"Timeframe: {trade['timeframe']}\n"
        f"Strategy: {trade['strategy']} (Slope: {trade['slope']}%)\n"
        f"Type: {'📈 Long' if trade['type'] == 'Long' else '📉 Short'}\n\n"
        f"Entry: {trade['entry']:.2f}\n"
        f"SL: {trade['sl']:.2f} (1.5x ATR)\n"
        f"TP1: {trade['tp1']:.2f} (2R)\n"
        f"TP2: {trade['tp2']:.2f} (3R)\n\n"
        f"Risk/Reward: {trade['rr_ratio']}:1"
    )
    send_telegram_message(msg)

# --- Main Execution ---
def main():
    """Main execution loop"""
    timeframes = {
        "15m": 500,
        "1h": 500,
        "4h": 500
    }

    print("🚀 Adaptive Trading Bot Started\n")
    
    for tf, limit in timeframes.items():
        print(f"=== {tf} Timeframe ===")
        
        try:
            # Fetch data and add indicators
            df = get_ohlcv("BTC/USDT", timeframe=tf, limit=limit)
            df = add_indicators(df)
            
            # Detect liquidity zones
            zones = detect_liquidity_zones(df)
            
            # Detect adaptive setups
            setups = detect_adaptive_setup(df, tf, zones)

            # Print market state
            print(f"Close: {df['close'].iloc[-1]:,.2f}")
            print(f"EMA20: {df['EMA20'].iloc[-1]:,.2f}")
            print(f"EMA50: {df['EMA50'].iloc[-1]:,.2f}")
            print(f"ATR: {df['ATR'].iloc[-1]:.2f}")
            print(f"Liquidity Zones: {len(zones)}")
            
            # Save setups
            for setup in setups:
                save_trade(setup)
                print(f"✅ {setup['type']} setup saved | Strategy: {setup['strategy']} | RR: {setup['rr_ratio']}:1\n")
                
        except Exception as e:
            print(f"❌ Error processing {tf}: {e}\n")

if __name__ == "__main__":
    main()
