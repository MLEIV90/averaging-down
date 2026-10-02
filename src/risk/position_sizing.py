import pandas as pd

def volatility_multiplier(target_vol, realized_vol):
    """Calcula el multiplicador basado en la relación entre volatilidad objetivo y realizada."""
    if pd.isna(realized_vol) or realized_vol <= 0:
        return 1.0
    scaling_factor = target_vol / realized_vol
    return max(0.5, min(1.5, scaling_factor))

def risk_based_units(capital, risk_per_unit):
    if risk_per_unit <= 0:
        return 0
    return capital / risk_per_unit

def calculate_position_size(target_vol, realized_vol, base_capital, max_risk_pct):
    multiplier = volatility_multiplier(target_vol, realized_vol)
    return base_capital * max_risk_pct * multiplier

def get_dynamic_allocation(base_pct, target_vol, realized_vol):
    """Devuelve el % de asignación dinámico para el Tier actual, acotado por la volatilidad."""
    multiplier = volatility_multiplier(target_vol, realized_vol)
    return round(base_pct * multiplier, 4)