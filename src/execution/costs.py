def estimated_transaction_cost(notional,commission_rate=0.0,slippage_rate=0.0):
    return notional*(commission_rate+slippage_rate)
