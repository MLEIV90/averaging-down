import pandas as pd
import json
import os
from src.data.downloader import download_market_data
from src.backtest.engine import run_backtest
from src.backtest.metrics import calculate_metrics

def run():
    assets = ["SPY", "BTC-USD", "GLD"]
    data = {}
    
    for ticker in assets:
        data[ticker] = download_market_data(ticker, start="2020-01-01")
        
    equity = run_backtest(data)
    metrics = calculate_metrics(equity)
    
    print(json.dumps(metrics, indent=2))
    
    os.makedirs('data/processed', exist_ok=True)
    with open('data/processed/backtest_results.json', 'w') as f:
        json.dump(metrics, f, indent=2)

if __name__ == "__main__":
    run()
