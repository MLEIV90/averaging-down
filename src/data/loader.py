from pathlib import Path
from typing import Optional

import pandas as pd

from .config import REPOSITORY_ROOT
from .engine import DataEngine, MissingLocalDataError
from .store import DataStore


def get_data_path(asset: str, folder: str = "raw", extension: str = "parquet") -> Path:
    """Return a repository-root-relative path without creating directories."""
    return REPOSITORY_ROOT / "data" / folder / f"{asset}.{extension}"


def save_local_data(df: pd.DataFrame, asset: str, folder: str = "raw") -> str:
    """Compatibility helper for storing an unmodified local source frame."""
    if df is None or df.empty:
        raise ValueError("Refusing to persist an empty dataset.")
    if folder != "raw":
        raise ValueError("save_local_data stores source data only; normalized data is written by DataEngine.")
    return str(DataStore().save_raw(asset, df))


def load_local_data(asset: str, folder: str = "raw") -> Optional[pd.DataFrame]:
    """Compatibility loader that routes source data through normalization and validation."""
    engine = DataEngine()
    try:
        if folder == "raw":
            return engine.load_or_download(asset, allow_download=False)
        return engine.load(asset, interval=folder)
    except MissingLocalDataError:
        return None
