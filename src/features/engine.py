"""Deterministic Feature Engine for validated, normalized Data Engine output."""

from __future__ import annotations

import pandas as pd

from .config import FeatureConfig, load_feature_config
from .indicators import (
    FeatureInputError,
    calculate_atr,
    calculate_drawdown,
    calculate_ema,
    calculate_realized_volatility,
    calculate_rsi,
    calculate_slope,
    calculate_z_atr,
)

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


class FeatureEngine:
    """Compute lowercase feature columns, retaining OHLCV and its index."""

    def __init__(self, config: FeatureConfig | None = None):
        self.config = config or load_feature_config()

    def compute(self, frame: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(frame, pd.DataFrame):
            raise FeatureInputError("FeatureEngine input must be a pandas DataFrame.")
        missing = [field for field in OHLCV_COLUMNS if field not in frame.columns]
        if missing:
            raise FeatureInputError(f"Missing required OHLCV fields: {missing}.")
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise FeatureInputError("FeatureEngine requires a timezone-aware DatetimeIndex.")
        if str(frame.index.tz) not in {"UTC", "UTC+00:00", "tzutc()", "Etc/UTC", "Etc/GMT", "GMT"}:
            raise FeatureInputError("FeatureEngine requires a UTC DatetimeIndex.")
        if not frame.index.is_monotonic_increasing:
            raise FeatureInputError("FeatureEngine input index must be ascending.")
        if frame.index.has_duplicates:
            raise FeatureInputError("FeatureEngine input index must not contain duplicates.")
        if frame.empty:
            return frame.loc[:, list(OHLCV_COLUMNS)].copy()

        cfg = self.config
        out = frame.loc[:, list(OHLCV_COLUMNS)].copy()
        ema_fast_column = f"ema{cfg.ema_fast}"
        ema_medium_column = f"ema{cfg.ema_medium}"
        ema_slow_column = f"ema{cfg.ema_slow}"
        atr_column = f"atr{cfg.atr_period}"
        out[ema_fast_column] = calculate_ema(out["close"], cfg.ema_fast)
        out[ema_medium_column] = calculate_ema(out["close"], cfg.ema_medium)
        out[ema_slow_column] = calculate_ema(out["close"], cfg.ema_slow)
        out[atr_column] = calculate_atr(out, cfg.atr_period, method=cfg.atr_method)
        out["z_atr"] = calculate_z_atr(out["close"], out[ema_fast_column], out[atr_column])
        out[f"rsi{cfg.rsi_fast_period}"] = calculate_rsi(out["close"], cfg.rsi_fast_period)
        out[f"rsi{cfg.rsi_period}"] = calculate_rsi(out["close"], cfg.rsi_period)
        realized = calculate_realized_volatility(
            out["close"], cfg.realized_vol_windows, cfg.annualization, cfg.realized_vol_return_method
        )
        out = out.join(realized)
        if cfg.realized_vol_period not in cfg.realized_vol_windows:
            out[f"realized_vol_{cfg.realized_vol_period}"] = calculate_realized_volatility(
                out["close"], (cfg.realized_vol_period,), cfg.annualization, cfg.realized_vol_return_method
            ).iloc[:, 0]
        out["asset_drawdown"] = calculate_drawdown(out["close"])
        out[f"{ema_medium_column}_slope"] = calculate_slope(
            out[ema_medium_column], cfg.slope_lookback, cfg.slope_method
        )
        return out


def calculate_features(frame: pd.DataFrame, config: FeatureConfig | None = None) -> pd.DataFrame:
    return FeatureEngine(config).compute(frame)
