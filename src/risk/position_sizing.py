def calculate_position_size(target_vol, realized_vol, base_capital, max_risk_pct):
    """
    Ajusta el tamaño de posición inversamente a la volatilidad, acotado entre 0.5x y 1.5x.
    """
    if realized_vol <= 0:
        return base_capital * max_risk_pct
        
    # Volatility scaling factor
    scaling_factor = target_vol / realized_vol
    
    # Clip multiplier between 0.5 and 1.5
    multiplier = max(0.5, min(1.5, scaling_factor))
    
    return base_capital * max_risk_pct * multiplier
