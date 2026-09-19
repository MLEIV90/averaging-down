import numpy as np
import pandas as pd

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calculate_atr(df, period=14):
    high = df['High']
    low = df['Low']
    close = df['Close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_d_atr(close, ema_fast, atr):
    return (close - ema_fast) / atr

def calculate_realized_volatility(close, windows=[10, 20, 60]):
    log_returns = np.log(close / close.shift(1))
    vol = {}
    for window in windows:
        vol[f'vol_{window}'] = log_returns.rolling(window=window).std() * np.sqrt(252)
    return pd.DataFrame(vol)

def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))
