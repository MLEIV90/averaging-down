import pandas as pd
from typing import Tuple, List

REQUIRED_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}

def validate_ohlcv(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    Validates the integrity of the OHLCV DataFrame.
    
    Checks:
    - Missing columns (Open, High, Low, Close, Volume)
    - Empty DataFrame
    - Null/NaN values in any column
    - Duplicate timestamps
    - Coherence: High >= Low, High >= Open, High >= Close, Low <= Open, Low <= Close
    - Positive prices (Open, High, Low, Close > 0)
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if df is None:
        return False, ["DataFrame is None."]
        
    if df.empty:
        return False, ["DataFrame is empty."]
        
    # Check missing columns
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        errors.append(f"Missing columns: {sorted(missing)}")
        return False, errors  # Stop further validation if columns are missing
        
    # Check null values
    for col in REQUIRED_COLUMNS:
        null_count = df[col].isna().sum()
        if null_count > 0:
            errors.append(f"Column '{col}' contains {null_count} NaN values.")
            
    # Check duplicate timestamps
    if df.index.duplicated().any():
        dup_count = df.index.duplicated().sum()
        errors.append(f"Duplicate timestamps detected: {dup_count} duplicates.")
        
    # Check if index is sorted
    if not df.index.is_monotonic_increasing:
        errors.append("Timestamps are not in chronological order.")
        
    # Coherence checks (row-by-row checks)
    # High >= Low
    bad_high_low = df[df["High"] < df["Low"]]
    if not bad_high_low.empty:
        errors.append(f"Incoherent High/Low: {len(bad_high_low)} rows where High < Low.")
        
    # High >= Open
    bad_high_open = df[df["High"] < df["Open"]]
    if not bad_high_open.empty:
        errors.append(f"Incoherent High/Open: {len(bad_high_open)} rows where High < Open.")
        
    # High >= Close
    bad_high_close = df[df["High"] < df["Close"]]
    if not bad_high_close.empty:
        errors.append(f"Incoherent High/Close: {len(bad_high_close)} rows where High < Close.")
        
    # Low <= Open
    bad_low_open = df[df["Low"] > df["Open"]]
    if not bad_low_open.empty:
        errors.append(f"Incoherent Low/Open: {len(bad_low_open)} rows where Low > Open.")
        
    # Low <= Close
    bad_low_close = df[df["Low"] > df["Close"]]
    if not bad_low_close.empty:
        errors.append(f"Incoherent Low/Close: {len(bad_low_close)} rows where Low > Close.")
        
    # Prices > 0
    for col in ["Open", "High", "Low", "Close"]:
        non_positive = df[df[col] <= 0]
        if not non_positive.empty:
            errors.append(f"Non-positive prices in '{col}': {len(non_positive)} rows where price <= 0.")
            
    return len(errors) == 0, errors
