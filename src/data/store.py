import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from .config import REPOSITORY_ROOT


class DataStoreError(OSError):
    pass


class DataStore:
    def __init__(self, root: str | Path = REPOSITORY_ROOT):
        self.root = Path(root).resolve()

    def raw_path(self, ticker: str) -> Path:
        return self.root / "data" / "raw" / f"{ticker}.parquet"

    def normalized_path(self, ticker: str, interval: str = "1d") -> Path:
        return self.root / "data" / "processed" / f"{ticker}_{interval}.parquet"

    def metadata_path(self, ticker: str, interval: str = "1d") -> Path:
        return self.root / "data" / "processed" / f"{ticker}_{interval}.metadata.json"

    def raw_metadata_path(self, ticker: str) -> Path:
        return self.root / "data" / "raw" / f"{ticker}.metadata.json"

    def legacy_raw_path(self, ticker: str) -> Path:
        return self.raw_path(ticker)

    @staticmethod
    def _atomic_replace(path: Path, writer) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix=f".{path.stem}.", suffix=path.suffix, dir=path.parent, delete=False) as temp:
                temp_path = Path(temp.name)
            writer(temp_path)
            os.replace(temp_path, path)
        except Exception as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise DataStoreError(f"Failed to persist {path}: {exc}") from exc

    def save_raw(self, ticker: str, raw: pd.DataFrame) -> Path:
        path = self.raw_path(ticker)
        self._atomic_replace(path, raw.to_parquet)
        return path

    def save_raw_metadata(self, ticker: str, metadata: dict[str, Any]) -> Path:
        path = self.raw_metadata_path(ticker)
        self._atomic_replace(path, lambda temp: temp.write_text(
            json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
        ))
        return path

    def load_raw_metadata(self, ticker: str) -> dict[str, Any]:
        path = self.raw_metadata_path(ticker)
        if not path.exists():
            return {}
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise DataStoreError(f"Could not read raw provenance {path}: {exc}") from exc
        if not isinstance(metadata, dict):
            raise DataStoreError(f"Raw provenance {path} is not a JSON object.")
        return metadata

    def load_raw(self, ticker: str) -> pd.DataFrame | None:
        path = self.raw_path(ticker)
        if not path.exists():
            return None
        try:
            return pd.read_parquet(path)
        except Exception as exc:
            raise DataStoreError(f"Could not read raw data {path}: {exc}") from exc

    def save_normalized(
        self,
        ticker: str,
        frame: pd.DataFrame,
        metadata: dict[str, Any],
        interval: str = "1d",
    ) -> tuple[Path, Path]:
        data_path = self.normalized_path(ticker, interval)
        meta_path = self.metadata_path(ticker, interval)
        self._atomic_replace(data_path, frame.to_parquet)
        self._atomic_replace(meta_path, lambda path: path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
        ))
        return data_path, meta_path

    def load_normalized(self, ticker: str, interval: str = "1d") -> tuple[pd.DataFrame, dict[str, Any]] | None:
        data_path = self.normalized_path(ticker, interval)
        meta_path = self.metadata_path(ticker, interval)
        if not data_path.exists() or not meta_path.exists():
            return None
        try:
            frame = pd.read_parquet(data_path)
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise DataStoreError(f"Could not read normalized data for {ticker}: {exc}") from exc
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise DataStoreError(f"Normalized data for {ticker} has no DatetimeIndex.")
        if frame.index.tz is None:
            raise DataStoreError(f"Normalized data for {ticker} has a timezone-naive index.")
        if not isinstance(metadata, dict):
            raise DataStoreError(f"Normalized provenance for {ticker} is not a JSON object.")
        return frame, metadata

    def load_legacy_raw(self, ticker: str) -> pd.DataFrame | None:
        path = self.legacy_raw_path(ticker)
        if not path.exists():
            return None
        try:
            return pd.read_parquet(path)
        except Exception as exc:
            raise DataStoreError(f"Could not read existing raw dataset {path}: {exc}") from exc
