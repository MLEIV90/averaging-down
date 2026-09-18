import pandas as pd
import os
from pathlib import Path
from typing import Optional

def get_data_path(asset: str, folder: str = "raw", extension: str = "parquet") -> Path:
    """Returns the path for a given asset data file."""
    base_dir = Path("data") / folder
    os.makedirs(base_dir, exist_ok=True)
    return base_dir / f"{asset}.{extension}"

def save_local_data(df: pd.DataFrame, asset: str, folder: str = "raw") -> str:
    """
    Saves a DataFrame to a local parquet file. 
    If parquet fails, falls back to CSV.
    """
    if df.empty:
        return ""
        
    path = get_data_path(asset, folder, "parquet")
    try:
        df.to_parquet(path)
        return str(path)
    except Exception as e:
        print(f"[Error] Failed to save {asset} to parquet: {e}. Falling back to CSV.")
        path_csv = get_data_path(asset, folder, "csv")
        df.to_csv(path_csv)
        return str(path_csv)

def load_local_data(asset: str, folder: str = "raw") -> Optional[pd.DataFrame]:
    """
    Loads an asset's data from local parquet (preferred) or CSV.
    """
    path_parquet = get_data_path(asset, folder, "parquet")
    path_csv = get_data_path(asset, folder, "csv")
    
    if path_parquet.exists():
        return pd.read_parquet(path_parquet)
    elif path_csv.exists():
        return pd.read_csv(path_csv, index_col=0, parse_dates=True)
    
    return None
