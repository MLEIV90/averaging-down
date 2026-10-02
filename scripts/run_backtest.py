import sys
import json
import pandas as pd
import os
from pathlib import Path

# Resolución canónica absoluta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.loader import load_local_data
from src.data.downloader import download_market_data
from src.backtest.engine import run_backtest
from src.backtest.metrics import calculate_metrics

def run():
    assets = ["SPY", "BTC-USD", "GLD"]
    data_dict = {}
    
    os.makedirs('data/processed', exist_ok=True)
    
    for ticker in assets:
        df = load_local_data(ticker, folder="raw")
        if df is None or df.empty:
            df = download_market_data(ticker, start="2020-01-01")
        if not df.empty:
            data_dict[ticker] = df
            
    # Ejecutar simulación vectorial
    equity_curve = run_backtest(data_dict)
    
    if equity_curve.empty:
        print("Error: El motor devolvió una curva vacía.")
        return
        
    # Extraer métricas institucionales
    metrics = calculate_metrics(equity_curve)
    
    # Exportar JSON de métricas (manejando tipos seguros)
    safe_metrics = {k: float(v) for k, v in metrics.items()}
    with open('data/processed/backtest_metrics.json', 'w') as f:
        json.dump(safe_metrics, f, indent=2)
        
    # Exportar serie de tiempo para graficado en Streamlit
    equity_curve.to_csv('data/processed/equity_curve.csv', header=['Equity'], index_label='Date')
    
    print("Backtest completado con éxito. Métricas y curva exportadas.")

if __name__ == "__main__":
    run()