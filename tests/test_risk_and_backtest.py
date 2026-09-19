import pytest
from src.risk.position_sizing import calculate_position_size
from src.backtest.metrics import calculate_metrics
import pandas as pd

def test_position_sizing():
    size = calculate_position_size(target_vol=0.2, realized_vol=0.1, base_capital=100000, max_risk_pct=0.1)
    # multiplier = 0.2/0.1 = 2.0 -> clipped to 1.5
    # size = 100000 * 0.1 * 1.5 = 15000
    assert size == 15000

def test_metrics():
    equity = pd.Series([100, 110, 105, 120])
    metrics = calculate_metrics(equity)
    assert "CAGR" in metrics
    assert "Max Drawdown" in metrics
