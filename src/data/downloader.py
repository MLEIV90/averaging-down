import pandas as pd
import yfinance as yf
from datetime import datetime
from typing import Optional

def resample_btc_to_ny_close(df_1h: pd.DataFrame) -> pd.DataFrame:
    """
    Resamples 1h UTC data to daily EOD candles synchronized with NY close (16:00 EST / 21:00 UTC).
    
    A daily session runs from 21:00 UTC of Day T-1 to 21:00 UTC of Day T.
    To bin this, we shift timestamps by -21 hours, so that:
    - 21:00 UTC on Day T-1 becomes 00:00 UTC on Day T-1.
    - 20:00 UTC on Day T becomes 23:00 UTC on Day T-1.
    All these fall into the same calendar day 'Day T-1' when grouped.
    Then we resample with daily frequency and label/index with Day T.
    """
    if df_1h.empty:
        return df_1h
        
    # Ensure timezone is localized to UTC
    if df_1h.index.tz is None:
        df_1h = df_1h.tz_localize("UTC")
    else:
        df_1h = df_1h.tz_convert("UTC")
        
    # Shift times backward by 21 hours
    shifted_df = df_1h.copy()
    shifted_df.index = shifted_df.index - pd.Timedelta(hours=21)
    
    # Resample using the shifted index
    resampler = shifted_df.resample("D")
    
    resampled_df = pd.DataFrame({
        "Open": resampler["Open"].first(),
        "High": resampler["High"].max(),
        "Low": resampler["Low"].min(),
        "Close": resampler["Close"].last(),
        "Volume": resampler["Volume"].sum()
    })
    
    # Shift the resulting daily index forward by 1 day to represent the end-of-session day
    resampled_df.index = resampled_df.index + pd.Timedelta(days=1)
    
    # Drop any row that doesn't have complete data
    resampled_df = resampled_df.dropna(subset=["Close"])
    
    return resampled_df

def download_market_data(
    symbol: str, 
    start: Optional[str] = None, 
    end: Optional[str] = None, 
    interval: str = "1d",
    resample_btc: bool = False
) -> pd.DataFrame:
    """
    Downloads historical market data from yfinance for a given symbol.
    
    Parameters:
        symbol: The ticker symbol (e.g. 'SPY', 'GLD', 'BTC-USD').
        start: Start date string (YYYY-MM-DD).
        end: End date string (YYYY-MM-DD).
        interval: Data interval (e.g. '1d', '1h').
        resample_btc: If True and symbol is 'BTC-USD', will attempt to download '1h'
                      data and resample it to EOD daily candles ending at 21:00 UTC (16:00 EST).
                      Note: yfinance only provides '1h' data for the last 730 days.
                      If the range is larger or '1h' fails, falls back to standard '1d' data.
    """
    # Force resample_btc to false if the date range is too far back (> 700 days from now)
    if resample_btc and symbol == "BTC-USD":
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d") if start else None
            if start_dt and (datetime.now() - start_dt).days > 700:
                print(f"[Warning] Date range for {symbol} starts more than 700 days ago. "
                      "1h historical data is limited by yfinance. Falling back to standard '1d' EOD.")
                resample_btc = False
        except Exception:
            # If date parsing fails, let the download attempt run
            pass

    # If resample_btc is active and asset is BTC-USD, download 1h data
    if resample_btc and symbol == "BTC-USD":
        print(f"Downloading 1h data for {symbol} to resample with NY close...")
        df = yf.download(symbol, start=start, end=end, interval="1h", auto_adjust=False, progress=False)
        if not df.empty:
            resampled = resample_btc_to_ny_close(df)
            if not resampled.empty:
                return resampled
            else:
                print("[Warning] BTC-USD resampling returned empty. Falling back to '1d'.")
        else:
            print("[Warning] Could not download 1h data for BTC-USD. Falling back to '1d'.")

    # Standard download
    df = yf.download(symbol, start=start, end=end, interval=interval, auto_adjust=False, progress=False)
    
    if df.empty:
        # Fallback to Ticker.history (sometimes handles specific assets better)
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, interval=interval, auto_adjust=False)
        
    if df.empty:
        return pd.DataFrame()
        
    # Standardize MultiIndex columns if present (e.g., if download returns multiple columns per ticker)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    # Clean up column names and index
    df = df.copy()
    
    # Map lowercase columns to capitalized
    cols_to_keep = {}
    for col in df.columns:
        if col.lower() in ["open", "high", "low", "close", "volume"]:
            cols_to_keep[col] = col.capitalize()
            
    df = df[list(cols_to_keep.keys())].rename(columns=cols_to_keep)
    
    # Ensure index is datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
        
    df.index.name = "Timestamp"
    
    # If the index has timezone, strip timezone to make it tz-naive for consistency in raw files
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
        
    return df
