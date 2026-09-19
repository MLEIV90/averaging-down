def evaluate_exit(ticker, close, ema20, rsi14, avg_buy_price, atr14, current_state):
    # Structural Stop
    k = 4.5 if 'BTC' in ticker else 3.0
    if avg_buy_price and close < (avg_buy_price - k * atr14):
        return 'FULL_RESET', 'STRUCTURAL_STOP'
    
    # De-risking
    if current_state in ['T1_ACTIVE', 'T2_ACTIVE', 'T3_ACTIVE']:
        if close > ema20 or rsi14 > 60:
            return 'PARTIAL_DE_RISK', 'RECOVERED_EMA_OR_RSI'
            
    # Full reset from De-Risk
    if current_state == 'DE_RISK' and close > ema20:
        return 'FULL_RESET', 'FULL_RECOVERY'
        
    return 'HOLD', 'NONE'
