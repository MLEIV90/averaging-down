import numpy as np
def total_return(equity_curve): return equity_curve.iloc[-1]/equity_curve.iloc[0]-1
def max_drawdown(equity_curve):
    dd=equity_curve/equity_curve.cummax()-1; return float(dd.min())
def annualized_volatility(returns,periods=252): return float(returns.std()*np.sqrt(periods))
