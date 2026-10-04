import numpy as np
import pandas as pd
import pytest

from src.features.regime import RegimeConfig, RegimeEngine
from src.strategy.signals import SignalConfig, SignalEngine, load_signal_config


def feature_frame(rows):
    """Tuples: close, high, low, z_atr, rsi2, realized_vol_20."""
    index = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC", name="timestamp")
    data = pd.DataFrame(rows, index=index, columns=["close", "high", "low", "z_atr", "rsi2", "realized_vol_20"])
    data["open"] = data["close"]
    data["volume"] = 1.0
    data["ema20"] = data["close"] - 1
    data["ema50"] = data["close"] - 2
    data["ema200"] = data["close"] - 3
    data["atr14"] = 1.0
    data["realized_vol_10"] = 1.0
    return data


def engine():
    regime = RegimeEngine(regime_config=RegimeConfig(panic_vol_lookback=3))
    return SignalEngine(regime_engine=regime)


def opportunity(close=102.0, high=103.0, low=100.0, z=-1.50, rsi=10.0, vol20=0.2):
    # Last close rises from 101; its location is 2/3 of the day's range.
    return feature_frame([(101, 103, 100, z, rsi, vol20), (close, high, low, z, rsi, vol20)])


@pytest.mark.parametrize(("asset", "threshold"), [("SPY", -1.50), ("BTC", -1.75), ("GLD", -1.50)])
def test_asset_threshold_inclusive_boundary_and_just_above(asset, threshold):
    exact = engine().classify_latest(opportunity(z=threshold), asset)
    more_extreme = engine().classify_latest(opportunity(z=threshold - 0.001), asset)
    above = engine().classify_latest(opportunity(z=threshold + 0.001), asset)
    assert exact.z_atr_extreme
    assert more_extreme.z_atr_extreme
    assert not above.z_atr_extreme


def test_btc_usd_uses_the_configured_btc_threshold_alias():
    assert engine().classify_latest(opportunity(z=-1.75), "BTC-USD").z_atr_extreme


def test_rsi2_threshold_is_inclusive_and_does_not_pass_just_above():
    exact = engine().classify_latest(opportunity(rsi=10.0), "SPY")
    above = engine().classify_latest(opportunity(rsi=10.001), "SPY")
    assert exact.rsi2_extreme
    assert not above.rsi2_extreme


@pytest.mark.parametrize("column", ["z_atr", "rsi2"])
def test_missing_or_nan_extreme_feature_is_unknown(column):
    frame = opportunity()
    frame[column] = np.nan
    result = engine().classify_latest(frame, "SPY")
    assert result.signal_state == "UNKNOWN"
    assert column in result.unavailable_features


def test_reversal_requires_rising_close_and_close_in_upper_60_percent():
    assert engine().classify_latest(opportunity(), "SPY").reversal_confirmed
    boundary = engine().classify_latest(opportunity(close=103.0, high=105.0, low=100.0), "SPY")
    assert boundary.close_location == pytest.approx(0.60)
    assert boundary.reversal_confirmed
    assert not engine().classify_latest(opportunity(close=101.5), "SPY").reversal_confirmed
    assert not engine().classify_latest(opportunity(close=101.0, high=103.0, low=100.0), "SPY").reversal_confirmed
    assert not engine().classify_latest(opportunity(close=100.5, high=103.0, low=100.0), "SPY").reversal_confirmed

    falling = opportunity(close=101.8, high=103.0, low=100.0)
    falling.iloc[0, falling.columns.get_loc("close")] = 102.0
    result = engine().classify_latest(falling, "SPY")
    assert result.close_location == pytest.approx(0.60)
    assert not result.reversal_confirmed


def test_flat_daily_range_and_missing_previous_close_are_unavailable():
    flat = opportunity(close=102.0, high=102.0, low=102.0)
    result = engine().classify_latest(flat, "SPY")
    assert result.close_location is None
    assert result.reversal_confirmed is None
    assert result.signal_state == "UNKNOWN"

    first = engine().classify_latest(opportunity().iloc[[0]], "SPY")
    assert first.previous_close is None
    assert first.signal_state == "UNKNOWN"


