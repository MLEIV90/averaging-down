def volatility_multiplier(target_vol,realized_vol,minimum=0.5,maximum=1.5):
    if realized_vol<=0: return maximum
    return max(minimum,min(maximum,target_vol/realized_vol))
def risk_based_units(risk_budget,stop_distance):
    if risk_budget<=0 or stop_distance<=0: return 0.0
    return risk_budget/stop_distance
