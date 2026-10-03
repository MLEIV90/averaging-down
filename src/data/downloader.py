from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import yfinance as yf


class DataDownloadError(RuntimeError):
    """The external provider could not be reached or returned an invalid response."""


class NetworkDataDownloadError(DataDownloadError):
    """The request failed before receiving a usable provider response."""


class InvalidProviderResponseError(DataDownloadError):
    """The provider returned no rows or an unusable response shape."""


class NoMarketDataError(InvalidProviderResponseError):
    """The provider returned no rows for a syntactically valid request."""


class InvalidDataRequestError(ValueError):
    """A requested date range or frequency is malformed."""


@dataclass(frozen=True)
class DownloadResult:
    raw: pd.DataFrame
    bars: pd.DataFrame
    source_interval: str
    downloaded_at_utc: str
    adjusted: bool
    daily_close_utc: str | None


def _field_level(columns: pd.Index) -> int | None:
    if not isinstance(columns, pd.MultiIndex):
        return None
    expected = {"open", "high", "low", "close", "volume"}
    for level in range(columns.nlevels):
        if expected.issubset({str(value).lower() for value in columns.get_level_values(level)}):
            return level
    return None


def _select_provider_asset(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        level = _field_level(result.columns)
        if level is None:
            raise InvalidProviderResponseError("Yahoo Finance response has an unrecognized MultiIndex schema.")
        result.columns = result.columns.get_level_values(level)
    return result


def resample_btc_to_ny_close(df_1h: pd.DataFrame, close_utc: str = "21:00") -> pd.DataFrame:
    """Group hourly UTC bars to the existing configurable BTC session date.

    The current repository convention is 21:00 UTC (16:00 EST). The resulting
    midnight UTC timestamp is a session-date label, not an execution instant.
    """
    if df_1h.empty:
        return df_1h.copy()
    frame = _select_provider_asset(df_1h)
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise InvalidProviderResponseError("Hourly provider data must have a DatetimeIndex.")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise InvalidProviderResponseError("Hourly provider timestamps must be ascending and unique before resampling.")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    else:
        frame.index = frame.index.tz_convert("UTC")
    try:
        hour, minute = (int(part) for part in close_utc.split(":", maxsplit=1))
        cutoff = pd.Timedelta(hours=hour, minutes=minute)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid UTC daily close time: {close_utc!r}.") from exc
    shifted = frame.copy()
    shifted.index = shifted.index - cutoff
    daily = shifted.resample("D").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
    })
    daily.index = (daily.index + pd.Timedelta(days=1)).tz_convert("UTC")
    return daily.dropna(subset=["Close"])


class MarketDataDownloader:
    def download(
        self,
        ticker: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
        interval: str = "1d",
        adjusted: bool = False,
        resample_cutoff_utc: str | None = None,
    ) -> DownloadResult:
        try:
            parsed_start = datetime.strptime(start, "%Y-%m-%d").date() if start else None
            parsed_end = datetime.strptime(end, "%Y-%m-%d").date() if end else None
        except ValueError as exc:
            raise InvalidDataRequestError("start and end must use YYYY-MM-DD format.") from exc
        if parsed_start and parsed_end and parsed_start >= parsed_end:
            raise InvalidDataRequestError("start must precede the exclusive end date.")
        request_interval = "1h" if resample_cutoff_utc else interval
        if resample_cutoff_utc and not start:
            raise ValueError("A start date is required when requesting BTC hourly resampling.")
        if resample_cutoff_utc and start:
            try:
                age_days = (datetime.now(timezone.utc).date() - datetime.strptime(start, "%Y-%m-%d").date()).days
            except ValueError as exc:
                raise ValueError("start/end must use YYYY-MM-DD format.") from exc
            # yfinance hourly history is limited. Preserve the existing daily fallback,
            # but record the effective interval so metadata cannot hide the switch.
            if age_days > 700:
                request_interval = "1d"
                resample_cutoff_utc = None

        try:
            raw = yf.download(
                ticker, start=start, end=end, interval=request_interval,
                auto_adjust=adjusted, progress=False,
            )
            if raw is not None and not isinstance(raw, pd.DataFrame):
                raise InvalidProviderResponseError(f"Yahoo Finance returned an unsupported response type for {ticker}.")
            if raw is None or raw.empty:
                raw = yf.Ticker(ticker).history(
                    start=start, end=end, interval=request_interval,
                    auto_adjust=adjusted, actions=True,
                )
            if raw is not None and not isinstance(raw, pd.DataFrame):
                raise InvalidProviderResponseError(f"Yahoo Finance history returned an unsupported response type for {ticker}.")
        except DataDownloadError:
            raise
        except Exception as exc:
            raise NetworkDataDownloadError(f"Yahoo Finance download failed for {ticker}: {exc}") from exc
        if not isinstance(raw, pd.DataFrame):
            raise InvalidProviderResponseError(f"Yahoo Finance returned an unsupported response type for {ticker}.")
        if raw is None or raw.empty:
            raise NoMarketDataError(
                f"Yahoo Finance returned no {request_interval} data for {ticker} in [{start}, {end})."
            )
        raw = _select_provider_asset(raw)
        if resample_cutoff_utc:
            bars = resample_btc_to_ny_close(raw, resample_cutoff_utc)
        else:
            bars = raw.copy()
        if bars.empty:
            raise NoMarketDataError(f"Yahoo Finance returned no usable bars for {ticker}.")
        return DownloadResult(
            raw=raw,
            bars=bars,
            source_interval=request_interval,
            downloaded_at_utc=datetime.now(timezone.utc).isoformat(),
            adjusted=adjusted,
            daily_close_utc=resample_cutoff_utc,
        )


def download_market_data(
    symbol: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    interval: str = "1d",
    resample_btc: bool = False,
    adjusted: bool = False,
) -> pd.DataFrame:
    """Backward-compatible DataFrame API; raises explicit errors on failure."""
    result = MarketDataDownloader().download(
        symbol,
        start=start,
        end=end,
        interval=interval,
        adjusted=adjusted,
        resample_cutoff_utc="21:00" if resample_btc and symbol == "BTC-USD" else None,
    )
    return result.bars
