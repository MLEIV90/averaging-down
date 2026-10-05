"""One-at-a-time perturbation definitions."""
from dataclasses import replace
import math
from numbers import Real
from src.strategy.signals import SignalConfig
from src.strategy.exits import ExitConfig
from src.risk.sizing_engine import RiskSizingConfig
from src.strategy.scale_in import ScaleInTier

def apply(parameter, value, signal, risk, exits, tiers):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ValueError("Sensitivity value must be finite.")
    value = float(value)
    if parameter == "signals.rsi2_entry_threshold":
        return replace(signal, rsi2_entry_threshold=value), risk, exits, tiers
    if parameter == "exits.partial_recovery.z_atr_threshold":
        if value <= 0: raise ValueError("Partial recovery Z_ATR threshold must be positive.")
        return signal, risk, replace(exits, z_atr_threshold=value), tiers
    if parameter == "exits.partial_recovery.rsi2_threshold":
        if not 0 <= value <= 100: raise ValueError("RSI2 threshold must be in [0, 100].")
        return signal, risk, replace(exits, rsi2_threshold=value), tiers
    if parameter == "exits.structural_stop.atr_multiple":
        if value <= 0: raise ValueError("ATR multiple must be positive.")
        return signal, risk, replace(exits, stop_atr_multiple=value), tiers
    if parameter == "exits.time_stop.max_cycle_days":
        if value <= 0: raise ValueError("Time-stop days must be positive.")
        return signal, risk, replace(exits, max_cycle_days=value), tiers
    if parameter == "risk.risk_budget_fraction":
        if value < 0: raise ValueError("Risk budget fraction cannot be negative.")
        return signal, replace(risk, risk_budget_fraction=value), exits, tiers
    if parameter.startswith("risk.volatility.target_vol."):
        if value <= 0: raise ValueError("Volatility target must be positive.")
        asset = parameter.rsplit(".",1)[1]
        targets = dict(risk.target_vol_by_asset); targets[asset] = value
        return signal, replace(risk, target_vol_by_asset=tuple(sorted(targets.items()))), exits, tiers
    parts = parameter.split(".")
    if len(parts) == 5 and parts[0] == "strategy" and parts[1] == "scale_in":
        asset, name = parts[2], parts[3]
        current = list(tiers[asset])
        index = {"T1":0,"T2":1,"T3":2}[name]
        old = current[index]
        if value >= 0: raise ValueError("Scale-in Z_ATR thresholds must remain negative.")
        current[index] = ScaleInTier(old.name, value, old.cumulative_weight)
        # The configured tiers must retain their ordering; invalid grid values are rejected.
        if not current[0].z_atr > current[1].z_atr > current[2].z_atr:
            raise ValueError("Perturbation violates ordered tier thresholds.")
        tiers = dict(tiers); tiers[asset] = tuple(current)
        return signal, risk, exits, tiers
    raise ValueError(f"Unsupported sensitivity parameter: {parameter}")
