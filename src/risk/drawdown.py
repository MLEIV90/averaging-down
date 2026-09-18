def drawdown_multiplier(drawdown):
    if drawdown>=-0.05: return 1.0
    if drawdown>=-0.10: return 0.8
    if drawdown>=-0.20: return 0.5
    return 0.25
