"""Deterministic, point-in-time opportunity signal classification.

Thresholds are provisional research hypotheses, not financially validated rules.
The engine consumes centralized Feature Engine outputs and Regime Engine states;
it does not calculate indicators, position sizes, or portfolio actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.data.config import REPOSITORY_ROOT
from src.features.config import FeatureConfig
from src.features.regime import RegimeEngine

DEFAULT_SIGNAL_CONFIG = REPOSITORY_ROOT / "config" / "signals.yaml"


@dataclass(frozen=True)
class SignalConfig:
    rsi2_entry_threshold: float = 10.0
    reversal_close_location_min: float = 0.60
    asset_z_atr_thresholds: tuple[tuple[str, float], ...] = (
        ("SPY", -1.50), ("BTC", -1.75), ("GLD", -1.50),
    )
    eligible_trend_regimes: tuple[str, ...] = ("BULL",)
    block_panic: bool = True
    regime_filter_enabled: bool = True
    rsi_filter_enabled: bool = True
    reversal_confirmation_enabled: bool = True

    def __post_init__(self) -> None:
        for name in ("rsi2_entry_threshold", "reversal_close_location_min"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
                raise ValueError(f"{name} must be a finite number.")
        if self.rsi2_entry_threshold < 0 or self.rsi2_entry_threshold > 100:
            raise ValueError("rsi2_entry_threshold must be between 0 and 100.")
        if self.reversal_close_location_min < 0 or self.reversal_close_location_min > 1:
            raise ValueError("reversal_close_location_min must be between 0 and 1.")
        thresholds = dict(self.asset_z_atr_thresholds)
        if not thresholds or len(thresholds) != len(self.asset_z_atr_thresholds):
            raise ValueError("asset_z_atr_thresholds must contain unique assets.")
        try:
            valid_thresholds = all(
                isinstance(asset, str) and bool(asset)
                and isinstance(value, (int, float)) and not isinstance(value, bool)
                and np.isfinite(value)
                for asset, value in thresholds.items()
            )
        except (TypeError, ValueError):
            valid_thresholds = False
        if not valid_thresholds:
            raise ValueError("Asset names and z_atr thresholds must be valid and finite.")
        if not self.eligible_trend_regimes or any(
            value not in {"BULL", "NEUTRAL", "BEAR"} for value in self.eligible_trend_regimes
        ):
            raise ValueError("eligible_trend_regimes must contain known trend states.")
        if type(self.block_panic) is not bool:
            raise ValueError("block_panic must be a boolean.")
        for name in ("regime_filter_enabled", "rsi_filter_enabled", "reversal_confirmation_enabled"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean.")

    @property
    def z_atr_thresholds(self) -> dict[str, float]:
        return dict(self.asset_z_atr_thresholds)


def load_signal_config(path: str | Path = DEFAULT_SIGNAL_CONFIG) -> SignalConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read signal configuration at {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("signals.yaml must contain a mapping at the root.")
    values = raw.get("signals", {})
    if not isinstance(values, dict):
        raise ValueError("signals.yaml must define a 'signals' mapping.")
    values = dict(values)
    assets = values.pop("assets", {})
    regime = values.pop("regime", {})
    stress = values.pop("stress", {})
    if not isinstance(assets, dict) or not isinstance(regime, dict) or not isinstance(stress, dict):
        raise ValueError("signals assets, regime, and stress sections must be mappings.")
    if values.keys() - {"rsi2_entry_threshold", "reversal_close_location_min"}:
        raise ValueError("Unknown signal configuration keys.")
    if set(regime) - {"eligible_trend_regimes"} or set(stress) - {"block_panic"}:
        raise ValueError("Unknown signal regime or stress configuration keys.")
    try:
        thresholds = tuple(
            (asset, settings["z_atr_entry_threshold"])
            for asset, settings in assets.items()
            if isinstance(settings, dict) and set(settings) == {"z_atr_entry_threshold"}
        )
        if len(thresholds) != len(assets):
            raise ValueError("Each asset must define only z_atr_entry_threshold.")
        return SignalConfig(
            rsi2_entry_threshold=values.pop("rsi2_entry_threshold", 10),
            reversal_close_location_min=values.pop("reversal_close_location_min", 0.60),
            asset_z_atr_thresholds=thresholds,
            eligible_trend_regimes=tuple(regime.get("eligible_trend_regimes", ("BULL",))),
            block_panic=stress.get("block_panic", True),
        )
    except (TypeError, KeyError) as exc:
        raise ValueError(f"Invalid signal configuration: {exc}") from exc


@dataclass(frozen=True)
class SignalResult:
    timestamp: pd.Timestamp | None
    asset: str
    signal_state: str
    trend_regime: str
    stress_regime: str
    z_atr: float | None
    rsi2: float | None
    z_atr_extreme: bool | None
    rsi2_extreme: bool | None
    extreme_condition: bool | None
    reversal_confirmed: bool | None
    close_location: float | None
    previous_close: float | None
    realized_vol_20: float | None
    regime_eligible: bool | None
    stress_blocked: bool | None
    entry_candidate: bool
    reason: str
    unavailable_features: tuple[str, ...]
    insufficient_data: bool


class SignalEngine:
    """Classify opportunity components from feature and regime engine outputs."""

    def __init__(
        self,
        config: SignalConfig | None = None,
        regime_engine: RegimeEngine | None = None,
        feature_config: FeatureConfig | None = None,
    ):
        self.config = config or load_signal_config()
        self.regime_engine = regime_engine or RegimeEngine(feature_config=feature_config)
        self.feature_config = self.regime_engine.feature_config

    @staticmethod
    def _value(frame: pd.DataFrame, column: str, position: int) -> float | None:
        if column not in frame.columns:
            return None
        try:
            value = float(pd.to_numeric(pd.Series([frame[column].iloc[position]]), errors="coerce").iloc[0])
        except (TypeError, ValueError, OverflowError):
            return None
        return value if np.isfinite(value) else None

    def classify_series(self, feature_frame: pd.DataFrame, asset: str) -> pd.DataFrame:
        """Return signals aligned to bars, with no use of later observations."""
        asset = asset.upper()
        threshold_asset = "BTC" if asset == "BTC-USD" else asset
        if threshold_asset not in self.config.z_atr_thresholds:
            raise ValueError(f"No provisional z_atr threshold configured for asset {asset!r}.")
        regimes = self.regime_engine.classify_series(feature_frame)
        results = [self._classify_at(feature_frame, regimes, asset, threshold_asset, i)
                   for i in range(len(feature_frame))]
        columns = list(SignalResult.__dataclass_fields__)
        return pd.DataFrame(
            [{name: getattr(result, name) for name in columns} for result in results],
            index=feature_frame.index, columns=columns, dtype=object,
        )

    def classify_latest(self, feature_frame: pd.DataFrame, asset: str) -> SignalResult:
        """Return the final point-in-time signal, derived from the series API."""
        history = self.classify_series(feature_frame, asset)
        if history.empty:
            return SignalResult(None, asset.upper(), "UNKNOWN", "UNKNOWN", "UNKNOWN", None, None,
                                None, None, None, None, None, None, None, None, None, False,
                                "required_features_unavailable", ("no_observations",), True)
        row = history.iloc[-1]
        return SignalResult(**{name: row[name] for name in SignalResult.__dataclass_fields__})

    def _classify_at(
        self, frame: pd.DataFrame, regimes: pd.DataFrame, asset: str, threshold_asset: str, i: int
    ) -> SignalResult:
        z_atr = self._value(frame, "z_atr", i)
        rsi2 = self._value(frame, f"rsi{self.feature_config.rsi_fast_period}", i)
        close = self._value(frame, "close", i)
        high = self._value(frame, "high", i)
        low = self._value(frame, "low", i)
        previous_close = self._value(frame, "close", i - 1) if i > 0 else None
        realized_vol = self._value(frame, "realized_vol_20", i)
        trend = str(regimes.iloc[i]["trend_regime"])
        stress = str(regimes.iloc[i]["stress_regime"])

        unavailable: list[str] = []
        required_values = [("z_atr", z_atr), ("close", close), ("high", high), ("low", low)]
        if self.config.rsi_filter_enabled:
            required_values.append((f"rsi{self.feature_config.rsi_fast_period}", rsi2))
        if self.config.reversal_confirmation_enabled:
            required_values.append(("previous_close", previous_close))
        for name, value in required_values:
            if value is None:
                unavailable.append(name)
        if trend == "UNKNOWN" and self.config.regime_filter_enabled:
            unavailable.extend(regimes.iloc[i]["unavailable_features"])
        if stress == "UNKNOWN":
            unavailable.extend(regimes.iloc[i]["unavailable_features"])

        z_extreme = None if z_atr is None else bool(z_atr <= self.config.z_atr_thresholds[threshold_asset])
        rsi_extreme = True if not self.config.rsi_filter_enabled else (None if rsi2 is None else bool(rsi2 <= self.config.rsi2_entry_threshold))
        extreme = None if z_extreme is None or rsi_extreme is None else bool(z_extreme and rsi_extreme)
        close_location = None
        if close is not None and high is not None and low is not None and high != low:
            close_location = (close - low) / (high - low)
        elif self.config.reversal_confirmation_enabled and close is not None and high is not None and low is not None:
            unavailable.append("close_location")
        reversal = True if not self.config.reversal_confirmation_enabled else (None if close_location is None or close is None or previous_close is None else bool(
            close > previous_close and close_location >= self.config.reversal_close_location_min
        ))

        regime_eligible = True if not self.config.regime_filter_enabled else (None if trend == "UNKNOWN" else bool(trend in self.config.eligible_trend_regimes))
        stress_blocked = None if stress == "UNKNOWN" else bool(self.config.block_panic and stress == "PANIC")
        enough = not unavailable and extreme is not None and reversal is not None \
            and regime_eligible is not None and stress_blocked is not None
        entry = bool(enough and regime_eligible and extreme and reversal and not stress_blocked)

        if not enough:
            state, reason = "UNKNOWN", "required_features_unavailable"
        elif entry:
            state, reason = "ENTRY_CANDIDATE", "entry_candidate"
        elif stress_blocked and regime_eligible and extreme and reversal:
            state, reason = "BLOCKED", "blocked_by_panic"
        elif extreme and not reversal:
            state, reason = "WATCH", "extreme_condition_met_waiting_reversal"
        elif not regime_eligible:
            state, reason = "NO_SIGNAL", "trend_regime_not_eligible"
        elif not extreme:
            state, reason = "NO_SIGNAL", "extreme_condition_not_met"
        elif stress_blocked:
            state, reason = "NO_SIGNAL", "blocked_by_panic"
        else:
            state, reason = "NO_SIGNAL", "extreme_condition_not_met"

        return SignalResult(
            timestamp=frame.index[i], asset=asset, signal_state=state,
            trend_regime=trend, stress_regime=stress, z_atr=z_atr, rsi2=rsi2,
            z_atr_extreme=z_extreme, rsi2_extreme=rsi_extreme,
            extreme_condition=extreme, reversal_confirmed=reversal,
            close_location=close_location, previous_close=previous_close,
            realized_vol_20=realized_vol, regime_eligible=regime_eligible,
            stress_blocked=stress_blocked, entry_candidate=entry, reason=reason,
            unavailable_features=tuple(dict.fromkeys(unavailable)), insufficient_data=not enough,
        )
