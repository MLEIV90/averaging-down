import numpy as np
import pandas as pd
def add_ema(df, periods=(20,50,200)):
    out=df.copy()
    for p in periods: out[f"EMA{p}"]=out["Close"].ewm(span=p,adjust=False).mean()
    return out
def add_atr(df, period=14):
    out=df.copy(); pc=out["Close"].shift(1)
    tr=pd.concat([out["High"]-out["Low"],(out["High"]-pc).abs(),(out["Low"]-pc).abs()],axis=1).max(axis=1)
    out[f"ATR{period}"]=tr.rolling(period).mean(); return out
def add_rsi(df, period=2):
    out=df.copy(); d=out["Close"].diff()
    gain=d.clip(lower=0).rolling(period).mean(); loss=(-d.clip(upper=0)).rolling(period).mean()
    rs=gain/loss.replace(0,np.nan); out[f"RSI{period}"]=100-(100/(1+rs)); return out
def add_drawdown(df):
    out=df.copy(); out["Drawdown"]=out["Close"]/out["Close"].cummax()-1; return out
