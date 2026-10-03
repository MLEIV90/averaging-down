import json

import numpy as np
import pandas as pd
import pytest

from src.data.config import AssetDataConfig
from src.data.downloader import DataDownloadError, DownloadResult, resample_btc_to_ny_close
from src.data.engine import DataEngine, DataWarningsRejected, MissingLocalDataError
from src.data.gaps import detect_gaps
from src.data.normalization import InvalidMarketData, normalize_market_data
from src.data.store import DataStore
from src.data.validator import DataValidator, Severity, validate_ohlcv


def bars(index=None):
    index = index if index is not None else pd.date_range("2024-01-02", periods=3, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open": [10.0] * len(index), "high": [12.0] * len(index), "low": [9.0] * len(index),
         "close": [11.0] * len(index), "volume": [100.0] * len(index)},
        index=index,
    ).rename_axis("timestamp")


def config(**kwargs):
    values = dict(ticker="TEST", market_timezone="America/New_York", asset_class="equity")
    values.update(kwargs)
    return AssetDataConfig(**values)


def test_valid_schema_and_legacy_validator_api():
    report = DataValidator().validate(bars())
    assert report.is_valid
    assert not report.issues
    assert validate_ohlcv(bars()) == (True, [])


@pytest.mark.parametrize("mutate,code", [
    (lambda frame: frame.rename(columns={"close": "settle"}), "missing_columns"),
    (lambda frame: frame.iloc[::-1], "unordered_timestamps"),
    (lambda frame: pd.concat([frame, frame.iloc[[0]]]), "duplicate_timestamps"),
    (lambda frame: frame.assign(high=8.0), "invalid_high"),
    (lambda frame: frame.assign(low=13.0), "invalid_low"),
    (lambda frame: frame.assign(close=0.0), "non_positive_price"),
    (lambda frame: frame.assign(volume=-1.0), "invalid_volume"),
])
def test_invalid_schemas_are_rejected(mutate, code):
    report = DataValidator().validate(mutate(bars()))
    assert not report.is_valid
    assert code in {issue.code for issue in report.errors}


def test_empty_and_null_datasets_are_rejected():
    assert "empty_dataset" in {i.code for i in DataValidator().validate(pd.DataFrame()).errors}
    frame = bars()
    frame.iloc[0, frame.columns.get_loc("open")] = np.nan
    assert "invalid_numeric" in {i.code for i in DataValidator().validate(frame).errors}


def test_fully_duplicate_row_is_rejected_but_equal_prices_on_different_dates_are_allowed():
    frame = bars()
    same_values = frame.iloc[[0]].copy()
    same_values.index = pd.DatetimeIndex([pd.Timestamp("2024-01-05", tz="UTC")], name="timestamp")
    assert DataValidator().validate(pd.concat([frame, same_values])).is_valid
    duplicated = pd.concat([frame, frame.iloc[[0]]])
    assert "duplicate_timestamps" in {i.code for i in DataValidator().validate(duplicated).errors}


def test_normalization_uses_utc_aware_index_and_consistent_numeric_schema():
    source_index = pd.date_range("2024-01-02", periods=2, freq="D")
    source = bars(source_index).rename(columns=str.title)
    normalized = normalize_market_data(source, config())
    assert list(normalized.columns) == ["open", "high", "low", "close", "volume"]
    assert all(dtype == "float64" for dtype in normalized.dtypes)
    assert str(normalized.index.tz) == "UTC"
    assert normalized.index[0] == pd.Timestamp("2024-01-02", tz="UTC")


def test_aware_daily_timestamp_keeps_its_provider_session_date_label():
    source = bars(pd.DatetimeIndex([pd.Timestamp("2024-01-02 23:30", tz="UTC")]))
    normalized = normalize_market_data(source, config())
    assert normalized.index[0] == pd.Timestamp("2024-01-02", tz="UTC")


def test_naive_intraday_timestamps_localize_to_market_zone_then_convert_to_utc():
    source = bars(pd.date_range("2024-01-02 09:30", periods=2, freq="h"))
    normalized = normalize_market_data(source, config(interval="1h"))
    assert normalized.index[0] == pd.Timestamp("2024-01-02 14:30", tz="UTC")


def test_btc_close_resampling_preserves_existing_21_utc_session_labels():
    hours = pd.to_datetime(["2024-01-01 21:00Z", "2024-01-02 20:00Z", "2024-01-02 21:00Z"])
    hourly = pd.DataFrame(
        {"Open": [10.0, 11.0, 12.0], "High": [11.0, 13.0, 14.0], "Low": [9.0, 10.0, 11.0],
         "Close": [10.5, 12.5, 13.5], "Volume": [1.0, 2.0, 3.0]},
        index=hours,
    )
    daily = resample_btc_to_ny_close(hourly, close_utc="21:00")
    assert list(daily.index) == [pd.Timestamp("2024-01-02", tz="UTC"), pd.Timestamp("2024-01-03", tz="UTC")]
    assert daily.iloc[0]["Open"] == 10.0
    assert daily.iloc[0]["Volume"] == 3.0


