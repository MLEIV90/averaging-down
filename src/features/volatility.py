"""Deprecated DataFrame adapters; all formulas live in indicators.py."""

from .indicators import calculate_realized_volatility, calculate_z_atr


def add_realized_vol(df, window=20, annualization=252):
    close = df["close"] if "close" in df else df["Close"]
    out = df.copy()
    values = calculate_realized_volatility(close, (window,), annualization, return_method="simple")
    out[f"RealizedVol{window}"] = values.iloc[:, 0]
    return out


def add_z_atr(df, ema_col="EMA20", atr_col="ATR14"):
    close = df["close"] if "close" in df else df["Close"]
    ema = df[ema_col] if ema_col in df else df[ema_col.lower()]
    atr = df[atr_col] if atr_col in df else df[atr_col.lower()]
    out = df.copy()
    out["Z_ATR"] = calculate_z_atr(close, ema, atr)
    return out
