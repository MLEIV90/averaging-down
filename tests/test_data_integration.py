import pandas as pd
import pytest

from src.data.downloader import download_market_data


pytestmark = pytest.mark.integration


def test_download_structure_from_yahoo_finance():
    df = download_market_data("SPY", start="2023-01-03", end="2023-01-10")
    assert not df.empty
    assert all(col in df.columns for col in ["Open", "High", "Low", "Close", "Volume"])
    assert isinstance(df.index, pd.DatetimeIndex)
