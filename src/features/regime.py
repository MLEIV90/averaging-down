import pandas as pd
import numpy as np

def detect_market_regime(df):
    last = df.iloc[-1]
    close = last['Close']
    ema20 = last['EMA20']
    ema50 = last['EMA50']
    ema200 = last['EMA200']
    
    if close > ema200 and ema20 >= ema50:
        return 'BULL'
    elif close < ema200 and ema50 < ema200:
        return 'BEAR'
    return 'NEUTRAL'

def is_panic(df):
    # Volatility check: 10d vol > 90th percentile of 252d history
    vol_10d = df['vol_10'].iloc[-1]
    vol_252d_history = df['vol_10'].rolling(window=252).mean() # This is not strictly 90th percentile of 252, but let's follow instruction
    # Correction: "10-day realized volatility > 90th percentile of last 252 days"
    hist_10d_vols = df['vol_10'].tail(252)
    vol_threshold = hist_10d_vols.quantile(0.90)
    
    # Drawdown check: daily drawdown > 3 * ATR
    # Daily drawdown is not explicitly in df. Let's calculate: Close / PrevClose - 1
    daily_dd = (df['Close'] / df['Close'].shift(1) - 1).abs()
    panic_dd = daily_dd.iloc[-1] > (3 * df['ATR14'].iloc[-1] / df['Close'].iloc[-1]) # Assuming ATR is in price units. Need to normalize ATR or Drawdown.
    # Wait, 3*ATR as drawdown? Usually ATR is in price. Drawdown is usually %.
    # "daily drawdown > 3 * ATR". This might mean: (Close - PrevClose) / Close < -3 * (ATR / Close)
    # Let's assume it means (Close - PrevClose) < -3 * ATR.
    
    panic_price_drop = (df['Close'].iloc[-1] - df['Close'].shift(1).iloc[-1]) < (-3 * df['ATR14'].iloc[-1])
    
    return vol_10d > vol_threshold or panic_price_drop
