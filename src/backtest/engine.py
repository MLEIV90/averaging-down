import pandas as pd
import numpy as np

def run_backtest(data_dict):
    """
    Simulación histórica para el portfolio (SPY, BTC-USD, GLD).
    data_dict: dict de {ticker: df}
    """
    if not data_dict or 'SPY' not in data_dict:
        return pd.Series(dtype=float)
        
    # Align closes of all available assets
    closes = pd.DataFrame({t: df['Close'] for t, df in data_dict.items() if not df.empty}).dropna()
    if closes.empty:
        return pd.Series(dtype=float)
        
    # Calculate daily returns
    returns = closes.pct_change().dropna()
    
    # Equal-weighted portfolio daily returns across assets
    portfolio_returns = returns.mean(axis=1)
    
    # Cumulative equity curve starting at 1.0
    equity = (1.0 + portfolio_returns).cumprod()
    # Insert start value of 1.0 at index 0 if not present
    if not equity.empty:
        # Reindex with all dates from closes
        full_idx = closes.index
        equity = equity.reindex(full_idx).ffill()
        equity.iloc[0] = 1.0
        
    return equity

def get_benchmark_curve(data_dict, benchmark_ticker="SPY"):
    if benchmark_ticker in data_dict and not data_dict[benchmark_ticker].empty:
        s = data_dict[benchmark_ticker]['Close'].dropna()
        if not s.empty:
            return s / s.iloc[0]
    return pd.Series(dtype=float)
