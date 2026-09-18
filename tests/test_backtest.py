import pandas as pd
from src.backtest.metrics import max_drawdown
def test_max_drawdown(): assert round(max_drawdown(pd.Series([100,110,99,120])),4)==-0.1