@pytest.mark.parametrize(("trend", "eligible"), [("BULL", True), ("NEUTRAL", False), ("BEAR", False)])
def test_trend_regime_eligibility_is_explicit(trend, eligible):
    frame = opportunity()
    if trend == "NEUTRAL":
        frame.loc[:, "ema20"] = frame["ema50"] - 1
    elif trend == "BEAR":
        frame.loc[:, "close"] = 90.0
        frame.loc[:, "ema20"] = 95.0
        frame.loc[:, "ema50"] = 85.0
        frame.loc[:, "ema200"] = 100.0
        frame.loc[:, "high"] = 100.0
        frame.loc[:, "low"] = 80.0
    result = engine().classify_latest(frame, "SPY")
    assert result.trend_regime == trend
    assert result.regime_eligible is eligible
    if trend != "BULL":
        assert not result.entry_candidate


def test_unknown_trend_and_unknown_stress_never_enable_entry():
    frame = opportunity()
    frame["ema200"] = np.nan
    unknown_trend = engine().classify_latest(frame, "SPY")
    assert unknown_trend.trend_regime == "UNKNOWN"
    assert unknown_trend.signal_state == "UNKNOWN"

    frame = opportunity()
    frame["realized_vol_10"] = np.nan
    unknown_stress = engine().classify_latest(frame, "SPY")
    assert unknown_stress.stress_regime == "UNKNOWN"
    assert unknown_stress.stress_blocked is None
    assert unknown_stress.signal_state == "UNKNOWN"
    assert not unknown_stress.entry_candidate


def test_panic_blocks_otherwise_entry_candidate_but_normal_does_not():
    frame = opportunity()
    normal = engine().classify_latest(frame, "SPY")
    assert normal.stress_regime == "NORMAL"
    assert not normal.stress_blocked
    assert normal.signal_state == "ENTRY_CANDIDATE"

    panic_frame = opportunity()
    panic_frame["realized_vol_10"] = [0.1, 10.0]
    blocked = engine().classify_latest(panic_frame, "SPY")
    assert blocked.stress_regime == "PANIC"
    assert blocked.stress_blocked
    assert blocked.signal_state == "BLOCKED"
    assert not blocked.entry_candidate


def test_state_machine_reaches_unknown_blocked_watch_entry_and_no_signal():
    signal_engine = engine()
    assert signal_engine.classify_latest(opportunity().iloc[:1], "SPY").signal_state == "UNKNOWN"
    assert signal_engine.classify_latest(opportunity(), "SPY").signal_state == "ENTRY_CANDIDATE"
    assert signal_engine.classify_latest(opportunity(close=101.5), "SPY").signal_state == "WATCH"
    assert signal_engine.classify_latest(opportunity(z=-1.0), "SPY").signal_state == "NO_SIGNAL"
    panic = opportunity()
    panic["realized_vol_10"] = [0.1, 10.0]
    assert signal_engine.classify_latest(panic, "SPY").signal_state == "BLOCKED"


def test_realized_volatility_is_exposed_but_does_not_gate_signal():
    low = engine().classify_latest(opportunity(vol20=0.01), "SPY")
    high = engine().classify_latest(opportunity(vol20=100.0), "SPY")
    assert low.realized_vol_20 == 0.01 and high.realized_vol_20 == 100.0
    assert low.signal_state == high.signal_state == "ENTRY_CANDIDATE"


def test_latest_matches_series_and_future_changes_do_not_change_earlier_signals():
    frame = opportunity()
    frame = pd.concat([frame, opportunity().iloc[[-1]].set_axis([frame.index[-1] + pd.Timedelta(days=1)])])
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] = 50.0
    changed.iloc[-1, changed.columns.get_loc("high")] = 55.0
    changed.iloc[-1, changed.columns.get_loc("low")] = 45.0
    first = engine().classify_series(frame, "SPY")
    second = engine().classify_series(changed, "SPY")
    pd.testing.assert_frame_equal(first.iloc[:-1], second.iloc[:-1])
    latest = engine().classify_latest(frame, "SPY")
    assert latest.signal_state == first.iloc[-1]["signal_state"]
    assert latest.timestamp == first.index[-1]


def test_signal_configuration_load_and_range_validation(tmp_path):
    config = load_signal_config()
    assert config.z_atr_thresholds == {"SPY": -1.5, "BTC": -1.75, "GLD": -1.5}
    with pytest.raises(ValueError, match="between 0 and 100"):
        SignalConfig(rsi2_entry_threshold=101)
    path = tmp_path / "bad.yaml"
    path.write_text("signals:\n  rsi2_entry_threshold: -1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="between 0 and 100"):
        load_signal_config(path)
