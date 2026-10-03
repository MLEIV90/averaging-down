import pandas as pd
import numpy as np
from src.features.config import FeatureConfig, load_feature_config

def run_backtest(data_dict, feature_config: FeatureConfig | None = None):
    """
    Simulación histórica vectorial avanzada. Reproduce los pesos de la máquina 
    de estados (Scale-in Tiers y De-risking) para el portfolio completo.
    """
    feature_config = feature_config or load_feature_config()
    if not data_dict or 'SPY' not in data_dict:
        return pd.Series(dtype=float)
        
    closes = pd.DataFrame({t: df['Close'] for t, df in data_dict.items() if not df.empty}).dropna()
    if closes.empty:
        return pd.Series(dtype=float)
        
    returns = closes.pct_change().dropna()
    weights = pd.DataFrame(index=returns.index, columns=returns.columns).fillna(0.0)
    
    for ticker in returns.columns:
        df = data_dict[ticker].reindex(returns.index)
        ema20 = df[f'ema{feature_config.ema_fast}']
        ema200 = df[f'ema{feature_config.ema_slow}']
        
        # Proxy del estado vectorial:
        bull_regime = df['Close'] > ema200
        tier1 = df['Close'] < ema20
        tier2 = df['Close'] < (ema20 * 0.96) # Caída adicional
        tier3 = df['Close'] < (ema20 * 0.92) # Caída profunda
        
        # Asignación teórica de pesos por Tiers
        w = np.where(bull_regime, 0.1, 0.0) 
        w = np.where(bull_regime & tier1, 0.2, w)
        w = np.where(bull_regime & tier2, 0.35, w)
        w = np.where(bull_regime & tier3, 0.5, w)
        
        # De-risk estructural: venta al recuperar la EMA20
        w = np.where(df['Close'] > ema20, 0.1, w)
        
        weights[ticker] = w
        
    # Normalización del apalancamiento bruto al 100%
    total_weight = weights.sum(axis=1)
    weights = weights.div(total_weight.replace(0, 1), axis=0) * np.minimum(total_weight, 1.0)
    
    # Capitalización del equity
    portfolio_returns = (returns * weights.shift(1)).sum(axis=1)
    equity = (1.0 + portfolio_returns).cumprod()
    
    full_idx = closes.index
    equity = equity.reindex(full_idx).ffill()
    if not equity.empty:
        equity.iloc[0] = 1.0
        
    return equity

def get_benchmark_curve(data_dict, benchmark_ticker="SPY"):
    if benchmark_ticker in data_dict and not data_dict[benchmark_ticker].empty:
        s = data_dict[benchmark_ticker]['Close'].dropna()
        if not s.empty:
            return s / s.iloc[0]
    return pd.Series(dtype=float)
