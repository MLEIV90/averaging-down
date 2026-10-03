import numpy as np
import pandas as pd
import pytest

from src.features.config import FeatureConfig
from src.features.engine import FeatureEngine
from src.features.indicators import (
    FeatureInputError,
    calculate_atr,
    calculate_d_atr,
    calculate_drawdown,
    calculate_ema,
    calculate_realized_volatility,
    calculate_rsi,
    calculate_slope,
    calculate_z_atr,
)


def synthetic_frame(close=(10, 11, 10, 12, 11)):
    idx = pd.date_range("2024-01-01", periods=len(close), freq="D", tz="UTC")
    prices = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {"open": prices, "high": prices + 1, "low": prices - 1, "close": prices, "volume": 10.0},
        index=idx,
    )


def small_config(**changes):
    values = dict(
        ema_fast=2, ema_medium=3, ema_slow=4, atr_period=2, atr_method="sma_true_range",
        rsi_fast_period=2, rsi_period=3, realized_vol_period=2,
        realized_vol_windows=(2,), annualization=4, slope_lookback=1, slope_method="difference",
    )
    values.update(changes)
    return FeatureConfig(**values)


def test_ema_has_reproducible_adjust_false_values_and_no_warmup_nan():
    actual = calculate_ema(pd.Series([10.0, 11.0, 13.0]), 2)
    np.testing.assert_allclose(actual, [10.0, 10.6666666667, 12.2222222222])


def test_atr_sma_true_range_has_manual_value_and_period_warmup():
    frame = synthetic_frame((10, 11, 10, 12))
    actual = calculate_atr(frame, 2)
    assert np.isnan(actual.iloc[0])
    # TR values are [2, 2, 2, 3], so the final two-bar SMA is 2.5.
    assert actual.iloc[-1] == pytest.approx(2.5)


def test_wilder_atr_method_is_explicit_and_different_from_sma():
    frame = synthetic_frame((10, 11, 10, 13, 11))
    assert calculate_atr(frame, 2, "wilder").iloc[-1] == pytest.approx(3.0)
    assert calculate_atr(frame, 2, "sma_true_range").iloc[-1] == pytest.approx(3.5)
    with pytest.raises(FeatureInputError):
        calculate_atr(frame, 2, "unknown")


def test_z_atr_sign_numerator_alias_and_zero_atr_nan():
    idx = pd.RangeIndex(3)
    close = pd.Series([8.0, 12.0, 12.0], index=idx)
    ema = pd.Series([10.0, 10.0, 10.0], index=idx)
    atr = pd.Series([2.0, 2.0, 0.0], index=idx)
    actual = calculate_z_atr(close, ema, atr)
    assert actual.iloc[0] == -1.0
    assert actual.iloc[1] == 1.0
    assert np.isnan(actual.iloc[2])
    pd.testing.assert_series_equal(calculate_d_atr(close, ema, atr), actual)


def test_rsi_sma_expected_value_warmup_and_constant_series():
    close = pd.Series([10.0, 11.0, 10.0, 12.0])
    rsi = calculate_rsi(close, 2)
    assert np.isnan(rsi.iloc[0])
    assert rsi.iloc[1] == pytest.approx(100)
    # At index 2 gains=[1,0], losses=[0,1], so RSI=50.
    assert rsi.iloc[2] == pytest.approx(50)
    assert calculate_rsi(pd.Series([5.0] * 5), 2).isna().all()
    assert calculate_rsi(pd.Series([1.0, 2.0, 3.0]), 2).iloc[-1] == pytest.approx(100)


def test_realized_volatility_log_returns_sample_std_annualization_and_warmup():
    close = pd.Series([100.0, 110.0, 99.0])
    actual = calculate_realized_volatility(close, windows=(2,), annualization=4)
    log_returns = np.log(np.array([110.0 / 100.0, 99.0 / 110.0]))
    assert np.isnan(actual.iloc[0, 0])
    assert actual.iloc[-1, 0] == pytest.approx(np.std(log_returns, ddof=1) * 2)
    simple = calculate_realized_volatility(close, windows=(2,), annualization=4, return_method="simple")
    assert simple.iloc[-1, 0] != pytest.approx(actual.iloc[-1, 0])


def test_asset_drawdown_and_slope_expected_values():
    price = pd.Series([10.0, 12.0, 9.0, 12.0])
    np.testing.assert_allclose(calculate_drawdown(price), [0.0, 0.0, -0.25, 0.0])
    np.testing.assert_allclose(calculate_slope(price, 2, "difference").iloc[2:], [-1.0, 0.0])
    np.testing.assert_allclose(calculate_slope(price, 2, "percent").iloc[2:], [-0.1, 0.0])
    with pytest.raises(FeatureInputError):
        calculate_slope(price, 2, "implicit")


