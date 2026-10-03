import numpy as np
import pandas as pd
import pytest

from src.features.config import FeatureConfig
from src.features.regime import (
    RegimeConfig,
    RegimeEngine,
    detect_market_regime,
    is_panic,
)


FEATURES = FeatureConfig()
REGIME = RegimeConfig(panic_vol_lookback=3, panic_vol_quantile=0.9, panic_atr_multiple=3.0)


def feature_frame(rows):
    """Rows are close, ema20, ema50, ema200, atr14, realized_vol_10."""
    index = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC", name="timestamp")
    return pd.DataFrame(
        rows,
        index=index,
        columns=["close", "ema20", "ema50", "ema200", "atr14", "realized_vol_10"],
        dtype=float,
    )


def stable_rows(count=4):
    return [(100, 105, 100, 90, 2, 1) for _ in range(count)]


def engine():
    return RegimeEngine(FEATURES, REGIME)


def test_bull_bear_and_neutral_conditions_are_explicit():
    bull = feature_frame([(110, 105, 100, 90, 2, 1)])
    bear = feature_frame([(80, 95, 80, 90, 2, 1)])
    neutral = feature_frame([(100, 110, 100, 100, 2, 1)])

    assert engine().classify_latest(bull).trend_regime == "BULL"
    assert engine().classify_latest(bear).trend_regime == "BEAR"
    assert engine().classify_latest(neutral).trend_regime == "NEUTRAL"


def test_trend_boundaries_preserve_strict_and_inclusive_comparisons():
    close_equals_slow = feature_frame([(100, 110, 100, 100, 2, 1)])
    fast_equals_medium = feature_frame([(110, 100, 100, 90, 2, 1)])
    medium_equals_slow = feature_frame([(80, 70, 90, 90, 2, 1)])

    assert engine().classify_latest(close_equals_slow).trend_regime == "NEUTRAL"
    assert engine().classify_latest(fast_equals_medium).trend_regime == "BULL"
    assert engine().classify_latest(medium_equals_slow).trend_regime == "NEUTRAL"


def test_ema_slope_is_supporting_only_and_does_not_gate_bull():
    frame = feature_frame([(110, 105, 100, 90, 2, 1)])
    frame["ema50_slope"] = -10.0
    assert engine().classify_latest(frame).trend_regime == "BULL"


def test_missing_or_nan_trend_features_are_unknown_not_neutral():
    frame = feature_frame(stable_rows())
    frame.loc[frame.index[-1], "ema200"] = np.nan
    result = engine().classify_latest(frame)
    assert result.trend_regime == "UNKNOWN"
    assert result.insufficient_data
    assert "ema200" in result.unavailable_features

    missing = feature_frame(stable_rows()).drop(columns="ema20")
    missing_result = engine().classify_latest(missing)
    assert missing_result.trend_regime == "UNKNOWN"
    assert "ema20" in missing_result.unavailable_features


def test_stress_is_unknown_during_volatility_warmup_without_a_shock():
    frame = feature_frame(stable_rows(2))
    frame["realized_vol_10"] = np.nan
    result = engine().classify_latest(frame)
    assert result.trend_regime == "BULL"
    assert result.stress_regime == "UNKNOWN"
    assert result.insufficient_data
    assert "realized_vol_10" in result.unavailable_features


def test_high_volatility_without_a_large_drop_is_panic():
    rows = stable_rows(4)
    rows[-1] = (100, 105, 100, 90, 2, 10)
    result = engine().classify_latest(feature_frame(rows))
    assert result.stress_regime == "PANIC"
    assert result.trend_regime == "BULL"
    assert "panic_high_volatility" in result.reason


def test_large_atr_scaled_drop_without_extreme_volatility_is_panic():
    rows = stable_rows(4)
    rows[-1] = (90, 95, 90, 90, 2, 1)
    result = engine().classify_latest(feature_frame(rows))
    assert result.stress_regime == "PANIC"
    assert "panic_atr_shock" in result.reason


def test_both_panic_components_and_neither_component():
    both = stable_rows(4)
    both[-1] = (90, 95, 90, 90, 2, 10)
    neither = stable_rows(4)

    both_result = engine().classify_latest(feature_frame(both))
    neither_result = engine().classify_latest(feature_frame(neither))
    assert both_result.stress_regime == "PANIC"
    assert "panic_volatility_and_atr_shock" in both_result.reason
    assert neither_result.stress_regime == "NORMAL"
    assert not neither_result.insufficient_data


