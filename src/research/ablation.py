"""One-component ablation definitions."""
from dataclasses import replace
from src.strategy.signals import SignalConfig
from src.strategy.exits import ExitConfig
from src.risk.sizing_engine import RiskSizingConfig
from src.portfolio.engine import PortfolioConfig

SUPPORTED = frozenset({"regime_filter","rsi2_filter","reversal_confirmation","scale_in",
                       "volatility_sizing","portfolio_constraints","partial_recovery_exit",
                       "time_stop","structural_stop"})

def overrides(component, signal, risk, portfolio, exits):
    if component == "regime_filter": return {"signal": replace(signal, regime_filter_enabled=False),
                                               "regime_filter_enabled": False}
    if component == "rsi2_filter": return {"signal": replace(signal, rsi_filter_enabled=False)}
    if component == "reversal_confirmation": return {"signal": replace(signal, reversal_confirmation_enabled=False)}
    if component == "scale_in": return {"disable_additional_entries": True}
    if component == "volatility_sizing": return {"risk": replace(risk, volatility_enabled=False)}
    if component == "portfolio_constraints":
        return {"portfolio": replace(portfolio, max_gross_exposure=1.0, minimum_cash_reserve=0.0,
                    max_asset_weight=tuple((a,1.0) for a,_ in portfolio.max_asset_weight))}
    if component == "partial_recovery_exit": return {"exits": replace(exits, partial_recovery_enabled=False)}
    if component == "time_stop": return {"exits": replace(exits, time_stop_enabled=False)}
    if component == "structural_stop": return {"exits": replace(exits, structural_stop_enabled=False)}
    return None
