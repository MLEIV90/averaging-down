import pandas as pd
import numpy as np
from src.features.indicators import calculate_ema, calculate_atr, calculate_d_atr

def sample_data():
    return pd.DataFrame({
        "Open": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24],
        "High": [11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25],
        "Low": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
        "Close": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
    })

def test_ema_computation():
    df = sample_data()
    ema = calculate_ema(df['Close'], 2)
    assert len(ema) == len(df)
    assert ema.notna().all()

def test_atr_computation():
    df = sample_data()
    atr = calculate_atr(df, period=2)
    assert len(atr) == len(df)
    # ATR is NaN for first period-1
    assert atr.iloc[1:].notna().all()

def test_d_atr_computation():
    df = sample_data()
    ema = calculate_ema(df['Close'], 2)
    atr = calculate_atr(df, period=2)
    d_atr = calculate_d_atr(df['Close'], ema, atr)
    # ATR is NaN for first period-1, so D_ATR will be NaN for first period-1
    assert d_atr.iloc[1:].notna().all()
