import pandas as pd
import json
import os
from src.data.loader import load_local_data
from src.data.downloader import download_market_data
from src.backtest.engine import run_backtest, get_benchmark_curve
from src.backtest.metrics import calculate_metrics

def run():
    assets = ["SPY", "BTC-USD", "GLD"]
    data = {}
    
    for ticker in assets:
        df = load_local_data(ticker, folder="raw")
        if df is None or df.empty:
            df = download_market_data(ticker, start="2020-01-01")
        data[ticker] = df
        
    equity = run_backtest(data)
    benchmark = get_benchmark_curve(data, "SPY")
    metrics = calculate_metrics(equity)
    
    # Prepare JSON structure containing metrics, equity curve, and benchmark curve
    result_payload = {
        "metrics": metrics,
        "equity_curve": {str(ts.strftime('%Y-%m-%d')): float(val) for ts, val in equity.items()},
        "benchmark_curve": {str(ts.strftime('%Y-%m-%d')): float(val) for ts, val in benchmark.items()}
    }
    
    print(json.dumps(metrics, indent=2))
    
    os.makedirs('data/processed', exist_ok=True)
    with open('data/processed/backtest_results.json', 'w') as f:
        json.dump(result_payload, f, indent=2)
        
    print("Backtest results successfully generated and saved to data/processed/backtest_results.json")

if __name__ == "__main__":
    run()
