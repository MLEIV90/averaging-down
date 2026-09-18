import pandas as pd
def classify_regime(row):
    p,e50,e200=row.get("Close"),row.get("EMA50"),row.get("EMA200")
    if pd.isna(p) or pd.isna(e50) or pd.isna(e200): return "NEUTRAL"
    if p>e200 and e50>e200: return "BULL"
    if p<e200 and e50<e200: return "BEAR"
    return "NEUTRAL"
def add_regime(df):
    out=df.copy(); out["Regime"]=out.apply(classify_regime,axis=1); return out
