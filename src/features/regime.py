import pandas as pd
import numpy as np
from .config import FeatureConfig, load_feature_config

def detect_market_regime(df, config: FeatureConfig | None = None):
    config = config or load_feature_config()
    last = df.iloc[-1]
    close = last['close']
    ema20 = last[f'ema{config.ema_fast}']
    ema50 = last[f'ema{config.ema_medium}']
    ema200 = last[f'ema{config.ema_slow}']
    
    if close > ema200 and ema20 >= ema50:
        return 'BULL'
    elif close < ema200 and ema50 < ema200:
        return 'BEAR'
    return 'NEUTRAL'

def is_panic(df, config: FeatureConfig | None = None):
    config = config or load_feature_config()
    vol_period = 10 if 10 in config.realized_vol_windows else config.realized_vol_period
    # Volatility check: 10d vol > 90th percentile of 252d history
    vol_10d = df[f'realized_vol_{vol_period}'].iloc[-1]
    hist_10d_vols = df[f'realized_vol_{vol_period}'].tail(252)
    vol_threshold = hist_10d_vols.quantile(0.90)
    
    # Drawdown check: daily drawdown > 3 * ATR
    # Daily drawdown is not explicitly in df. Let's calculate: Close / PrevClose - 1
    daily_dd = (df['close'] / df['close'].shift(1) - 1).abs()
    panic_dd = daily_dd.iloc[-1] > (3 * df[f'atr{config.atr_period}'].iloc[-1] / df['close'].iloc[-1])
    # Wait, 3*ATR as drawdown? Usually ATR is in price. Drawdown is usually %.
    # "daily drawdown > 3 * ATR". This might mean: (Close - PrevClose) / Close < -3 * (ATR / Close)
    # Let's assume it means (Close - PrevClose) < -3 * ATR.
    
    panic_price_drop = (df['close'].iloc[-1] - df['close'].shift(1).iloc[-1]) < (-3 * df[f'atr{config.atr_period}'].iloc[-1])
    
    return vol_10d > vol_threshold or panic_price_drop