def test_gap_detection_distinguishes_weekends_crypto_and_calendar_ambiguity():
    equity = bars(pd.to_datetime(["2024-01-05", "2024-01-08"], utc=True))
    btc = bars(pd.to_datetime(["2024-01-05", "2024-01-08"], utc=True))
    equity_gaps = detect_gaps(equity, config())
    assert equity_gaps[0].classification == "expected_weekend_closure"
    assert equity_gaps[0].severity == Severity.INFORMATIONAL
    btc_gaps = detect_gaps(btc, config(asset_class="crypto"))
    assert btc_gaps[0].classification == "unexpected_24_7_gap"
    holiday_adjacent = bars(pd.to_datetime(["2024-01-08", "2024-01-10"], utc=True))
    assert detect_gaps(holiday_adjacent, config())[0].classification == "calendar_ambiguous"


def test_requested_leading_gap_is_reported_not_filled():
    gaps = detect_gaps(bars(), config(), expected_start="2024-01-01")
    assert gaps[0].classification == "missing_leading_range"


def test_single_observation_still_reports_requested_edge_gaps():
    one_row = bars().iloc[:1]
    gaps = detect_gaps(one_row, config(), expected_start="2024-01-01", expected_end="2024-01-05")
    assert {gap.classification for gap in gaps} == {"missing_leading_range", "missing_trailing_range"}


def test_store_persists_and_reloads_parquet_and_provenance(tmp_path):
    store = DataStore(tmp_path)
    frame = bars()
    store.save_raw("TEST", frame)
    data_path, metadata_path = store.save_normalized("TEST", frame, {"row_count": len(frame)})
    loaded = store.load_normalized("TEST")
    assert store.load_raw("TEST").equals(frame)
    assert loaded[0].equals(frame)
    assert loaded[1] == {"row_count": 3}
    assert data_path.exists() and metadata_path.exists()


