import pandas as pd
from src.features.indicators import add_ema,add_atr
def sample_data():
    return pd.DataFrame({"Open":[10,11,12,13,14],"High":[11,12,13,14,15],"Low":[9,10,11,12,13],"Close":[10,11,12,13,14]})
def test_ema_created():
    df=add_ema(sample_data(),periods=(2,)); assert "EMA2" in df and df["EMA2"].notna().all()
def test_atr_created():
    df=add_atr(sample_data(),period=2); assert "ATR2" in df
