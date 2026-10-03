import pandas as pd

from .config import AssetDataConfig
from .downloader import InvalidProviderResponseError
from .validator import DataValidator, ValidationReport


OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
SCHEMA_VERSION = "1.0"


class InvalidMarketData(ValueError):
    def __init__(self, report: ValidationReport):
        self.report = report
        summary = "; ".join(issue.message for issue in report.errors)
        super().__init__(summary or "Market data is invalid.")


def normalize_market_data(raw: pd.DataFrame, config: AssetDataConfig) -> pd.DataFrame:
    """Map provider OHLCV fields to lowercase and use a UTC-aware time index.

    Daily timestamps are session-date labels: their displayed date component is
    preserved and represented at 00:00 UTC. Naive intraday timestamps are
    localized to the configured market timezone before conversion; aware
    intraday timestamps are converted as instants to UTC. No prices are filled
    or resampled here.
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=list(OHLCV_COLUMNS), index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        # yfinance may return (field, ticker) or (ticker, field) columns.
        levels = [list(map(str, frame.columns.get_level_values(i))) for i in range(frame.columns.nlevels)]
        field_level = next((i for i, values in enumerate(levels) if {v.lower() for v in values} & set(OHLCV_COLUMNS)), None)
        if field_level is None:
            raise InvalidProviderResponseError("Provider response has no identifiable OHLCV column level.")
        frame.columns = frame.columns.get_level_values(field_level)

    mapped: dict[str, str] = {}
    for column in frame.columns:
        key = str(column).strip().lower().replace(" ", "_")
        if key in OHLCV_COLUMNS:
            mapped[column] = key
    frame = frame.rename(columns=mapped)
    missing = [column for column in OHLCV_COLUMNS if column not in frame.columns]
    if missing:
        raise InvalidProviderResponseError(f"Provider response is missing OHLCV fields: {missing}.")
    # Retain only the canonical schema. Duplicate aliases are rejected.
    if frame.columns.duplicated().any():
        raise InvalidProviderResponseError("Provider response contains duplicate OHLCV fields.")
    frame = frame.loc[:, list(OHLCV_COLUMNS)].copy()
    try:
        frame.index = pd.DatetimeIndex(frame.index, name="timestamp")
    except (TypeError, ValueError) as exc:
        raise InvalidProviderResponseError("Provider response timestamps are not valid datetimes.") from exc
    is_daily = config.interval.lower() in {"1d", "d", "daily"}
    if is_daily:
        # A daily bar's date is a label. Preserve that date even if a provider
        # represents the label with a timezone-aware midnight/close timestamp.
        date_labels = frame.index.tz_localize(None).normalize()
        frame.index = date_labels.tz_localize("UTC")
    elif frame.index.tz is None:
        frame.index = frame.index.tz_localize(config.market_timezone, ambiguous="raise", nonexistent="raise").tz_convert("UTC")
    else:
        frame.index = frame.index.tz_convert("UTC")
    frame.index.name = "timestamp"
    for column in OHLCV_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    return frame


def validate_normalized(frame: pd.DataFrame) -> ValidationReport:
    return DataValidator().validate(frame)


def normalize_and_validate(raw: pd.DataFrame, config: AssetDataConfig) -> pd.DataFrame:
    frame = normalize_market_data(raw, config)
    report = validate_normalized(frame)
    if not report.is_valid:
        raise InvalidMarketData(report)
    return frame
