"""Deterministic exit proposals, separate from fills and accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from numbers import Real
from pathlib import Path
from typing import Any

import yaml

from src.data.config import REPOSITORY_ROOT

DEFAULT_EXIT_CONFIG = REPOSITORY_ROOT / "config" / "exits.yaml"


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number.")
    return number


def _optional_finite(value: Any, name: str) -> float | None:
    return None if value is None else _finite(value, name)


def _aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")


@dataclass(frozen=True)
class ExitConfig:
    structural_stop_enabled: bool
    stop_atr_multiple: float
    time_stop_enabled: bool
    max_cycle_days: float
    partial_recovery_enabled: bool
    z_atr_threshold: float
    rsi2_threshold: float
    partial_sell_fraction: float


def load_exit_config(path: str | Path = DEFAULT_EXIT_CONFIG) -> ExitConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read exit configuration at {config_path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("exits"), dict):
        raise ValueError("exits.yaml must define an 'exits' mapping.")
    try:
        stop, timer, partial = raw["exits"]["structural_stop"], raw["exits"]["time_stop"], raw["exits"]["partial_recovery"]
        enabled = (stop["enabled"], timer["enabled"], partial["enabled"])
        if any(type(value) is not bool for value in enabled):
            raise ValueError("Exit enabled settings must be booleans.")
        result = ExitConfig(
            enabled[0], _finite(stop["atr_multiple"], "atr_multiple"),
            enabled[1], _finite(timer["max_cycle_days"], "max_cycle_days"),
            enabled[2], _finite(partial["z_atr_threshold"], "z_atr_threshold"),
            _finite(partial["rsi2_threshold"], "rsi2_threshold"),
            _finite(partial["fraction"], "partial_sell_fraction"),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Exit configuration is missing or malformed: {exc}") from exc
    if result.stop_atr_multiple <= 0 or result.max_cycle_days <= 0:
        raise ValueError("Stop ATR multiple and maximum cycle days must be positive.")
    if not 0 < result.partial_sell_fraction <= 1:
        raise ValueError("partial_sell_fraction must be in (0, 1].")
    return result


@dataclass(frozen=True)
class ExitDecision:
    action: str
    reason: str
    asset: str
    quantity_fraction: float
    reference_price: float
    signal_timestamp: datetime
    z_atr: float | None
    rsi2: float | None
    ema20: float | None
    days_in_cycle: float
    position_quantity: float
    unavailable_inputs: tuple[str, ...] = ()


class ExitEngine:
    """Evaluate supplied point-in-time observations and propose at most one exit."""

    def __init__(self, config_path: str | Path = DEFAULT_EXIT_CONFIG, *, config: ExitConfig | None = None):
        self.config = config or load_exit_config(config_path)

    def evaluate(
        self, *, asset: str, position_quantity: float, anchor_price: float,
        entry_timestamp: datetime, entry_atr: float | None,
        current_timestamp: datetime, current_price: float, z_atr: float | None,
        rsi2: float | None, partial_sell_stage: int, ema20: float | None = None,
    ) -> ExitDecision:
        if not isinstance(asset, str) or not asset.strip():
            raise ValueError("asset must be a non-empty string.")
        quantity = _finite(position_quantity, "position_quantity")
        anchor = _finite(anchor_price, "anchor_price")
        price = _finite(current_price, "current_price")
        if anchor <= 0 or price <= 0:
            raise ValueError("anchor_price and current_price must be positive.")
        _aware(entry_timestamp, "entry_timestamp")
        _aware(current_timestamp, "current_timestamp")
        if entry_timestamp > current_timestamp:
            raise ValueError("entry_timestamp must be <= current_timestamp.")
        if type(partial_sell_stage) is not int or partial_sell_stage < 0:
            raise ValueError("partial_sell_stage must be a non-negative integer.")
        atr = _optional_finite(entry_atr, "entry_atr")
        z = _optional_finite(z_atr, "z_atr")
        rsi = _optional_finite(rsi2, "rsi2")
        ema = _optional_finite(ema20, "ema20")
        age = (current_timestamp - entry_timestamp).total_seconds() / 86400
        unavailable: list[str] = []

        action, reason, fraction = "HOLD", "NO_EXIT_CONDITION", 0.0
        if quantity <= 0:
            reason = "NO_POSITION"
        else:
            if self.config.structural_stop_enabled and atr is None:
                unavailable.append("entry_atr")
            stop_triggered = self.config.structural_stop_enabled and atr is not None \
                and price <= anchor - self.config.stop_atr_multiple * atr
            if stop_triggered:
                action, reason, fraction = "FULL_EXIT", "STRUCTURAL_STOP", 1.0
            elif self.config.time_stop_enabled and age >= self.config.max_cycle_days:
                action, reason, fraction = "FULL_EXIT", "TIME_STOP", 1.0
            elif self.config.partial_recovery_enabled and (z is None or rsi is None):
                if z is None:
                    unavailable.append("z_atr")
                if rsi is None:
                    unavailable.append("rsi2")
            elif self.config.partial_recovery_enabled and partial_sell_stage == 0 \
                    and z >= self.config.z_atr_threshold and rsi > self.config.rsi2_threshold:
                action, reason, fraction = "PARTIAL_SELL", "PARTIAL_RECOVERY", self.config.partial_sell_fraction
        return ExitDecision(action, reason, asset.strip().upper(), fraction, price,
                            current_timestamp, z, rsi, ema, age, quantity, tuple(unavailable))


def should_reset_cycle(decision: ExitDecision, *, position_quantity_after_fill: float) -> bool:
    """Cycle reset is permitted only after a FULL_EXIT has actually flattened the holding."""
    if not isinstance(decision, ExitDecision):
        raise TypeError("decision must be an ExitDecision.")
    remaining = _finite(position_quantity_after_fill, "position_quantity_after_fill")
    if remaining < 0:
        raise ValueError("position_quantity_after_fill cannot be negative.")
    return decision.action == "FULL_EXIT" and remaining == 0
