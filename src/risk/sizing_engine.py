"""Deterministic risk and quantity proposals, independent of execution/accounting."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from pathlib import Path
from typing import Any

import yaml

from src.data.config import REPOSITORY_ROOT
from src.strategy.scale_in import ScaleInDecision

DEFAULT_RISK_CONFIG = REPOSITORY_ROOT / "config" / "risk.yaml"
SUPPORTED_ASSETS = frozenset({"SPY", "BTC", "GLD"})
SUPPORTED_ACTIONS = frozenset({"BUY_T1", "BUY_T2", "BUY_T3"})


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number.")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number.")
    return number


@dataclass(frozen=True)
class RiskSizingConfig:
    risk_budget_fraction: float
    stop_atr_multiple: float
    volatility_enabled: bool
    min_volatility_factor: float
    max_volatility_factor: float
    target_vol_by_asset: tuple[tuple[str, float], ...]

    def target_vol_for(self, asset: str) -> float:
        try:
            return dict(self.target_vol_by_asset)[asset]
        except KeyError as exc:
            raise ValueError(f"No target volatility configured for {asset!r}.") from exc


def load_risk_sizing_config(path: str | Path = DEFAULT_RISK_CONFIG) -> RiskSizingConfig:
    """Load and strictly validate the centralized sizing parameters."""
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read risk configuration at {config_path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("risk"), dict) \
            or not isinstance(raw.get("volatility"), dict):
        raise ValueError("risk.yaml must define 'risk' and 'volatility' mappings.")
    risk = raw["risk"]
    volatility = raw["volatility"]
    try:
        risk_budget_fraction = _finite_number(risk["risk_budget_fraction"], "risk_budget_fraction")
        stop_atr_multiple = _finite_number(risk["stop_atr_multiple"], "stop_atr_multiple")
        enabled = volatility["enabled"]
        if type(enabled) is not bool:
            raise ValueError("volatility.enabled must be a boolean.")
        minimum = _finite_number(volatility["min_factor"], "min_factor")
        maximum = _finite_number(volatility["max_factor"], "max_factor")
        target_config = volatility["target_vol"]
    except KeyError as exc:
        raise ValueError(f"risk.yaml is missing required sizing parameter {exc.args[0]!r}.") from exc
    if risk_budget_fraction < 0:
        raise ValueError("risk_budget_fraction cannot be negative.")
    if stop_atr_multiple <= 0:
        raise ValueError("stop_atr_multiple must be positive.")
    if minimum <= 0 or maximum <= 0 or minimum > maximum:
        raise ValueError("Volatility factor bounds must be positive and min_factor <= max_factor.")
    if not isinstance(target_config, dict) or set(target_config) != SUPPORTED_ASSETS:
        raise ValueError(f"target_vol must define exactly {sorted(SUPPORTED_ASSETS)}.")
    targets: list[tuple[str, float]] = []
    for asset in sorted(SUPPORTED_ASSETS):
        target = _finite_number(target_config[asset], f"target_vol.{asset}")
        if target <= 0:
            raise ValueError(f"target_vol.{asset} must be positive.")
        targets.append((asset, target))
    return RiskSizingConfig(
        risk_budget_fraction=risk_budget_fraction,
        stop_atr_multiple=stop_atr_multiple,
        volatility_enabled=enabled,
        min_volatility_factor=minimum,
        max_volatility_factor=maximum,
        target_vol_by_asset=tuple(targets),
    )


@dataclass(frozen=True)
class SizingDecision:
    asset: str
    action: str
    target_weight: float
    incremental_weight: float
    reference_price: float
    atr: float
    risk_budget: float
    stop_distance: float
    realized_vol: float | None
    volatility_factor: float
    allocation_quantity: float
    risk_quantity: float
    vol_adjusted_risk_budget: float
    vol_adjusted_risk_quantity: float
    cash_quantity: float
    final_quantity: float
    binding_constraint: str
    reason: str


def _normalize_asset(asset: str) -> str:
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError("asset must be a non-empty string.")
    normalized = asset.strip().upper()
    return "BTC" if normalized == "BTC-USD" else normalized


class RiskSizingEngine:
    """Turn a scale-in proposal into a quantity proposal; never routes or fills it."""

    def __init__(self, config_path: str | Path = DEFAULT_RISK_CONFIG, *, config: RiskSizingConfig | None = None):
        self.config = config or load_risk_sizing_config(config_path)

    def size(
        self,
        decision: ScaleInDecision,
        *,
        equity: float,
        available_cash: float,
        reference_price: float,
        atr: float,
        realized_vol: float | None,
    ) -> SizingDecision:
        if not isinstance(decision, ScaleInDecision):
            raise TypeError("decision must be a ScaleInDecision.")
        asset = _normalize_asset(decision.asset)
        target_weight = _finite_number(decision.target_weight, "target_weight")
        incremental_weight = _finite_number(decision.incremental_weight, "incremental_weight")
        if target_weight < 0 or incremental_weight < 0:
            raise ValueError("weights cannot be negative.")
        if decision.action not in SUPPORTED_ACTIONS:
            return SizingDecision(
                asset=asset, action="NO_SIZING", target_weight=target_weight,
                incremental_weight=incremental_weight, reference_price=0.0, atr=0.0,
                risk_budget=0.0, stop_distance=0.0, realized_vol=None, volatility_factor=0.0,
                allocation_quantity=0.0, risk_quantity=0.0, vol_adjusted_risk_budget=0.0,
                vol_adjusted_risk_quantity=0.0, cash_quantity=0.0, final_quantity=0.0,
                binding_constraint="NONE", reason="unsupported_action",
            )
        if asset not in SUPPORTED_ASSETS:
            raise ValueError(f"Unsupported asset {decision.asset!r}.")

        values = {
            "equity": _finite_number(equity, "equity"),
            "available_cash": _finite_number(available_cash, "available_cash"),
            "reference_price": _finite_number(reference_price, "reference_price"),
            "atr": _finite_number(atr, "atr"),
            "target_weight": target_weight,
            "incremental_weight": incremental_weight,
        }
        if values["equity"] <= 0:
            raise ValueError("equity must be positive.")
        if values["available_cash"] < 0:
            raise ValueError("available_cash cannot be negative.")
        if values["reference_price"] <= 0:
            raise ValueError("reference_price must be positive.")
        if values["atr"] <= 0:
            raise ValueError("atr must be positive.")
        if values["target_weight"] < 0 or values["incremental_weight"] < 0:
            raise ValueError("weights cannot be negative.")

        realized: float | None = None
        if self.config.volatility_enabled:
            if realized_vol is None:
                raise ValueError("realized_vol is required when volatility adjustment is enabled.")
            realized = _finite_number(realized_vol, "realized_vol")
            if realized <= 0:
                raise ValueError("realized_vol must be positive when volatility adjustment is enabled.")
            target_vol = self.config.target_vol_for(asset)
            raw_factor = target_vol / realized
            volatility_factor = min(self.config.max_volatility_factor,
                                    max(self.config.min_volatility_factor, raw_factor))
        else:
            volatility_factor = 1.0

        risk_budget = values["equity"] * self.config.risk_budget_fraction
        stop_distance = self.config.stop_atr_multiple * values["atr"]
        allocation_quantity = (values["equity"] * values["incremental_weight"]
                               / values["reference_price"])
        risk_quantity = risk_budget / stop_distance
        adjusted_budget = risk_budget * volatility_factor
        adjusted_risk_quantity = adjusted_budget / stop_distance
        cash_quantity = values["available_cash"] / values["reference_price"]
        candidates = {
            "ALLOCATION": allocation_quantity,
            "RISK": adjusted_risk_quantity,
            "CASH": cash_quantity,
        }
        # Stable tie precedence is part of the API contract: ALLOCATION, then RISK, then CASH.
        binding = min(candidates, key=candidates.get)
        final_quantity = candidates[binding]
        action = decision.action if final_quantity > 0 else "NO_SIZING"
        reason = "sized" if action != "NO_SIZING" else "non_positive_quantity"
        return SizingDecision(
            asset=asset, action=action, target_weight=values["target_weight"],
            incremental_weight=values["incremental_weight"], reference_price=values["reference_price"],
            atr=values["atr"], risk_budget=risk_budget, stop_distance=stop_distance,
            realized_vol=realized, volatility_factor=volatility_factor,
            allocation_quantity=allocation_quantity, risk_quantity=risk_quantity,
            vol_adjusted_risk_budget=adjusted_budget,
            vol_adjusted_risk_quantity=adjusted_risk_quantity, cash_quantity=cash_quantity,
            final_quantity=final_quantity, binding_constraint=binding, reason=reason,
        )
