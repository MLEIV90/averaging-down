import sys
from pathlib import Path
import json
import pandas as pd
import os

# Resolución canónica de rutas
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.loader import load_local_data
from src.data.downloader import download_market_data
from src.features.indicators import calculate_ema, calculate_atr, calculate_d_atr, calculate_realized_volatility, calculate_rsi
from src.features.regime import detect_market_regime, is_panic
from src.strategy.scale_in import ScaleInEngine
from src.strategy.exits import evaluate_exit
from src.risk.position_sizing import get_dynamic_allocation

def run():
    assets = ["SPY", "BTC-USD", "GLD"]
    signals = []
    
    # Cargar estado persistente del portfolio
    state_file = Path('data/processed/portfolio_state.json')
    portfolio_state = {}
    if state_file.exists():
        with open(state_file, 'r') as f:
            portfolio_state = json.load(f)
            
    os.makedirs('data/processed', exist_ok=True)
    
    for ticker in assets:
        df = load_local_data(ticker, folder="raw")
        if df is None or df.empty:
            df = download_market_data(ticker, start="2020-01-01")
        if df.empty:
            continue
            
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
        
        # Recuperar variables de estado
        asset_state = portfolio_state.get(ticker, {})
        current_tier = asset_state.get("Target_Tier", "FLAT")
        last_z = asset_state.get("Last_Z_ATR", 0.0)
        avg_price = asset_state.get("Avg_Buy_Price", 0.0)
        
        # Inicializar motor con persistencia
        engine = ScaleInEngine(ticker.replace('-USD', ''), initial_state=current_tier, last_z_atr=last_z)
        
        last_close = float(df['Close'].iloc[-1])
        last_d_atr = float(df['D_ATR'].iloc[-1])
        last_ema20 = float(df['EMA20'].iloc[-1])
        
        # Obtener volatilidad realizada para el risk sizing
        vol_cols = [c for c in df.columns if 'Vol' in c or 'volatility' in c.lower()]
        realized_vol = float(df[vol_cols[0]].iloc[-1]) if vol_cols else 0.15
        
        action, new_state = engine.get_action(last_d_atr, regime, panic)
        exit_action, reason = evaluate_exit(ticker, last_close, last_ema20, float(df['RSI14'].iloc[-1]), avg_price, float(df['ATR14'].iloc[-1]), new_state)
        
        final_action = action if action != 'HOLD' else exit_action
        
        if final_action == 'FULL_RESET':
            new_state = 'FLAT'
            engine.last_z_atr = 0.0
            avg_price = 0.0
            
        # Target Volatility del 15%. Base T1=10%, T2=15%, T3=20%
        base_pct = 0.10 if 'T1' in final_action else (0.15 if 'T2' in final_action else (0.20 if 'T3' in final_action else 0.0))
        alloc_pct = get_dynamic_allocation(base_pct, 0.15, realized_vol) if base_pct > 0 else 0.0
        
        signals.append({
            "Ticker": ticker,
            "Close": last_close,
            "Regime": regime,
            "D_ATR": last_d_atr,
            "Action": final_action,
            "Target_Tier": new_state,
            "Suggested_Alloc_Pct": alloc_pct,
            "Reason": reason if final_action != 'HOLD' and 'BUY' not in final_action else ("TIER_ENTRY" if 'BUY' in final_action else "NONE")
        })
        
        portfolio_state[ticker] = {
            "Target_Tier": new_state,
            "Last_Z_ATR": float(engine.last_z_atr),
            "Avg_Buy_Price": last_close if 'BUY' in final_action and avg_price == 0 else avg_price,
            "Regime": regime,
            "Close": last_close,
            "Action": final_action,
            "Realized_Vol": realized_vol
        }
        
    print(json.dumps(signals, indent=2))
    
    with open('data/processed/latest_signals.json', 'w') as f:
        json.dump(signals, f, indent=2)
        
    with open('data/processed/portfolio_state.json', 'w') as f:
        json.dump(portfolio_state, f, indent=2)

if __name__ == "__main__":
    run()