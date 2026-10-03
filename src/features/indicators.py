"""Pure, causal quantitative feature calculations.

The historical calculation conventions are retained where the repository had
an identifiable implementation. See README.md and RESEARCH_LOG.md for their
limitations; passing software tests is not financial validation.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


class FeatureInputError(ValueError):
    """Raised when feature inputs violate their documented data contract."""


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value <= 0:
        raise FeatureInputError(f"{name} must be a positive integer.")
    return int(value)


def _field(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame:
        return frame[name]
    legacy = name.title()
    if legacy in frame:
        return frame[legacy]
    raise FeatureInputError(f"Missing required OHLCV field: {name}.")


def calculate_ema(series: pd.Series, span: int) -> pd.Series:
    """Legacy-compatible EMA, seeded by the first value (adjust=False)."""
    span = _positive_int(span, "span")
    if not isinstance(series, pd.Series):
        raise FeatureInputError("EMA input must be a pandas Series.")
    return series.ewm(span=span, adjust=False).mean()


def calculate_atr(df: pd.DataFrame, period: int = 14, method: str = "sma_true_range") -> pd.Series:
    """True Range averaged with a simple moving average (legacy convention).

    The first True Range is high-low, so ATR first becomes available at
    position ``period - 1``. ``wilder`` is also explicit for future comparison.
    """
    period = _positive_int(period, "period")
    high, low, close = (_field(df, col) for col in ("high", "low", "close"))
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    if method == "sma_true_range":
        return tr.rolling(window=period, min_periods=period).mean()
    if method == "wilder":
        # Wilder's RMA, seeded by the first complete-period SMA.
        result = pd.Series(np.nan, index=tr.index, dtype="float64", name=tr.name)
        if len(tr) < period:
            return result
        seed_at = period - 1
        result.iloc[seed_at] = tr.iloc[:period].mean()
        result.iloc[period:] = tr.iloc[period:]
        return result.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
    raise FeatureInputError("ATR method must be 'sma_true_range' or 'wilder'.")


def calculate_z_atr(close: pd.Series, ema: pd.Series, atr: pd.Series) -> pd.Series:
    """Distance from EMA in ATR units; zero ATR is represented as NaN."""
    if not (close.index.equals(ema.index) and close.index.equals(atr.index)):
        raise FeatureInputError("close, ema, and atr must have identical indexes.")
    denominator = atr.where(atr != 0)
    return (close - ema) / denominator


def calculate_d_atr(close: pd.Series, ema_fast: pd.Series, atr: pd.Series) -> pd.Series:
    """Deprecated spelling retained as a backward-compatible alias for z_atr."""
    return calculate_z_atr(close, ema_fast, atr)


def calculate_rsi(close: pd.Series, period: int = 14, method: str = "sma") -> pd.Series:
    """RSI using the repository's simple rolling gain/loss averages.

    A zero average loss with positive average gain yields 100. When both are
    zero (a constant window), the mathematically undefined result remains NaN.
    """
    period = _positive_int(period, "period")
    if method != "sma":
        raise FeatureInputError("RSI method must be 'sma'.")
    delta = close.diff()
    # Preserve the prior implementation: the first unavailable delta is
    # converted to zero by where(..., 0), so the first full RSI window occurs
    # after ``period`` closes rather than ``period + 1`` closes.
    gain = delta.where(delta > 0, 0).rolling(window=period, min_periods=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period, min_periods=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calculate_realized_volatility(
    close: pd.Series,
    windows: Iterable[int] = (10, 20, 60),
    annualization: float = 252,
    return_method: str = "log",
) -> pd.DataFrame:
    """Annualized sample std of causal simple/log returns (legacy uses log)."""
    if isinstance(annualization, bool) or not isinstance(annualization, (int, float, np.number)) or not np.isfinite(annualization) or annualization <= 0:
        raise FeatureInputError("annualization must be a positive finite number.")
    periods = tuple(_positive_int(window, "window") for window in windows)
    if not periods:
        raise FeatureInputError("windows must contain at least one positive integer.")
    if return_method == "log":
        returns = np.log(close / close.shift(1))
    elif return_method == "simple":
        returns = close.pct_change(fill_method=None)
    else:
        raise FeatureInputError("return_method must be 'log' or 'simple'.")
    return pd.DataFrame(
        {
            f"realized_vol_{window}": returns.rolling(window, min_periods=window).std() * np.sqrt(annualization)
            for window in periods
        },
        index=close.index,
    )


def calculate_drawdown(price: pd.Series) -> pd.Series:
    """Asset-price drawdown from its running peak; distinct from portfolio DD."""
    return price / price.cummax() - 1


def calculate_slope(series: pd.Series, lookback: int, method: str) -> pd.Series:
    """EMA slope helper; method is mandatory because no finance convention is approved."""
    lookback = _positive_int(lookback, "lookback")
    if method == "difference":
        return series - series.shift(lookback)
    if method == "percent":
        return series / series.shift(lookback) - 1
    raise FeatureInputError("slope method must be 'difference' or 'percent'.")