class StubDownloader:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def download(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return next(self.results)


def write_test_config(path):
    path.write_text(
        "data_defaults:\n  start: '2024-01-01'\nassets:\n  TEST:\n    timezone: UTC\n    asset_class: equity\n    enabled: true\n",
        encoding="utf-8",
    )


def download_result(frame, downloaded_at):
    source = frame.rename(columns=str.title)
    return DownloadResult(source, source, "1d", downloaded_at, False, None)


def test_incremental_update_merges_without_duplicate_timestamps_and_records_metadata(tmp_path):
    config_path = tmp_path / "assets.yaml"
    write_test_config(config_path)
    dates = pd.date_range("2024-01-02", periods=3, freq="D", tz="UTC")
    first = bars(dates[:2])
    overlap = bars(dates[1:])
    overlap.loc[dates[1], "close"] = 11.5
    results = [download_result(first, "2024-01-04T00:00:00+00:00"), download_result(overlap, "2024-01-05T00:00:00+00:00")]
    engine = DataEngine(DataStore(tmp_path), StubDownloader(results), config_path=config_path)

    initial = engine.update("TEST", start="2024-01-01", end="2024-01-04")
    updated = engine.update("TEST", start="2024-01-03", end="2024-01-05")
    metadata = json.loads(DataStore(tmp_path).metadata_path("TEST").read_text(encoding="utf-8"))
    assert len(initial) == 2
    assert len(updated) == 3
    assert updated.index.is_unique
    assert updated.loc[dates[1], "close"] == 11.5
    assert metadata["asset"] == "TEST"
    assert metadata["source"] == "Yahoo Finance (yfinance)"
    assert metadata["row_count"] == 3
    assert metadata["adjusted"] is False
    assert metadata["schema_version"] == "1.0"
    assert engine.load("TEST").equals(updated)


def test_load_missing_data_is_explicit_without_download(tmp_path):
    config_path = tmp_path / "assets.yaml"
    write_test_config(config_path)
    with pytest.raises(MissingLocalDataError):
        DataEngine(DataStore(tmp_path), config_path=config_path).load_or_download("TEST", allow_download=False)


def test_invalid_download_is_not_persisted(tmp_path):
    config_path = tmp_path / "assets.yaml"
    write_test_config(config_path)
    invalid = bars().assign(high=8.0)
    engine = DataEngine(DataStore(tmp_path), StubDownloader([download_result(invalid, "2024-01-04T00:00:00+00:00")]), config_path=config_path)
    with pytest.raises(InvalidMarketData):
        engine.update("TEST", start="2024-01-01", end="2024-01-04")
    assert not DataStore(tmp_path).normalized_path("TEST").exists()


def test_adjusted_choice_and_daily_session_label_are_configurable():
    default_cfg = config()
    frame = normalize_market_data(bars(pd.date_range("2024-01-02", periods=1)), default_cfg)
    assert frame.index[0] == pd.Timestamp("2024-01-02", tz="UTC")
    assert default_cfg.adjusted is False


def test_warning_policy_is_caller_configurable(tmp_path):
    config_path = tmp_path / "assets.yaml"
    write_test_config(config_path)
    dates = pd.to_datetime(["2024-01-02", "2024-01-04"], utc=True)
    frame = bars(dates)
    engine = DataEngine(
        DataStore(tmp_path),
        StubDownloader([download_result(frame, "2024-01-05T00:00:00+00:00")]),
        config_path=config_path,
        allow_warnings=False,
    )
    with pytest.raises(DataWarningsRejected):
        engine.update("TEST", start="2024-01-01", end="2024-01-05")
    assert not DataStore(tmp_path).normalized_path("TEST").exists()


def test_downloader_wraps_provider_network_errors(monkeypatch):
    import src.data.downloader as downloader_module

    def raise_network_error(*args, **kwargs):
        raise TimeoutError("network unavailable")

    monkeypatch.setattr(downloader_module.yf, "download", raise_network_error)
    with pytest.raises(DataDownloadError, match="Yahoo Finance download failed"):
        downloader_module.MarketDataDownloader().download("TEST", start="2024-01-01", end="2024-01-05")


def test_btc_provider_daily_fallback_is_kept_consistent_for_incremental_updates(tmp_path):
    config_path = tmp_path / "assets.yaml"
    config_path.write_text(
        "data_defaults:\n  start: '2020-01-01'\nassets:\n  BTC-USD:\n    timezone: UTC\n    asset_class: crypto\n    source_interval: 1h\n    daily_close_utc: '21:00'\n",
        encoding="utf-8",
    )
    dates = pd.date_range("2024-01-02", periods=3, freq="D", tz="UTC")
    fallback = DownloadResult(bars(dates).rename(columns=str.title), bars(dates).rename(columns=str.title), "1d", "2024-01-05T00:00:00+00:00", False, None)
    next_daily = DownloadResult(bars(dates[-1:]).rename(columns=str.title), bars(dates[-1:]).rename(columns=str.title), "1d", "2024-01-06T00:00:00+00:00", False, None)
    downloader = StubDownloader([fallback, next_daily])
    engine = DataEngine(DataStore(tmp_path), downloader, config_path=config_path)
    engine.update("BTC-USD", start="2020-01-01", end="2024-01-05")
    engine.update("BTC-USD", end="2024-01-06")
    assert downloader.calls[1][1]["interval"] == "1d"
    assert downloader.calls[1][1]["resample_cutoff_utc"] is None


def test_hourly_raw_cache_is_reconstructed_using_its_recorded_cutoff(tmp_path):
    config_path = tmp_path / "assets.yaml"
    config_path.write_text(
        "assets:\n  BTC-USD:\n    timezone: UTC\n    asset_class: crypto\n    source_interval: 1h\n    daily_close_utc: '21:00'\n",
        encoding="utf-8",
    )
    hourly_index = pd.to_datetime(["2024-01-01 21:00Z", "2024-01-02 20:00Z"])
    hourly = pd.DataFrame(
        {"Open": [10.0, 11.0], "High": [11.0, 12.0], "Low": [9.0, 10.0],
         "Close": [10.5, 11.5], "Volume": [1.0, 2.0]},
        index=hourly_index,
    )
    store = DataStore(tmp_path)
    store.save_raw("BTC-USD", hourly)
    store.save_raw_metadata("BTC-USD", {
        "asset": "BTC-USD", "source": "Yahoo Finance (yfinance)", "frequency": "1h",
        "daily_close_utc": "21:00", "adjusted": False, "download_timestamp_utc": "2024-01-03T00:00:00+00:00",
    })
    loaded = DataEngine(store, StubDownloader([]), config_path=config_path).load_or_download("BTC-USD", allow_download=False)
    assert list(loaded.index) == [pd.Timestamp("2024-01-02", tz="UTC")]
    assert loaded.iloc[0]["volume"] == 3.0
    normalized_metadata = store.load_normalized("BTC-USD")[1]
    assert normalized_metadata["daily_close_utc_applied"] == "21:00"