def test_feature_pipeline_matches_values_and_preserves_input():
    frame = synthetic_frame()
    before = frame.copy(deep=True)
    actual = FeatureEngine(small_config()).compute(frame)
    assert actual.index.equals(frame.index)
    assert list(actual.columns[:5]) == ["open", "high", "low", "close", "volume"]
    assert actual.loc[frame.index[1], "ema2"] == pytest.approx(10 + 2 / 3)
    assert actual.loc[frame.index[1], "atr2"] == pytest.approx(2.0)
    assert actual.loc[frame.index[1], "z_atr"] == pytest.approx(1 / 6)
    assert actual.loc[frame.index[2], "rsi2"] == pytest.approx(50.0)
    assert actual.loc[frame.index[2], "asset_drawdown"] == pytest.approx(-1 / 11)
    assert "realized_vol_2" in actual and "ema3_slope" in actual
    pd.testing.assert_frame_equal(frame, before)


def test_regression_matches_previous_eod_indicator_conventions():
    frame = synthetic_frame((10, 11, 10, 12, 11, 13))
    old_ema = frame["close"].ewm(span=3, adjust=False).mean()
    old_tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - frame["close"].shift()).abs(),
            (frame["low"] - frame["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    old_atr = old_tr.rolling(window=2).mean()
    old_rsi_delta = frame["close"].diff()
    old_gain = old_rsi_delta.where(old_rsi_delta > 0, 0).rolling(window=2).mean()
    old_loss = (-old_rsi_delta.where(old_rsi_delta < 0, 0)).rolling(window=2).mean()
    old_rsi = 100 - (100 / (1 + old_gain / old_loss))
    old_log_returns = np.log(frame["close"] / frame["close"].shift(1))
    old_vol = old_log_returns.rolling(window=2).std() * np.sqrt(4)

    pd.testing.assert_series_equal(calculate_ema(frame["close"], 3), old_ema)
    pd.testing.assert_series_equal(calculate_atr(frame, 2), old_atr)
    pd.testing.assert_series_equal(calculate_rsi(frame["close"], 2), old_rsi)
    pd.testing.assert_series_equal(
        calculate_realized_volatility(frame["close"], (2,), 4).iloc[:, 0], old_vol,
        check_names=False,
    )


def test_empty_short_and_irregular_timezone_aware_inputs():
    engine = FeatureEngine(small_config())
    empty = synthetic_frame().iloc[:0]
    assert engine.compute(empty).empty
    short = engine.compute(synthetic_frame((10,)))
    assert short["atr2"].isna().all()
    assert short["rsi2"].isna().all()
    irregular = synthetic_frame().iloc[[0, 2, 4]]
    assert engine.compute(irregular).index.equals(irregular.index)
    with pytest.raises(FeatureInputError, match="timezone-aware"):
        engine.compute(irregular.tz_convert(None))
    with pytest.raises(FeatureInputError, match="ascending"):
        engine.compute(irregular.iloc[::-1])
    with pytest.raises(FeatureInputError, match="duplicates"):
        engine.compute(pd.concat([irregular, irregular.iloc[[0]]]).sort_index())


def test_missing_ohlc_and_invalid_periods_fail_explicitly():
    with pytest.raises(FeatureInputError, match="Missing required OHLCV"):
        FeatureEngine(small_config()).compute(synthetic_frame().drop(columns="high"))
    with pytest.raises(FeatureInputError, match="positive integer"):
        calculate_ema(pd.Series([1.0, 2.0]), 0)
    with pytest.raises(FeatureInputError, match="annualization"):
        calculate_realized_volatility(pd.Series([1.0, 2.0]), annualization=0)


@pytest.mark.parametrize("feature", ["ema2", "atr2", "rsi2", "realized_vol_2", "ema3_slope"])
def test_features_have_no_lookahead_for_future_price_changes(feature):
    frame = synthetic_frame((10, 11, 10, 12, 11))
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] = 100.0
    changed.iloc[-1, changed.columns.get_loc("high")] = 101.0
    changed.iloc[-1, changed.columns.get_loc("low")] = 99.0
    engine = FeatureEngine(small_config())
    original_features = engine.compute(frame)
    changed_features = engine.compute(changed)
    pd.testing.assert_series_equal(
        original_features.loc[frame.index[:-1], feature],
        changed_features.loc[frame.index[:-1], feature],
        check_names=True,
    )
