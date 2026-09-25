def volatility_multiplier(target_vol, realized_vol):
    """
    Calcula el multiplicador basado en la relación entre volatilidad objetivo y realizada.
    Acotado entre 0.5x y 1.5x.
    """
    if realized_vol <= 0:
        return 1.0
    scaling_factor = target_vol / realized_vol
    return max(0.5, min(1.5, scaling_factor))

def risk_based_units(capital, risk_per_unit):
    """
    Calcula unidades basadas en el riesgo total disponible por unidad de riesgo.
    """
    if risk_per_unit <= 0:
        return 0
    return capital / risk_per_unit

def calculate_position_size(target_vol, realized_vol, base_capital, max_risk_pct):
    """
    Ajusta el tamaño de posición inversamente a la volatilidad, acotado entre 0.5x y 1.5x.
    """
    multiplier = volatility_multiplier(target_vol, realized_vol)
    return base_capital * max_risk_pct * multiplier
