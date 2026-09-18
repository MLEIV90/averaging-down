def add_features(df):
    from .indicators import add_ema,add_atr,add_rsi,add_drawdown
    from .volatility import add_realized_vol,add_z_atr
    from .regime import add_regime
    out=add_ema(df); out=add_atr(out); out=add_rsi(out); out=add_drawdown(out)
    out=add_realized_vol(out); out=add_z_atr(out); return add_regime(out)
