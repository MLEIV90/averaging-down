def add_realized_vol(df, window=20, annualization=252):
    out=df.copy(); out[f"RealizedVol{window}"]=out["Close"].pct_change().rolling(window).std()*(annualization**0.5); return out
def add_z_atr(df, ema_col="EMA20", atr_col="ATR14"):
    out=df.copy(); out["Z_ATR"]=(out["Close"]-out[ema_col])/out[atr_col]; return out
