# Crypto Trading Assistant  

This project is a Python-based **trade signal tracker** for **BTC/USDT**.  
It analyzes market structure using **EMA trend detection** and **liquidity zones**, generates trade setups, and tracks their full lifecycle (pending → open → closed).  

All trades are saved in `trades.json`, and alerts are sent to **Telegram** in real-time.  

Think of it as a **smart assistant** that helps you spot and track trades automatically.  

---

## 🚀 How the Strategy Works  

The strategy is designed around **trend-following with liquidity confirmation**, combining technical analysis with smart money concepts:  

1. **EMA Trend Detection**  
   - The bot calculates the **20-period EMA** and the **50-period EMA**.  
   - When **EMA20 > EMA50**, the market is in a bullish trend → bot looks for **long trades**.  
   - When **EMA20 < EMA50**, the market is in a bearish trend → bot looks for **short trades**.  

2. **Liquidity Zones**  
   - The bot identifies areas where price is likely to react (previous highs/lows, consolidations).  
   - These zones act as **entry confirmation points** where orders are triggered.  

3. **Trade Lifecycle Management**  
   - Every trade has a unique **trade ID**.  
   - Trades start as **pending**, move to **open** once executed, and then to **closed** when the exit conditions are met.  
   - All trades are stored in `trades.json`, ensuring complete traceability.  

4. **Telegram Alerts**  
   - The bot notifies you instantly when:  
     - A new setup is detected.  
     - A trade is entered.  
     - A trade is closed.  
   - This way, you always stay in control without staring at charts all day.  

---

## 🎯 Why This Strategy?  

This system is built like a **product for traders who want confidence and automation**:  

- **Transparency** → Every trade is logged, tracked, and stored.  
- **Trend-Following Core** → EMA structure ensures we only trade in the dominant direction.  
- **Liquidity Awareness** → Trades are aligned with market psychology, not random entries.  
- **Automation with Control** → You get real-time alerts but still choose how to act on them.  

Think of it as a **personal trading assistant**:  
- It watches the charts 24/7.  
- It tells you when conditions align.  
- It records every step so you can review, optimize, and trust the process.  

---
