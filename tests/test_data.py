import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.data.downloader import download_market_data
from src.data.validator import validate_ohlcv

def test_download_structure():
    """Verify that download_market_data returns correct columns and format."""
    # Using a very small range to keep it fast
    df = download_market_data("SPY", start="2023-01-01", end="2023-01-10")
    
    assert not df.empty
    assert all(col in df.columns for col in ["Open", "High", "Low", "Close", "Volume"])
    assert isinstance(df.index, pd.DatetimeIndex)

def test_validator_valid_data():
    """Test validator with clean data."""
    data = {
        "Open": [100.0, 101.0],
        "High": [105.0, 106.0],
        "Low": [95.0, 96.0],
        "Close": [102.0, 103.0],
        "Volume": [1000, 1100]
    }
    df = pd.DataFrame(data, index=pd.to_datetime(["2023-01-01", "2023-01-02"]))
    is_valid, errors = validate_ohlcv(df)
    assert is_valid
    assert len(errors) == 0

def test_validator_invalid_coherence():
    """Test validator with incoherent prices (High < Low)."""
    data = {
        "Open": [100.0],
        "High": [90.0],  # Incoherent
        "Low": [95.0],
        "Close": [92.0],
        "Volume": [1000]
    }
    df = pd.DataFrame(data, index=pd.to_datetime(["2023-01-01"]))
    is_valid, errors = validate_ohlcv(df)
    assert not is_valid
    assert any("High < Low" in e for e in errors)

def test_validator_missing_columns():
    """Test validator with missing columns."""
    df = pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2023-01-01"]))
    is_valid, errors = validate_ohlcv(df)
    assert not is_valid
    assert any("Missing columns" in e for e in errors)

def test_validator_null_values():
    """Test validator with NaN values."""
    data = {
        "Open": [100.0, np.nan],
        "High": [105.0, 106.0],
        "Low": [95.0, 96.0],
        "Close": [102.0, 103.0],
        "Volume": [1000, 1100]
    }
    df = pd.DataFrame(data, index=pd.to_datetime(["2023-01-01", "2023-01-02"]))
    is_valid, errors = validate_ohlcv(df)
    assert not is_valid
    assert any("contains 1 NaN values" in e for e in errors)
