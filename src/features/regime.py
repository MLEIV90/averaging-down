"""Point-in-time market trend and stress classification.

These rules reproduce the repository's existing provisional classifier. They
are implemented software conventions, not financially validated definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .config import FeatureConfig, load_feature_config
from src.data.config import REPOSITORY_ROOT

DEFAULT_REGIME_CONFIG = REPOSITORY_ROOT / "config" / "regime.yaml"


@dataclass(frozen=True)
class RegimeConfig:
    panic_vol_period: int = 10
    panic_vol_lookback: int = 252
    panic_vol_quantile: float = 0.90
    panic_atr_multiple: float = 3.0

    def __post_init__(self) -> None:
        if isinstance(self.panic_vol_period, bool) or not isinstance(self.panic_vol_period, int) or self.panic_vol_period <= 0:
            raise ValueError("panic_vol_period must be a positive integer.")
        if isinstance(self.panic_vol_lookback, bool) or not isinstance(self.panic_vol_lookback, int) or self.panic_vol_lookback <= 0:
            raise ValueError("panic_vol_lookback must be a positive integer.")
        if isinstance(self.panic_vol_quantile, bool) or not isinstance(self.panic_vol_quantile, (int, float)) or not 0 < self.panic_vol_quantile < 1:
            raise ValueError("panic_vol_quantile must be between 0 and 1.")
        if isinstance(self.panic_atr_multiple, bool) or not isinstance(self.panic_atr_multiple, (int, float)) or self.panic_atr_multiple <= 0:
            raise ValueError("panic_atr_multiple must be positive.")


def load_regime_config(path: str | Path = DEFAULT_REGIME_CONFIG) -> RegimeConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read regime configuration at {config_path}: {exc}") from exc
    values = raw.get("regime", {})
    if not isinstance(values, dict):
        raise ValueError("regime.yaml must define a 'regime' mapping.")
    try:
        config = RegimeConfig(**values)
    except TypeError as exc:
        raise ValueError(f"Invalid regime configuration: {exc}") from exc
    return config


@dataclass(frozen=True)
class RegimeResult:
    timestamp: pd.Timestamp | None
    trend_regime: str
    stress_regime: str
    supporting_features: dict[str, float]
    reason: str
    unavailable_features: tuple[str, ...]
    insufficient_data: bool


class RegimeEngine:
    """Classify centralized features into independent trend and stress states."""

    def __init__(
        self,
        feature_config: FeatureConfig | None = None,
        regime_config: RegimeConfig | None = None,
    ):
        self.feature_config = feature_config or load_feature_config()
        self.regime_config = regime_config or load_regime_config()

    @staticmethod
    def _numeric(frame: pd.DataFrame, name: str) -> pd.Series:
        if name not in frame.columns:
            return pd.Series(np.nan, index=frame.index, dtype="float64", name=name)
        return pd.to_numeric(frame[name], errors="coerce").astype("float64")

    def classify_series(self, feature_frame: pd.DataFrame) -> pd.DataFrame:
        """Return causal trend/stress states aligned to every input timestamp.

        Missing or NaN features produce UNKNOWN for the state that needs them.
        Rolling panic thresholds use only the current and preceding observations.
        """
        if not isinstance(feature_frame, pd.DataFrame):
            raise ValueError("RegimeEngine input must be a pandas DataFrame.")
        if not isinstance(feature_frame.index, pd.DatetimeIndex) or feature_frame.index.tz is None:
            raise ValueError("RegimeEngine requires a timezone-aware DatetimeIndex.")
        if str(feature_frame.index.tz) not in {"UTC", "UTC+00:00", "tzutc()", "Etc/UTC", "Etc/GMT", "GMT"}:
            raise ValueError("RegimeEngine requires a UTC DatetimeIndex.")
        if not feature_frame.index.is_monotonic_increasing:
            raise ValueError("RegimeEngine input index must be ascending.")
        if feature_frame.index.has_duplicates:
            raise ValueError("RegimeEngine input index must be unique.")

        index = feature_frame.index
        cfg = self.feature_config
        rcfg = self.regime_config
        fast_name, medium_name, slow_name = (f"ema{cfg.ema_fast}", f"ema{cfg.ema_medium}", f"ema{cfg.ema_slow}")
        atr_name = f"atr{cfg.atr_period}"
        vol_period = rcfg.panic_vol_period
        vol_name = f"realized_vol_{vol_period}"

        close = self._numeric(feature_frame, "close")
        fast = self._numeric(feature_frame, fast_name)
        medium = self._numeric(feature_frame, medium_name)
        slow = self._numeric(feature_frame, slow_name)
        atr = self._numeric(feature_frame, atr_name)
        realized_vol = self._numeric(feature_frame, vol_name)

        trend_valid = np.isfinite(close) & np.isfinite(fast) & np.isfinite(medium) & np.isfinite(slow)
        bull = trend_valid & (close > slow) & (fast >= medium)
        bear = trend_valid & (close < slow) & (medium < slow)
        trend_values = np.full(len(index), "UNKNOWN", dtype=object)
        trend_values[trend_valid] = "NEUTRAL"
        trend_values[bull] = "BULL"
        trend_values[bear] = "BEAR"

        threshold = realized_vol.rolling(
            window=rcfg.panic_vol_lookback, min_periods=1
        ).quantile(rcfg.panic_vol_quantile)
        vol_valid = np.isfinite(realized_vol) & np.isfinite(threshold)
        panic_volatility = vol_valid & (realized_vol > threshold)

        previous_close = close.shift(1)
        shock_valid = np.isfinite(close) & np.isfinite(previous_close) & np.isfinite(atr)
        panic_shock = shock_valid & ((close - previous_close) < (-rcfg.panic_atr_multiple * atr))
        panic = panic_volatility | panic_shock
        stress_valid = panic | (vol_valid & shock_valid)
        stress_values = np.full(len(index), "UNKNOWN", dtype=object)
        stress_values[stress_valid] = "NORMAL"
        stress_values[panic] = "PANIC"

        reasons: list[str] = []
        unavailable: list[tuple[str, ...]] = []
        insufficient: list[bool] = []
        for i in range(len(index)):
            trend_reason = {
                "BULL": "bull_conditions_met",
                "BEAR": "bear_conditions_met",
                "NEUTRAL": "trend_conditions_unmet",
                "UNKNOWN": "trend_features_unavailable",
            }[trend_values[i]]
            if stress_values[i] == "UNKNOWN":
                stress_reason = "stress_features_unavailable"
            elif bool(panic_volatility.iloc[i]) and bool(panic_shock.iloc[i]):
                stress_reason = "panic_volatility_and_atr_shock"
            elif bool(panic_volatility.iloc[i]):
                stress_reason = "panic_high_volatility"
            elif bool(panic_shock.iloc[i]):
                stress_reason = "panic_atr_shock"
            else:
                stress_reason = "normal_no_panic_condition"

            missing: list[str] = []
            for name, values in (("close", close), (fast_name, fast), (medium_name, medium), (slow_name, slow)):
                if not np.isfinite(values.iloc[i]):
                    missing.append(name)
            if not bool(vol_valid.iloc[i]):
                missing.append(vol_name)
            if not bool(shock_valid.iloc[i]):
                if not np.isfinite(close.iloc[i]):
                    if "close" not in missing:
                        missing.append("close")
                elif not np.isfinite(previous_close.iloc[i]):
                    missing.append("previous_close")
                if not np.isfinite(atr.iloc[i]):
                    missing.append(atr_name)
            unavailable.append(tuple(dict.fromkeys(missing)))
            reasons.append(f"trend:{trend_reason}; stress:{stress_reason}")
            insufficient.append(trend_values[i] == "UNKNOWN" or stress_values[i] == "UNKNOWN")

        return pd.DataFrame(
            {
                "trend_regime": trend_values,
                "stress_regime": stress_values,
                "insufficient_data": insufficient,
                "unavailable_features": unavailable,
                "reason": reasons,
            },
            index=index,
        )

    def classify_latest(self, feature_frame: pd.DataFrame) -> RegimeResult:
        """Return a structured state for the latest bar using the series API."""
        history = self.classify_series(feature_frame)
        if history.empty:
            return RegimeResult(
                timestamp=None,
                trend_regime="UNKNOWN",
                stress_regime="UNKNOWN",
                supporting_features={},
                reason="trend:trend_features_unavailable; stress:stress_features_unavailable",
                unavailable_features=("no_observations",),
                insufficient_data=True,
            )
        timestamp = history.index[-1]
        row = feature_frame.iloc[-1]
        cfg = self.feature_config
        names = (
            "close", f"ema{cfg.ema_fast}", f"ema{cfg.ema_medium}", f"ema{cfg.ema_slow}",
            f"atr{cfg.atr_period}",
            f"realized_vol_{self.regime_config.panic_vol_period}",
            f"ema{cfg.ema_medium}_slope",
        )
        supporting: dict[str, float] = {}
        for name in names:
            if name in row.index and pd.notna(row[name]):
                supporting[name] = float(row[name])
        latest = history.iloc[-1]
        return RegimeResult(
            timestamp=timestamp,
            trend_regime=str(latest["trend_regime"]),
            stress_regime=str(latest["stress_regime"]),
            supporting_features=supporting,
            reason=str(latest["reason"]),
            unavailable_features=tuple(latest["unavailable_features"]),
            insufficient_data=bool(latest["insufficient_data"]),
        )


def detect_market_regime(df: pd.DataFrame, config: FeatureConfig | None = None) -> str:
    """Compatibility adapter returning only trend regime (including UNKNOWN)."""
    return RegimeEngine(feature_config=config).classify_latest(df).trend_regime


def is_panic(df: pd.DataFrame, config: FeatureConfig | None = None) -> bool:
    """Compatibility adapter; UNKNOWN stress retains the old false boolean."""
    return RegimeEngine(feature_config=config).classify_latest(df).stress_regime == "PANIC"
