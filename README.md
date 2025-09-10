# Trading Bot 

An automated trading signal generator that analyzes Bitcoin price movements across multiple timeframes using EMA trend analysis and liquidity zone detection. The bot identifies potential trading setups based on technical patterns and sends real-time alerts via Telegram to help traders spot opportunities.

## 🎯 What This Product Does

This trading bot is designed to help cryptocurrency traders by:

- **Automated Signal Generation**: Continuously monitors BTC/USDT across 15-minute, 1-hour, and 4-hour timeframes
- **Smart Entry Detection**: Uses EMA crossovers and liquidity zone analysis to identify optimal entry points
- **Risk Management**: Automatically calculates stop-loss and take-profit levels for each signal
- **Real-Time Alerts**: Sends instant notifications via Telegram when new signals are detected
- **Trade Tracking**: Monitors active trades and updates you when entries, stop-losses, or take-profits are hit

## 📊 How It Works

### Signal Generation Algorithm

The bot uses a multi-layered approach to identify trading opportunities:

#### 1. **Trend Analysis**
- Calculates 20-period and 50-period Exponential Moving Averages (EMAs)
- **Bullish Trend**: EMA20 > EMA50 (generates long signals)
- **Bearish Trend**: EMA20 < EMA50 (generates short signals)
- **Neutral Trend**: EMAs are equal (no signals generated)

#### 2. **Liquidity Zone Detection**
- Identifies significant support and demand levels by analyzing:
  - Local highs and lows over a 50-candle lookback period
  - Volume confirmation at these levels
- **Supply Zones**: Areas where price previously faced selling pressure
- **Demand Zones**: Areas where price previously found buying support

#### 3. **Entry Signal Conditions**

**For Long Positions (Bullish Trend)**:
- Price must be above EMA20
- Must have valid supply zones above current price
- Entry: 80% of the way from EMA20 to EMA50
- Stop Loss: 0.3% below EMA50
- Take Profit 1: Current price + 2x the EMA spread
- Take Profit 2: Nearest supply zone level

**For Short Positions (Bearish Trend)**:
- Price must be below EMA20
- Must have valid demand zones below current price
- Entry: 80% of the way from EMA20 to EMA50
- Stop Loss: 0.3% above EMA50
- Take Profit 1: Current price - 2x the EMA spread
- Take Profit 2: Nearest demand zone level

### Multi-Timeframe Analysis

The bot analyzes three timeframes simultaneously:
- **15-minute**: For scalping and short-term trades
- **1-hour**: For intraday swing trades
- **4-hour**: For longer-term position trades

Each timeframe operates independently, allowing for different trading styles and risk preferences.

## 💡 How It Helps Traders

### 1. **Removes Emotional Trading**
- Eliminates fear and greed from decision-making
- Provides objective, rule-based signals
- Consistent methodology across all market conditions

### 2. **24/7 Market Monitoring**
- Never misses a trading opportunity
- Works while you sleep or focus on other activities
- Instant alerts ensure you don't miss entries or exits

### 3. **Risk Management**
- Pre-calculated stop-losses protect your capital
- Multiple take-profit levels optimize profit potential
- Clear risk-reward ratios for each trade

### 4. **Time Efficiency**
- No need to constantly watch charts
- Automated analysis saves hours of manual work
- Focus on trade execution rather than analysis

### 5. **Backtesting Capability**
- Historical performance tracking
- Trade statistics and success rates
- Continuous strategy refinement

## 🛠️ Setup Requirements

### Dependencies
```bash
pip install ccxt pandas ta requests
```

### Required Libraries
- **ccxt**: For cryptocurrency exchange connectivity
- **pandas**: For data manipulation and analysis
- **ta**: For technical analysis indicators
- **requests**: For Telegram API communication

### Environment Variables
Set up your Telegram bot credentials:
```bash
export BOT_TOKEN="your_telegram_bot_token"
export CHAT_ID="your_telegram_chat_id"
```

## 📱 Telegram Integration

The bot sends detailed alerts including:
- **New Signal Alerts**: Entry price, stop-loss, take-profits, and timeframe
- **Trade Updates**: When entries are hit and positions open
- **Exit Notifications**: When stop-losses or take-profits are triggered
- **Local Time**: All timestamps converted to Colombia timezone (UTC-5)

### Sample Alert Messages

**New Signal**:
```
📢 New Trade Alert!
Pair: BTC/USDT
Timeframe: 1h
Type: Long
Entry: 43,250.00
SL: 42,800.00
TP1: 44,100.00
TP2: 44,650.00
Status: pending
Signal Time: Mon, Dec 09 2024 - 15:30 (COL)
```

**Trade Update**:
```
✅ Trade Update!
Pair: BTC/USDT
Type: Long
Entry: 43,250.00
Status: OPEN
```

## 📈 Trading Strategy Summary

This bot implements a **trend-following strategy with liquidity zone confirmation**:

- **Market Structure**: Uses EMAs to determine overall trend direction
- **Entry Timing**: Waits for price to respect the trend near EMA levels
- **Target Selection**: Aims for previous liquidity zones where price may react
- **Risk Control**: Tight stops with multiple profit targets for optimal risk-reward

## ⚠️ Risk Disclaimer

This trading bot is for educational and informational purposes only. Cryptocurrency trading carries significant risk, and you should:

- Never risk more than you can afford to lose
- Thoroughly test the strategy before live trading
- Consider market volatility and liquidity
- Use proper position sizing
- Monitor performance and adjust as needed

Past performance does not guarantee future results.

## 🔧 Customization Options

The bot can be easily modified for:
- Different cryptocurrency pairs
- Alternative timeframes
- Custom EMA periods
- Different risk-reward ratios
- Additional technical indicators
- Alternative exchange connections

## 📊 Performance Tracking

The bot maintains a JSON file (`trades.json`) with complete trade history including:
- Signal generation time
- Entry and exit prices
- Trade duration
- Profit/loss results
- Exit reasons (TP/SL)

## 🚀 Getting Started

1. Install dependencies
2. Set up Telegram bot and get credentials
3. Configure environment variables
4. Run the script: `python main.py`
5. Monitor Telegram for signals
6. Execute trades based on alerts

---

*Built for serious traders who want to leverage technical analysis automation for consistent market opportunities.*
