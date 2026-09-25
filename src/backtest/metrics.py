import pandas as pd
import numpy as np

def max_drawdown(equity_curve):
    """
    Calcula el Drawdown Máximo de una curva de capital.
    """
    if equity_curve.empty:
        return 0
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    return drawdown.min()

def calculate_metrics(equity_curve):
    """
    Calcula métricas clave del backtest.
    """
    returns = equity_curve.pct_change().dropna()
    
    cagr = (equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (252 / len(equity_curve)) - 1
    
    max_dd = max_drawdown(equity_curve)
    
    sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
    
    negative_returns = returns[returns < 0]
    sortino = (returns.mean() / negative_returns.std()) * np.sqrt(252)
    
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    win_rate = len(returns[returns > 0]) / len(returns)
    
    return {
        "CAGR": cagr,
        "Max Drawdown": max_dd,
        "Sharpe Ratio": sharpe,
        "Sortino Ratio": sortino,
        "Calmar Ratio": calmar,
        "Win Rate": win_rate
    }
