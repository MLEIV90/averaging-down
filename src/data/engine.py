from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .config import AssetDataConfig, load_assets_config
from .downloader import DownloadResult, MarketDataDownloader, resample_btc_to_ny_close
from .gaps import detect_gaps
from .normalization import InvalidMarketData, SCHEMA_VERSION, normalize_and_validate
from .store import DataStore
from .validator import DataValidator, Severity, ValidationReport


class MissingLocalDataError(FileNotFoundError):
    pass


class DataWarningsRejected(ValueError):
    pass


class DataEngine:
    """Central acquisition, validation, normalization, storage and load API."""

    def __init__(
        self,
        store: DataStore | None = None,
        downloader: MarketDataDownloader | None = None,
        config_path=None,
        allow_warnings: bool = True,
    ):
        self.store = store or DataStore()
        self.downloader = downloader or MarketDataDownloader()
        self.config_path = config_path
        self.allow_warnings = allow_warnings

    def _config(self, ticker: str) -> tuple[AssetDataConfig, dict[str, Any]]:
        assets, defaults = load_assets_config(self.config_path) if self.config_path else load_assets_config()
        try:
            return assets[ticker], defaults
        except KeyError as exc:
            raise ValueError(f"Asset {ticker!r} is not configured.") from exc

    @staticmethod
    def _metadata(
        ticker: str,
        config: AssetDataConfig,
        frame: pd.DataFrame,
        *,
        source: str,
        source_interval: str,
        downloaded_at_utc: str | None,
        adjusted: bool | None,
        gaps,
        start_requested: str | None,
        end_requested: str | None,
    ) -> dict[str, Any]:
        return {
            "asset": ticker,
            "ticker": ticker,
            "source": source,
            "frequency": config.interval,
            "source_frequency": source_interval,
            "start": frame.index[0].isoformat() if not frame.empty else None,
            "end": frame.index[-1].isoformat() if not frame.empty else None,
            "requested_start": start_requested,
            "requested_end_exclusive": end_requested,
            "download_timestamp_utc": downloaded_at_utc,
            "timezone_convention": "UTC-aware DatetimeIndex; daily timestamps label the session date at 00:00 UTC",
            "market_timezone": config.market_timezone,
            "daily_close_utc": None,
            "daily_close_utc_applied": None,
            "adjusted": adjusted,
            "row_count": int(len(frame)),
            "schema_version": SCHEMA_VERSION,
            "schema": {column: str(dtype) for column, dtype in frame.dtypes.items()},
            "gap_reports": [
                {"start": gap.start.isoformat(), "end": gap.end.isoformat(),
                 "classification": gap.classification, "severity": gap.severity.value,
                 "message": gap.message}
                for gap in gaps
            ],
            "overlap_policy": "newly downloaded bar replaces existing bar at the same timestamp",
        }

    def _persist_download(
        self,
        ticker: str,
        config: AssetDataConfig,
        result: DownloadResult,
        *,
        start: str | None,
        end: str | None,
        replace_existing: bool = False,
    ) -> pd.DataFrame:
        self._validate_raw_timestamps(result.raw, "new provider response")
        incoming = normalize_and_validate(result.bars, config)
        previous = self.store.load_normalized(ticker, config.interval)
        if previous is not None and not replace_existing:
            old_frame, _ = previous
            prior_report = DataValidator().validate(old_frame)
            if not prior_report.is_valid:
                raise InvalidMarketData(prior_report)
            # New observations deliberately win on overlapping dates so provider
            # corrections can be incorporated without retaining duplicate index rows.
            combined = pd.concat([old_frame.loc[~old_frame.index.isin(incoming.index)], incoming]).sort_index()
            report = DataValidator().validate(combined)
            if not report.is_valid:
                raise InvalidMarketData(report)
        else:
            combined = incoming

        try:
            existing_raw = self.store.load_raw(ticker)
        except Exception:
            # Do not silently replace an unreadable cache: its user must decide how
            # to recover the existing local source data.
            raise
        if existing_raw is not None:
            self._validate_raw_timestamps(existing_raw, f"cached raw data for {ticker}")
        prior_raw_metadata = self.store.load_raw_metadata(ticker)
        raw_frequency_matches = prior_raw_metadata.get("frequency") == result.source_interval
        if replace_existing or existing_raw is None or not raw_frequency_matches:
            raw_combined = result.raw
        else:
            raw_combined = pd.concat([existing_raw.loc[~existing_raw.index.isin(result.raw.index)], result.raw]).sort_index()

        gaps = detect_gaps(combined, config, expected_start=start, expected_end=end)
        warning_gaps = [gap for gap in gaps if gap.severity.value == "WARNING"]
        if warning_gaps and not self.allow_warnings:
            raise DataWarningsRejected("Data gaps produced warnings and the caller configured strict warning handling.")
        metadata = self._metadata(
            ticker, config, combined, source="Yahoo Finance (yfinance)",
            source_interval=result.source_interval,
            downloaded_at_utc=result.downloaded_at_utc, adjusted=result.adjusted,
            gaps=gaps, start_requested=start, end_requested=end,
        )
        metadata["daily_close_utc"] = result.daily_close_utc
        metadata["daily_close_utc_applied"] = result.daily_close_utc
        metadata["replaced_unknown_provenance"] = replace_existing
        self.store.save_raw(ticker, raw_combined)
        self.store.save_raw_metadata(ticker, {
            "asset": ticker,
            "ticker": ticker,
            "source": "Yahoo Finance (yfinance)",
            "frequency": result.source_interval,
            "start": raw_combined.index[0].isoformat(),
            "end": raw_combined.index[-1].isoformat(),
            "download_timestamp_utc": result.downloaded_at_utc,
            "timezone_convention": "provider response preserved before normalization",
            "adjusted": result.adjusted,
            "daily_close_utc": result.daily_close_utc,
            "row_count": int(len(raw_combined)),
            "schema_version": "raw-provider",
            "schema": {column: str(dtype) for column, dtype in raw_combined.dtypes.items()},
        })
        self.store.save_normalized(ticker, combined, metadata, config.interval)
        return combined

    @staticmethod
    def _validate_raw_timestamps(frame: pd.DataFrame, label: str) -> None:
        report = ValidationReport()
        if not isinstance(frame.index, pd.DatetimeIndex):
            report.add(Severity.ERROR, "invalid_raw_index", f"{label} must have a DatetimeIndex.")
        else:
            if not frame.index.is_monotonic_increasing:
                report.add(Severity.ERROR, "unordered_raw_timestamps", f"{label} timestamps must be ascending.")
            if frame.index.has_duplicates:
                report.add(Severity.ERROR, "duplicate_raw_timestamps", f"{label} timestamps must be unique.")
        if not report.is_valid:
            raise InvalidMarketData(report)

    def update(
        self,
        ticker: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Initial download or incremental update; latest downloaded overlap wins."""
        config, defaults = self._config(ticker)
        explicit_start = start is not None
        existing = self.store.load_normalized(ticker, config.interval)
        if existing is None and self.store.load_legacy_raw(ticker) is not None:
            self.load_or_download(ticker, allow_download=False)
            existing = self.store.load_normalized(ticker, config.interval)

        replace_existing = False
        request_interval = config.source_interval
        request_cutoff = config.resample_cutoff_utc
        if existing is not None:
            _, existing_metadata = existing
            if str(existing_metadata.get("source", "")).startswith("legacy local"):
                if explicit_start:
                    first_date = existing[0].index[0].date().isoformat()
                    if start > first_date:
                        raise ValueError(
                            f"Legacy {ticker} data has unknown provenance. For a consistent refresh, start at or before {first_date}."
                        )
                replace_existing = True
                start = start or config.default_start or defaults.get("start")
                if not start:
                    raise ValueError(f"Cannot rebuild {ticker}: provenance is unknown and no full-history start is configured.")
            else:
                previous_cutoff = existing_metadata.get("daily_close_utc_applied")
                previous_source_interval = existing_metadata.get("source_frequency")
                if config.resample_cutoff_utc and not previous_cutoff and previous_source_interval == "1d":
                    # Preserve the existing provider-daily convention after yfinance's
                    # hourly-history cutoff; do not mix provider daily bars with hourly aggregates.
                    request_interval = "1d"
                    request_cutoff = None
                elif previous_cutoff:
                    request_cutoff = config.resample_cutoff_utc
                    request_interval = config.source_interval
        if existing is not None and start is None:
            last = existing[0].index[-1]
            last_session_date = last.tz_convert("UTC").date()
            # NY-close BTC bars span the preceding 21:00 UTC hour boundary;
            # re-fetch a two-day overlap so the first revised aggregate is complete.
            overlap_days = 2 if request_cutoff else 0
            next_date = last_session_date + pd.Timedelta(days=1 - overlap_days)
            start = next_date.isoformat()
        if start is None:
            start = config.default_start or defaults.get("start")
        if not start:
            raise ValueError(f"No start date supplied and no default configured for {ticker}.")
        if end is None:
            end = datetime.now(timezone.utc).date().isoformat()
        result = self.downloader.download(
            ticker,
            start=start,
            end=end,
            interval=request_interval,
            adjusted=config.adjusted,
            resample_cutoff_utc=request_cutoff,
        )
        return self._persist_download(
            ticker, config, result, start=start, end=end, replace_existing=replace_existing
        )

    def load(self, ticker: str, *, interval: str = "1d") -> pd.DataFrame:
        loaded = self.store.load_normalized(ticker, interval)
        if loaded is None:
            raise MissingLocalDataError(f"No validated local data found for {ticker} ({interval}).")
        frame, metadata = loaded
        report = DataValidator().validate(frame)
        if not report.is_valid:
            raise InvalidMarketData(report)
        if not self.allow_warnings and any(item.get("severity") == "WARNING" for item in metadata.get("gap_reports", [])):
            raise DataWarningsRejected(f"Cached data for {ticker} contains gap warnings.")
        required_provenance = {"asset", "source", "frequency", "row_count", "schema_version"}
        if not required_provenance.issubset(metadata):
            raise ValueError(f"Cached data for {ticker} is missing required provenance metadata.")
        if metadata.get("row_count") not in (None, len(frame)):
            raise ValueError(f"Metadata row_count does not match cached data for {ticker}.")
        return frame

    def load_or_download(self, ticker: str, *, allow_download: bool = True) -> pd.DataFrame:
        try:
            return self.load(ticker)
        except MissingLocalDataError:
            pass
        config, _ = self._config(ticker)
        legacy = self.store.load_legacy_raw(ticker)
        if legacy is not None:
            raw_metadata = self.store.load_raw_metadata(ticker)
            raw_frequency = raw_metadata.get("frequency", "unknown")
            applied_cutoff = raw_metadata.get("daily_close_utc")
            source_bars = legacy
            if raw_frequency == "1h" and applied_cutoff:
                source_bars = resample_btc_to_ny_close(legacy, applied_cutoff)
            normalized = normalize_and_validate(source_bars, config)
            gaps = detect_gaps(normalized, config)
            warning_gaps = [gap for gap in gaps if gap.severity.value == "WARNING"]
            if warning_gaps and not self.allow_warnings:
                raise DataWarningsRejected("Legacy dataset has gap warnings and caller configured strict warning handling.")
            metadata = self._metadata(
                ticker, config, normalized,
                source=raw_metadata.get("source", "legacy local Parquet (original provenance unavailable)"),
                source_interval=raw_frequency, downloaded_at_utc=raw_metadata.get("download_timestamp_utc"),
                adjusted=raw_metadata.get("adjusted"), gaps=gaps,
                start_requested=None, end_requested=None,
            )
            metadata["daily_close_utc"] = applied_cutoff
            metadata["daily_close_utc_applied"] = applied_cutoff
            self.store.save_normalized(ticker, normalized, metadata, config.interval)
            if not raw_metadata:
                self.store.save_raw_metadata(ticker, {
                    "asset": ticker,
                    "ticker": ticker,
                    "source": "legacy local Parquet (original provenance unavailable)",
                    "frequency": "unknown",
                    "start": legacy.index[0].isoformat(),
                    "end": legacy.index[-1].isoformat(),
                    "download_timestamp_utc": None,
                    "timezone_convention": "inferred while migrating legacy local data",
                    "adjusted": None,
                    "row_count": int(len(legacy)),
                    "schema_version": "legacy-provider",
                    "schema": {column: str(dtype) for column, dtype in legacy.dtypes.items()},
                })
            return normalized
        if not allow_download:
            raise MissingLocalDataError(f"No local raw or validated data found for {ticker}.")
        return self.update(ticker)


def load_market_data(ticker: str, *, allow_download: bool = False) -> pd.DataFrame:
    """Shared public loader. UI defaults to local-only; scripts may opt into download."""
    return DataEngine().load_or_download(ticker, allow_download=allow_download)
