"""Configurable scale-in proposals and fill-derived position transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from numbers import Real
from pathlib import Path
from typing import Any

import yaml

from src.data.config import REPOSITORY_ROOT
from src.strategy.signals import SignalResult
from src.strategy.state_machine import PositionState

DEFAULT_STRATEGY_CONFIG = REPOSITORY_ROOT / "config" / "strategy.yaml"
SUPPORTED_ASSETS = frozenset({"SPY", "BTC", "GLD"})
TIER_NAMES = ("T1", "T2", "T3")


@dataclass(frozen=True)
class ScaleInTier:
    name: str
    z_atr: float
    cumulative_weight: float


def _number(value: Any) -> bool:
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def load_scale_in_config(path: str | Path = DEFAULT_STRATEGY_CONFIG) -> dict[str, tuple[ScaleInTier, ...]]:
    """Load and strictly validate all configured three-tier asset schedules."""
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read strategy configuration at {config_path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("strategy"), dict):
        raise ValueError("strategy.yaml must define a 'strategy' mapping.")
    scale_in = raw["strategy"].get("scale_in")
    if not isinstance(scale_in, dict):
        raise ValueError("strategy.yaml must define a 'strategy.scale_in' mapping.")
    if set(scale_in) != SUPPORTED_ASSETS:
        missing = sorted(SUPPORTED_ASSETS - set(scale_in))
        unknown = sorted((str(asset) for asset in set(scale_in) - SUPPORTED_ASSETS))
        raise ValueError(f"Scale-in assets must be {sorted(SUPPORTED_ASSETS)}; missing={missing}, unknown={unknown}.")

    parsed: dict[str, tuple[ScaleInTier, ...]] = {}
    for asset in sorted(SUPPORTED_ASSETS):
        asset_settings = scale_in[asset]
        if not isinstance(asset_settings, dict) or set(asset_settings) != {"tiers"}:
            raise ValueError(f"{asset} must define only a tiers list.")
        raw_tiers = asset_settings["tiers"]
        if not isinstance(raw_tiers, list):
            raise ValueError(f"{asset}.tiers must be a list.")
        by_name: dict[str, ScaleInTier] = {}
        for tier in raw_tiers:
            if not isinstance(tier, dict) or set(tier) != {"name", "z_atr", "cumulative_weight"}:
                raise ValueError(f"Every {asset} tier must define name, z_atr, and cumulative_weight.")
            name = tier["name"]
            if name not in TIER_NAMES:
                raise ValueError(f"Unknown {asset} tier name: {name!r}.")
            if name in by_name:
                raise ValueError(f"Duplicate {asset} tier {name}.")
            if not _number(tier["z_atr"]):
                raise ValueError(f"{asset} {name}.z_atr must be a finite number.")
            if not _number(tier["cumulative_weight"]):
                raise ValueError(f"{asset} {name}.cumulative_weight must be a finite number.")
            by_name[name] = ScaleInTier(name, float(tier["z_atr"]), float(tier["cumulative_weight"]))
        if set(by_name) != set(TIER_NAMES):
            missing = sorted(set(TIER_NAMES) - set(by_name))
            raise ValueError(f"{asset} must define T1, T2, and T3 exactly once; missing={missing}.")
        tiers = tuple(by_name[name] for name in TIER_NAMES)
        if not tiers[0].z_atr > tiers[1].z_atr > tiers[2].z_atr:
            raise ValueError(f"{asset} Z_ATR thresholds must become progressively more extreme (T1 > T2 > T3).")
        weights = tuple(tier.cumulative_weight for tier in tiers)
        if not 0 < weights[0] < weights[1] < weights[2] <= 1:
            raise ValueError(f"{asset} cumulative weights must satisfy 0 < T1 < T2 < T3 <= 1.")
        parsed[asset] = tiers
    return parsed


@dataclass(frozen=True)
class ScaleInDecision:
    action: str
    target_tier: str | None
    incremental_weight: float
    target_weight: float
    reason: str
    z_atr: float | None
    previous_filled_z_atr: float | None
    asset: str
    signal_timestamp: datetime | None


def _normalize_asset(asset: str) -> str:
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError("asset must be a non-empty string.")
    normalized = asset.strip().upper()
    return "BTC" if normalized == "BTC-USD" else normalized


class ScaleInEngine:
    """Propose one tier at a time; mutate position state only after an explicit fill."""

    def __init__(
        self,
        ticker: str,
        config_path: str | Path = DEFAULT_STRATEGY_CONFIG,
        initial_state: str = "FLAT",
        last_z_atr: float = 0.0,
        tiers: tuple[ScaleInTier, ...] | None = None,
        disable_additional_entries: bool = False,
        regime_filter_enabled: bool = True,
    ):
        self.ticker = ticker
        self.asset = _normalize_asset(ticker)
        all_tiers = load_scale_in_config(config_path)
        if self.asset not in all_tiers:
            raise ValueError(f"No scale-in tier configuration for asset {ticker!r}.")
        self._tiers = tuple(tiers) if tiers is not None else all_tiers[self.asset]
        self.disable_additional_entries = bool(disable_additional_entries)
        self.regime_filter_enabled = bool(regime_filter_enabled)
        if not self._tiers or self._tiers[0].name != "T1":
            raise ValueError("Scale-in override must retain T1.")
        if any(t.name != f"T{i + 1}" for i, t in enumerate(self._tiers)):
            raise ValueError("Scale-in tiers must be consecutive beginning with T1.")
        # Preserve the original public schedule shape for legacy callers.
        self.tiers = [
            {"name": tier.name, "z_atr": tier.z_atr, "cumulative_weight": tier.cumulative_weight}
            for tier in self._tiers
        ]
        # Compatibility state is deliberately isolated from the fill-based API.
        self.state = initial_state
        self.last_z_atr = last_z_atr

    def _decision(
        self,
        action: str,
        tier: ScaleInTier | None,
        state: PositionState,
        signal: SignalResult | None,
        reason: str,
        z_atr: float | None,
    ) -> ScaleInDecision:
        return ScaleInDecision(
            action=action,
            target_tier=tier.name if tier else None,
            incremental_weight=(tier.cumulative_weight - state.position_weight) if tier else 0.0,
            target_weight=tier.cumulative_weight if tier else state.position_weight,
            reason=reason,
            z_atr=z_atr,
            previous_filled_z_atr=state.last_filled_z_atr,
            asset=self.asset,
            signal_timestamp=signal.timestamp if signal is not None else None,
        )

    def _validate_state_for_asset(self, state: PositionState) -> None:
        if not isinstance(state, PositionState):
            raise TypeError("state must be a PositionState.")
        state.validate()
        if state.cycle_active:
            expected = next(tier.cumulative_weight for tier in self._tiers if tier.name == state.last_tier)
            if not math.isclose(state.position_weight, expected, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError("PositionState weight does not match its filled tier configuration.")

    def evaluate(self, signal: SignalResult, state: PositionState) -> ScaleInDecision:
        """Evaluate one SignalResult without modifying the supplied post-fill state."""
        self._validate_state_for_asset(state)
        if not isinstance(signal, SignalResult):
            raise TypeError("signal must be a SignalResult.")
        if _normalize_asset(signal.asset) != self.asset:
            return self._decision("NO_ACTION", None, state, signal, "asset_mismatch", signal.z_atr)
        z_atr = signal.z_atr

        if signal.signal_state not in {"UNKNOWN", "NO_SIGNAL", "WATCH", "ENTRY_CANDIDATE", "BLOCKED"}:
            return self._decision("NO_ACTION", None, state, signal, "signal_unknown", z_atr)
        if signal.signal_state == "UNKNOWN" or signal.insufficient_data or signal.unavailable_features:
            return self._decision("NO_ACTION", None, state, signal, "signal_unknown", z_atr)
        if self.regime_filter_enabled and signal.trend_regime == "UNKNOWN":
            return self._decision("NO_ACTION", None, state, signal, "trend_unknown", z_atr)
        if signal.stress_regime == "UNKNOWN":
            return self._decision("NO_ACTION", None, state, signal, "stress_unknown", z_atr)
        if signal.stress_regime not in {"NORMAL", "PANIC"}:
            return self._decision("NO_ACTION", None, state, signal, "stress_unknown", z_atr)
        if not _number(z_atr):
            return self._decision("NO_ACTION", None, state, signal, "z_atr_unavailable", None)
        z_atr = float(z_atr)
        if signal.stress_regime == "PANIC":
            return self._decision("NO_ACTION", None, state, signal, "panic_blocked", float(z_atr))
        if self.regime_filter_enabled and signal.trend_regime != "BULL":
            return self._decision("NO_ACTION", None, state, signal, "trend_regime_not_eligible", float(z_atr))

        if not state.cycle_active:
            t1 = self._tiers[0]
            if signal.signal_state != "ENTRY_CANDIDATE" or signal.entry_candidate is not True:
                return self._decision("NO_ACTION", None, state, signal, "entry_candidate_required", float(z_atr))
            if z_atr > t1.z_atr:
                return self._decision("NO_ACTION", None, state, signal, "tier_1_threshold_not_met", float(z_atr))
            return self._decision("BUY_T1", t1, state, signal, "tier_1_entry", float(z_atr))

        if self.disable_additional_entries:
            return self._decision("NO_ACTION", None, state, signal, "additional_entries_disabled", float(z_atr))

        if state.last_tier == "T3":
            return self._decision("NO_ACTION", None, state, signal, "tier_3_already_active", float(z_atr))

        next_tier_index = 1 if state.last_tier == "T1" else 2
        tier = self._tiers[next_tier_index]
        if z_atr > tier.z_atr:
            return self._decision("NO_ACTION", None, state, signal, f"tier_{next_tier_index + 1}_threshold_not_met", float(z_atr))
        if z_atr >= state.last_filled_z_atr:
            return self._decision("NO_ACTION", None, state, signal, "z_atr_not_deeper_than_last_fill", float(z_atr))
        return self._decision(
            f"BUY_T{next_tier_index + 1}", tier, state, signal,
            f"tier_{next_tier_index + 1}_scale_in", float(z_atr),
        )

    def apply_fill(
        self,
        state: PositionState,
        decision: ScaleInDecision,
        fill_price: float,
        fill_timestamp: datetime,
    ) -> PositionState:
        """Return a new state after validating and applying the supplied actual fill."""
        self._validate_state_for_asset(state)
        if not isinstance(decision, ScaleInDecision) or decision.action not in {"BUY_T1", "BUY_T2", "BUY_T3"}:
            raise ValueError("Only BUY_T1, BUY_T2, or BUY_T3 decisions can be filled.")
        if decision.asset != self.asset:
            raise ValueError("Decision asset does not match this ScaleInEngine.")
        if isinstance(fill_price, bool) or not isinstance(fill_price, Real) \
                or not math.isfinite(float(fill_price)) or fill_price <= 0:
            raise ValueError("fill_price must be finite and positive.")
        if not isinstance(fill_timestamp, datetime) or fill_timestamp.tzinfo is None \
                or fill_timestamp.utcoffset() is None:
            raise ValueError("fill_timestamp must be a timezone-aware timestamp.")
        if not _number(decision.z_atr):
            raise ValueError("A fillable decision must contain a finite z_atr.")
        if not _number(decision.target_weight) or not _number(decision.incremental_weight):
            raise ValueError("Decision weights must be finite numbers.")

        tier_number = int(decision.action[-1])
        expected_tier = self._tiers[tier_number - 1]
        expected_state = {1: "FLAT", 2: "T1_ACTIVE", 3: "T2_ACTIVE"}[tier_number]
        if state.tier_state != expected_state:
            raise ValueError(f"{decision.action} cannot be applied from {state.tier_state}.")
        if decision.target_tier != expected_tier.name:
            raise ValueError("Decision target tier does not match its action.")
        if not math.isclose(decision.target_weight, expected_tier.cumulative_weight, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("Decision target weight does not match the configured tier target.")
        expected_increment = expected_tier.cumulative_weight - state.position_weight
        if not math.isclose(decision.incremental_weight, expected_increment, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("Decision incremental weight does not match the configured tier increment.")
        if decision.previous_filled_z_atr != state.last_filled_z_atr:
            raise ValueError("Decision was evaluated against a different filled position state.")
        if decision.z_atr > expected_tier.z_atr:
            raise ValueError("Decision Z_ATR does not meet the configured tier threshold.")
        if tier_number > 1 and decision.z_atr >= state.last_filled_z_atr:
            raise ValueError("A scale-in fill requires deeper Z_ATR than the previous fill.")

        price = float(fill_price)
        target_weight = expected_tier.cumulative_weight
        increment = expected_increment
        if state.cycle_active:
            average_price = (
                state.position_weight * state.average_entry_price + increment * price
            ) / target_weight
            anchor = state.anchor_price
            entry_timestamp = state.entry_timestamp
            lowest = min(state.lowest_price, price)
        else:
            average_price = price
            anchor = price
            entry_timestamp = fill_timestamp
            lowest = price
        return PositionState(
            cycle_active=True,
            last_tier=expected_tier.name,
            anchor_price=anchor,
            lowest_price=lowest,
            position_weight=target_weight,
            average_entry_price=average_price,
            entry_timestamp=entry_timestamp,
            last_filled_z_atr=float(decision.z_atr),
            partial_sell_stage=0,
        )

    @staticmethod
    def reset_cycle(state: PositionState) -> PositionState:
        if not isinstance(state, PositionState):
            raise TypeError("state must be a PositionState.")
        state.validate()
        return PositionState()

    def get_action(self, d_atr: float, regime: str, is_panic: bool) -> tuple[str, str]:
        """Legacy mutating adapter retained for run_eod.py and existing callers.

        New position logic must use evaluate() and apply_fill(); this method
        preserves the old close-observation state mutation semantics.
        """
        if regime == "BEAR" or is_panic:
            return "HOLD", self.state

        if self.state == "FLAT":
            tier = self._tiers[0]
            if d_atr <= tier.z_atr:
                self.state = "T1_ACTIVE"
                self.last_z_atr = d_atr
                return "BUY_T1", self.state
        elif self.state == "T1_ACTIVE":
            tier = self._tiers[1]
            if d_atr <= tier.z_atr and d_atr < self.last_z_atr:
                self.state = "T2_ACTIVE"
                self.last_z_atr = d_atr
                return "BUY_T2", self.state
        elif self.state == "T2_ACTIVE":
            tier = self._tiers[2]
            if d_atr <= tier.z_atr and d_atr < self.last_z_atr:
                self.state = "T3_ACTIVE"
                self.last_z_atr = d_atr
                return "BUY_T3", self.state
        return "HOLD", self.state
