import sys
import json
import pandas as pd
import os
from src.data.downloader import download_market_data
from src.features.indicators import calculate_ema, calculate_atr, calculate_d_atr, calculate_realized_volatility, calculate_rsi
from src.features.regime import detect_market_regime, is_panic
from src.strategy.scale_in import ScaleInEngine
from src.strategy.exits import evaluate_exit

# Add root to sys.path
sys.path.append('.')

def run():
    assets = ["SPY", "BTC-USD", "GLD"]
    signals = []
    
    # Create directory if not exists
    os.makedirs('data/processed', exist_ok=True)
    
    for ticker in assets:
        # Get data
        df = download_market_data(ticker, start="2025-01-01", resample_btc=True)
        if df.empty:
            continue
            
        # Add features
        df['EMA20'] = calculate_ema(df['Close'], 20)
        df['EMA50'] = calculate_ema(df['Close'], 50)
        df['EMA200'] = calculate_ema(df['Close'], 200)
        df['ATR14'] = calculate_atr(df, 14)
        df['D_ATR'] = calculate_d_atr(df['Close'], df['EMA20'], df['ATR14'])
        vol_df = calculate_realized_volatility(df['Close'])
        df = pd.concat([df, vol_df], axis=1)
        df['RSI14'] = calculate_rsi(df['Close'], 14)
        
        regime = detect_market_regime(df)
        panic = is_panic(df)
        
        # Strategy
        engine = ScaleInEngine(ticker.replace('-USD', ''))
        action, state = engine.get_action(df['D_ATR'].iloc[-1], regime, panic)
        
        # Exits
        exit_action, reason = evaluate_exit(ticker, df['Close'].iloc[-1], df['EMA20'].iloc[-1], df['RSI14'].iloc[-1], 0, df['ATR14'].iloc[-1], state)
        
        signals.append({
            "Ticker": ticker,
            "Close": float(df['Close'].iloc[-1]),
            "Regime": regime,
            "D_ATR": float(df['D_ATR'].iloc[-1]),
            "Action": action if action != 'HOLD' else exit_action,
            "Target_Tier": state,
            "Suggested_Alloc_Pct": 0.1,
            "Reason": reason
        })
        
    print(json.dumps(signals, indent=2))
    # Write to file
    with open('data/processed/latest_signals.json', 'w') as f:
        json.dump(signals, f, indent=2)

if __name__ == "__main__":
    run()