def test_panic_thresholds_keep_strict_comparisons_at_equality():
    equal_vol = stable_rows(4)
    equal_drop = stable_rows(4)
    equal_drop[-1] = (94, 99, 94, 90, 2, 1)
    assert engine().classify_latest(feature_frame(equal_vol)).stress_regime == "NORMAL"
    # A six-point decline equals 3 * ATR(2), so strict '<' does not trigger.
    assert engine().classify_latest(feature_frame(equal_drop)).stress_regime == "NORMAL"


def test_compatibility_helpers_match_the_audited_latest_rules():
    rows = stable_rows(4)
    rows[-1] = (90, 95, 90, 100, 2, 1)
    frame = feature_frame(rows)
    old_trend = (
        "BULL" if frame["close"].iloc[-1] > frame["ema200"].iloc[-1]
        and frame["ema20"].iloc[-1] >= frame["ema50"].iloc[-1]
        else "BEAR" if frame["close"].iloc[-1] < frame["ema200"].iloc[-1]
        and frame["ema50"].iloc[-1] < frame["ema200"].iloc[-1]
        else "NEUTRAL"
    )
    old_panic = (
        frame["realized_vol_10"].iloc[-1] > frame["realized_vol_10"].tail(252).quantile(0.90)
        or frame["close"].iloc[-1] - frame["close"].iloc[-2] < -3 * frame["atr14"].iloc[-1]
    )
    assert detect_market_regime(frame, FEATURES) == old_trend
    assert is_panic(frame, FEATURES) == bool(old_panic)


def test_series_reports_bull_neutral_bear_transition_and_latest_matches():
    frame = feature_frame(
        [
            (110, 105, 100, 90, 2, 1),
            (110, 95, 100, 90, 2, 1),
            (80, 70, 80, 90, 2, 1),
        ]
    )
    history = engine().classify_series(frame)
    latest = engine().classify_latest(frame)

    assert history["trend_regime"].tolist() == ["BULL", "NEUTRAL", "BEAR"]
    assert latest.trend_regime == history.iloc[-1]["trend_regime"]
    assert latest.stress_regime == history.iloc[-1]["stress_regime"]
    assert latest.timestamp == frame.index[-1]


def test_bull_and_bear_trends_can_coexist_with_panic_stress():
    bull_rows = stable_rows(4)
    bull_rows[-1] = (100, 105, 100, 90, 2, 10)
    bear_rows = [(80, 95, 80, 90, 2, 1) for _ in range(4)]
    bear_rows[-1] = (70, 85, 70, 90, 2, 1)

    bull_panic = engine().classify_latest(feature_frame(bull_rows))
    bear_panic = engine().classify_latest(feature_frame(bear_rows))
    assert (bull_panic.trend_regime, bull_panic.stress_regime) == ("BULL", "PANIC")
    assert (bear_panic.trend_regime, bear_panic.stress_regime) == ("BEAR", "PANIC")


def test_future_changes_do_not_rewrite_historical_regimes():
    frame = feature_frame(
        [
            (110, 105, 100, 90, 2, 1),
            (110, 105, 100, 90, 2, 1),
            (110, 105, 100, 90, 2, 1),
            (90, 95, 90, 100, 2, 1),
        ]
    )
    changed = frame.copy()
    changed.iloc[-1] = [30, 200, 220, 250, 50, 1000]
    original_history = engine().classify_series(frame)
    changed_history = engine().classify_series(changed)
    pd.testing.assert_frame_equal(
        original_history.iloc[:-1], changed_history.iloc[:-1], check_dtype=True
    )


def test_empty_input_and_missing_stress_inputs_are_explicit():
    empty = feature_frame([])
    assert engine().classify_series(empty).empty
    empty_result = engine().classify_latest(empty)
    assert empty_result.trend_regime == "UNKNOWN"
    assert empty_result.stress_regime == "UNKNOWN"
    assert empty_result.insufficient_data

    missing = feature_frame(stable_rows()).drop(columns="atr14")
    result = engine().classify_latest(missing)
    assert result.stress_regime == "UNKNOWN"
    assert "atr14" in result.unavailable_features


def test_series_rejects_unsorted_or_duplicate_timestamps():
    frame = feature_frame(stable_rows())
    with pytest.raises(ValueError, match="ascending"):
        engine().classify_series(frame.iloc[::-1])
    with pytest.raises(ValueError, match="unique"):
        engine().classify_series(pd.concat([frame, frame.iloc[[-1]]]))
