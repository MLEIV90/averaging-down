import sys
import os
from datetime import datetime
from src.data.downloader import download_market_data
from src.data.loader import save_local_data

# Add root to sys.path
sys.path.append('.')

def run():
    assets = ["SPY", "BTC-USD", "GLD"]
    start_date = "2020-01-01"
    end_date = datetime.today().strftime('%Y-%m-%d')
    
    os.makedirs('data/raw', exist_ok=True)
    
    for ticker in assets:
        print(f"Downloading historical data for {ticker} from {start_date} to {end_date}...")
        df = download_market_data(ticker, start=start_date, end=end_date, resample_btc=True)
        if not df.empty:
            path = save_local_data(df, ticker, folder="raw")
            print(f"Successfully saved {ticker} to {path} ({len(df)} rows)")
        else:
            print(f"[Error] Failed to download data for {ticker}")

if __name__ == "__main__":
    run()
