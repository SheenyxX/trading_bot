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
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ Telegram error: {response.text}")
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

# --- Adaptive Trade Setup Detection ---
def detect_adaptive_setup(df, tf, zones, trades):
    """
    Adaptive entry logic with duplicate filtering:
    - Entry price threshold: 15m=0.3%, 1h=0.5%, 4h=0.8%
    - Strategy change: Always generate new signal
    - Direction flip: Always generate new signal
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
        if direction == "Long":
            entry_price = ema50 + 0.4 * (ema20 - ema50)
        else:
            entry_price = ema50 - 0.4 * (ema50 - ema20)
    else:
        lookback = 50
        recent_high = max(df["high"].iloc[-lookback:])
        recent_low = min(df["low"].iloc[-lookback:])
        swing_range = recent_high - recent_low
        
        if direction == "Long":
            entry_price = recent_low + 0.575 * swing_range
        else:
            entry_price = recent_high - 0.575 * swing_range

    # Check for existing pending trades (duplicate filter)
    existing_pending = [t for t in trades.values() 
                       if t["timeframe"] == tf and t["status"] == "pending"]
    
    if existing_pending:
        last_trade = existing_pending[-1]
        
        # Entry price change thresholds by timeframe
        thresholds = {"15m": 0.003, "1h": 0.005, "4h": 0.008}
        entry_threshold = thresholds.get(tf, 0.005)
        
        # Calculate % change in entry price
        entry_change = abs(entry_price - last_trade["entry"]) / last_trade["entry"]
        
        # Skip if: same direction + same strategy + entry change below threshold
        if (direction == last_trade["type"] and 
            strategy == last_trade.get("strategy") and
            entry_change < entry_threshold):
            print(f"   ⏭️  Skipping duplicate: Entry change {entry_change*100:.2f}% < {entry_threshold*100:.1f}%")
            return []

    # ATR-based stop loss (1.5x ATR)
    if direction == "Long":
        sl = entry_price - 1.5 * atr
        tp1 = entry_price + 2 * (entry_price - sl)
        tp2 = entry_price + 3 * (entry_price - sl)
    else:
        sl = entry_price + 1.5 * atr
        tp1 = entry_price - 2 * (sl - entry_price)
        tp2 = entry_price - 3 * (sl - entry_price)

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

    # Build trade structure
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

# --- Save Trade ---
def save_trade(trade, filename="trades.json"):
    """Save trade to JSON and send Telegram notification"""
    trades = load_trades(filename)
    
    if trade["trade_id"] in trades:
        return
    
    trades[trade["trade_id"]] = trade
    
    with open(filename, "w") as f:
        json.dump(trades, f, indent=4)

    # Telegram notification for new signal
    msg = (
        f"🔔 <b>NEW TRADE SIGNAL</b>\n\n"
        f"<b>ID:</b> <code>{trade['trade_id']}</code>\n"
        f"<b>Status:</b> 🟡 PENDING\n\n"
        f"<b>Pair:</b> {trade['symbol']}\n"
        f"<b>Timeframe:</b> {trade['timeframe']}\n"
        f"<b>Strategy:</b> {trade['strategy']} (Slope: {trade['slope']}%)\n"
        f"<b>Type:</b> {'📈 LONG' if trade['type'] == 'Long' else '📉 SHORT'}\n\n"
        f"<b>Entry:</b> ${trade['entry']:,.2f}\n"
        f"<b>Stop Loss:</b> ${trade['sl']:,.2f}\n"
        f"<b>Take Profit 1:</b> ${trade['tp1']:,.2f} (2R)\n"
        f"<b>Take Profit 2:</b> ${trade['tp2']:,.2f} (3R)\n\n"
        f"<b>Risk/Reward:</b> {trade['rr_ratio']}:1"
    )
    send_telegram_message(msg)

# --- Update Trades Status ---
def update_trades_status(df, filename="trades.json"):
    """Monitor and update trade status: pending → open → closed/expired"""
    trades = load_trades(filename)
    updated = False
    
    latest_high = df["high"].iloc[-1]
    latest_low = df["low"].iloc[-1]
    latest_close = df["close"].iloc[-1]
    now = datetime.now(timezone.utc)
    
    # Expiry times by timeframe
    expiry_times = {
        "15m": timedelta(hours=2),
        "1h": timedelta(hours=12),
        "4h": timedelta(days=3)
    }
    
    for trade_id, trade in list(trades.items()):
        status = trade.get("status", "pending")
        tf = trade.get("timeframe", "1h")
        
        try:
            signal_time = datetime.fromisoformat(trade["signal_time"].replace("Z", "+00:00"))
        except:
            signal_time = None
        
        # --- PENDING → OPEN or EXPIRED ---
        if status == "pending":
            # Check expiry
            if signal_time and now - signal_time > expiry_times.get(tf, timedelta(hours=12)):
                trade["status"] = "expired"
                trade["exit_reason"] = "Signal expired"
                trade["exit_time"] = now.isoformat()
                updated = True
                
                msg = (
                    f"⏱️ <b>TRADE EXPIRED</b>\n\n"
                    f"<b>ID:</b> <code>{trade_id}</code>\n"
                    f"<b>Status:</b> ⚫ EXPIRED\n\n"
                    f"<b>Reason:</b> Signal timeout ({expiry_times.get(tf)})\n"
                    f"<b>Pair:</b> {trade['symbol']}\n"
                    f"<b>Type:</b> {trade['type']}"
                )
                send_telegram_message(msg)
            
            # Check if entry hit
            elif trade["type"] == "Long" and latest_low <= trade["entry"]:
                trade["status"] = "open"
                trade["entry_time"] = now.isoformat()
                updated = True
                
                msg = (
                    f"✅ <b>TRADE OPENED</b>\n\n"
                    f"<b>ID:</b> <code>{trade_id}</code>\n"
                    f"<b>Status:</b> 🟢 OPEN\n\n"
                    f"<b>Pair:</b> {trade['symbol']}\n"
                    f"<b>Type:</b> {'📈 LONG' if trade['type'] == 'Long' else '📉 SHORT'}\n"
                    f"<b>Entry:</b> ${trade['entry']:,.2f}\n"
                    f"<b>Current Price:</b> ${latest_close:,.2f}"
                )
                send_telegram_message(msg)
            
            elif trade["type"] == "Short" and latest_high >= trade["entry"]:
                trade["status"] = "open"
                trade["entry_time"] = now.isoformat()
                updated = True
                
                msg = (
                    f"✅ <b>TRADE OPENED</b>\n\n"
                    f"<b>ID:</b> <code>{trade_id}</code>\n"
                    f"<b>Status:</b> 🟢 OPEN\n\n"
                    f"<b>Pair:</b> {trade['symbol']}\n"
                    f"<b>Type:</b> {'📈 LONG' if trade['type'] == 'Long' else '📉 SHORT'}\n"
                    f"<b>Entry:</b> ${trade['entry']:,.2f}\n"
                    f"<b>Current Price:</b> ${latest_close:,.2f}"
                )
                send_telegram_message(msg)
        
        # --- OPEN → CLOSED ---
        elif status == "open":
            # Check stop loss
            if ((trade["type"] == "Long" and latest_close <= trade["sl"]) or 
                (trade["type"] == "Short" and latest_close >= trade["sl"])):
                
                trade["status"] = "closed"
                trade["exit_reason"] = "Stop Loss"
                trade["exit_time"] = now.isoformat()
                trade["outcome"] = "loss"
                
                # Calculate duration
                if trade.get("entry_time"):
                    try:
                        entry_dt = datetime.fromisoformat(trade["entry_time"].replace("Z", "+00:00"))
                        trade["duration_minutes"] = int((now - entry_dt).total_seconds() / 60)
                    except:
                        pass
                
                updated = True
                
                msg = (
                    f"❌ <b>TRADE CLOSED - STOP LOSS</b>\n\n"
                    f"<b>ID:</b> <code>{trade_id}</code>\n"
                    f"<b>Status:</b> 🔴 CLOSED\n\n"
                    f"<b>Pair:</b> {trade['symbol']}\n"
                    f"<b>Type:</b> {trade['type']}\n"
                    f"<b>Entry:</b> ${trade['entry']:,.2f}\n"
                    f"<b>Exit:</b> ${latest_close:,.2f}\n"
                    f"<b>Result:</b> LOSS 📉"
                )
                if trade.get("duration_minutes"):
                    msg += f"\n<b>Duration:</b> {trade['duration_minutes']} minutes"
                send_telegram_message(msg)
            
            # Check take profit
            elif ((trade["type"] == "Long" and latest_close >= trade["tp2"]) or 
                  (trade["type"] == "Short" and latest_close <= trade["tp2"])):
                
                trade["status"] = "closed"
                trade["exit_reason"] = "Take Profit"
                trade["exit_time"] = now.isoformat()
                trade["outcome"] = "win"
                
                # Calculate duration
                if trade.get("entry_time"):
                    try:
                        entry_dt = datetime.fromisoformat(trade["entry_time"].replace("Z", "+00:00"))
                        trade["duration_minutes"] = int((now - entry_dt).total_seconds() / 60)
                    except:
                        pass
                
                updated = True
                
                msg = (
                    f"🎯 <b>TRADE CLOSED - TAKE PROFIT</b>\n\n"
                    f"<b>ID:</b> <code>{trade_id}</code>\n"
                    f"<b>Status:</b> 🟢 CLOSED\n\n"
                    f"<b>Pair:</b> {trade['symbol']}\n"
                    f"<b>Type:</b> {trade['type']}\n"
                    f"<b>Entry:</b> ${trade['entry']:,.2f}\n"
                    f"<b>Exit:</b> ${latest_close:,.2f}\n"
                    f"<b>Result:</b> WIN 🎉"
                )
                if trade.get("duration_minutes"):
                    msg += f"\n<b>Duration:</b> {trade['duration_minutes']} minutes"
                send_telegram_message(msg)
    
    # Save if any updates
    if updated:
        with open(filename, "w") as f:
            json.dump(trades, f, indent=4)

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
            
            # Load existing trades
            trades = load_trades()
            
            # Update status of existing trades first
            update_trades_status(df)
            
            # Reload trades after updates
            trades = load_trades()
            
            # Detect liquidity zones
            zones = detect_liquidity_zones(df)
            
            # Detect adaptive setups (with duplicate filtering)
            setups = detect_adaptive_setup(df, tf, zones, trades)

            # Print market state
            print(f"Close: ${df['close'].iloc[-1]:,.2f}")
            print(f"EMA20: ${df['EMA20'].iloc[-1]:,.2f}")
            print(f"EMA50: ${df['EMA50'].iloc[-1]:,.2f}")
            print(f"ATR: {df['ATR'].iloc[-1]:.2f}")
            print(f"Zones: {len(zones)}")
            
            # Save new setups
            for setup in setups:
                save_trade(setup)
                print(f"✅ {setup['type']} signal | Strategy: {setup['strategy']} | RR: {setup['rr_ratio']}:1")
            
            if not setups:
                print("   No new signals generated")
            
            print()
                
        except Exception as e:
            print(f"❌ Error processing {tf}: {e}\n")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
