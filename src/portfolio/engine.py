"""Deterministic portfolio-level constraints for per-asset sizing proposals.

This layer approves quantities only. It has no market-data, accounting, order,
or execution dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from numbers import Real
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from src.data.config import REPOSITORY_ROOT
from src.risk.sizing_engine import SizingDecision

DEFAULT_PORTFOLIO_CONFIG = REPOSITORY_ROOT / "config" / "portfolio.yaml"
ASSETS = frozenset({"SPY", "BTC", "GLD"})


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number.")
    return result


def _asset(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("asset must be a non-empty string.")
    normalized = value.strip().upper()
    normalized = "BTC" if normalized == "BTC-USD" else normalized
    if normalized not in ASSETS:
        raise ValueError(f"Unsupported asset {value!r}.")
    return normalized


@dataclass(frozen=True)
class PortfolioConfig:
    max_gross_exposure: float
    minimum_cash_reserve: float
    max_asset_weight: tuple[tuple[str, float], ...]
    priority_order: tuple[str, ...]

    def __post_init__(self) -> None:
        gross = _number(self.max_gross_exposure, "max_gross_exposure")
        reserve = _number(self.minimum_cash_reserve, "minimum_cash_reserve")
        if not 0 <= gross <= 1 or not 0 <= reserve <= 1:
            raise ValueError("Gross exposure and cash reserve must be in [0, 1].")
        weights = dict(self.max_asset_weight)
        if set(weights) != ASSETS:
            raise ValueError(f"max_asset_weight must define exactly {sorted(ASSETS)}.")
        for asset, weight in weights.items():
            if not 0 <= _number(weight, f"max_asset_weight.{asset}") <= 1:
                raise ValueError("Asset limits must be in [0, 1].")
        order = tuple(_asset(a) for a in self.priority_order)
        if len(order) != len(set(order)) or set(order) != ASSETS:
            raise ValueError("priority_order must list SPY, BTC, and GLD exactly once.")


def load_portfolio_config(path: str | Path = DEFAULT_PORTFOLIO_CONFIG) -> PortfolioConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        section = raw["portfolio"]["allocation_constraints"]
        gross = section["max_gross_exposure"]
        reserve = section["minimum_cash_reserve"]
        limits = section["max_asset_weight"]
        order = section["priority_order"]
    except (OSError, yaml.YAMLError, TypeError, KeyError) as exc:
        raise ValueError(f"Invalid portfolio configuration at {config_path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("portfolio"), dict):
        raise ValueError("portfolio.yaml must define a portfolio mapping.")
    if not isinstance(limits, dict) or set(limits) != ASSETS:
        raise ValueError(f"max_asset_weight must define exactly {sorted(ASSETS)}.")
    return PortfolioConfig(_number(gross, "max_gross_exposure"),
                           _number(reserve, "minimum_cash_reserve"),
                           tuple((asset, _number(limits[asset], f"max_asset_weight.{asset}"))
                                 for asset in sorted(ASSETS)), tuple(order))


@dataclass(frozen=True)
class PortfolioHolding:
    asset: str
    quantity: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _asset(self.asset))
        quantity = _number(self.quantity, "holding quantity")
        if quantity < 0:
            raise ValueError("Holding quantity cannot be negative.")
        object.__setattr__(self, "quantity", quantity)


@dataclass(frozen=True)
class PortfolioSnapshot:
    timestamp: datetime
    equity: float
    available_cash: float
    holdings: Mapping[str, float] | tuple[PortfolioHolding, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware.")
        equity = _number(self.equity, "equity")
        cash = _number(self.available_cash, "available_cash")
        if equity < 0 or cash < 0 or cash > equity:
            raise ValueError("Equity/cash must be non-negative and cash cannot exceed equity.")
        if isinstance(self.holdings, Mapping):
            items = self.holdings.items()
        else:
            items = ((holding.asset, holding.quantity) for holding in self.holdings)
        normalized: dict[str, float] = {}
        for name, raw_quantity in items:
            asset = _asset(name)
            if asset in normalized:
                raise ValueError(f"Duplicate holding for {asset}.")
            quantity = _number(raw_quantity, f"holdings.{asset}")
            if quantity < 0:
                raise ValueError("Holding quantities cannot be negative.")
            normalized[asset] = quantity
        object.__setattr__(self, "equity", equity)
        object.__setattr__(self, "available_cash", cash)
        object.__setattr__(self, "holdings", tuple(sorted(normalized.items())))


@dataclass(frozen=True)
class AllocationProposal:
    sizing: SizingDecision
    timestamp: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.sizing, SizingDecision):
            raise TypeError("sizing must be a SizingDecision.")
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("proposal timestamp must be timezone-aware.")
        _asset(self.sizing.asset)
        quantity = _number(self.sizing.final_quantity, "proposed quantity")
        if quantity < 0:
            raise ValueError("Proposed quantity cannot be negative.")
        if quantity > 0:
            price = _number(self.sizing.reference_price, "proposal reference price")
            if price <= 0 or self.sizing.action not in {"BUY_T1", "BUY_T2", "BUY_T3"}:
                raise ValueError("Positive proposals require a supported buy action and positive reference price.")


@dataclass(frozen=True)
class AllocationDecision:
    asset: str
    requested_quantity: float
    approved_quantity: float
    requested_notional: float
    approved_notional: float
    current_exposure: float
    resulting_exposure: float
    reduction_amount: float
    binding_constraint: str
    reference_price: float
    timestamp: datetime
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioDecision:
    timestamp: datetime
    decisions: tuple[AllocationDecision, ...]
    gross_exposure_after: float


class PortfolioEngine:
    """Constrain risk sizing quantities using explicit point-in-time inputs."""

    def __init__(self, config_path: str | Path = DEFAULT_PORTFOLIO_CONFIG, *, config: PortfolioConfig | None = None):
        self.config = config or load_portfolio_config(config_path)

    def evaluate(self, snapshot: PortfolioSnapshot, proposals: Sequence[AllocationProposal],
                 reference_prices: Mapping[str, float], *,
                 transaction_cost_rate: float = 0.0) -> PortfolioDecision:
        if not isinstance(snapshot, PortfolioSnapshot):
            raise TypeError("snapshot must be a PortfolioSnapshot.")
        transaction_cost_rate = _number(transaction_cost_rate, "transaction_cost_rate")
        if transaction_cost_rate < 0:
            raise ValueError("transaction_cost_rate cannot be negative.")
        normalized_prices: dict[str, float] = {}
        for name, raw in reference_prices.items():
            asset = _asset(name)
            if asset in normalized_prices:
                raise ValueError(f"Duplicate reference price for {asset}.")
            price = _number(raw, f"reference_prices.{asset}")
            if price <= 0:
                raise ValueError("Reference prices must be positive.")
            normalized_prices[asset] = price
        holdings = dict(snapshot.holdings)
        items: dict[str, AllocationProposal] = {}
        for proposal in proposals:
            if not isinstance(proposal, AllocationProposal):
                raise TypeError("proposals must contain AllocationProposal values.")
            if proposal.timestamp > snapshot.timestamp:
                raise ValueError("Proposal timestamp cannot be after portfolio snapshot.")
            sizing = proposal.sizing
            asset = _asset(sizing.asset)
            if asset in items:
                raise ValueError(f"Only one proposal per asset is supported: {asset}.")
            quantity = _number(sizing.final_quantity, "proposed quantity")
            price = _number(sizing.reference_price, "proposal reference price")
            if quantity < 0 or (quantity > 0 and price <= 0):
                raise ValueError("Proposed quantity must be non-negative and positive proposals require a price.")
            if asset not in normalized_prices:
                raise ValueError(f"Missing reference price for {asset}.")
            if quantity > 0 and not math.isclose(price, normalized_prices[asset], rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f"Proposal and supplied reference prices differ for {asset}.")
            items[asset] = proposal
        for asset, quantity in holdings.items():
            if quantity and asset not in normalized_prices:
                raise ValueError(f"Missing reference price for held asset {asset}.")

        current_notional = {a: q * normalized_prices[a] for a, q in holdings.items() if q}
        represented_value = sum(current_notional.values())
        if not math.isclose(snapshot.available_cash + represented_value, snapshot.equity,
                            rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError("Snapshot equity must equal available cash plus supported holdings at supplied prices.")
        if snapshot.equity == 0 and (snapshot.available_cash != 0 or represented_value != 0):
            raise ValueError("A zero-equity snapshot must have zero cash and no holdings.")
        current_gross = sum(current_notional.values()) / snapshot.equity if snapshot.equity else 0.0
        accepted_gross = current_gross
        reserve_cash_limit = max(0.0, snapshot.available_cash - self.config.minimum_cash_reserve * snapshot.equity)
        cash_spent = 0.0
        results: dict[str, AllocationDecision] = {}
        weights = dict(self.config.max_asset_weight)
        for asset in self.config.priority_order:
            proposal = items.get(asset)
            if proposal is None:
                continue
            sizing = proposal.sizing
            price = normalized_prices[asset]
            requested = _number(sizing.final_quantity, "proposed quantity")
            notional = requested * price
            existing = current_notional.get(asset, 0.0)
            current_weight = existing / snapshot.equity if snapshot.equity else 0.0
            constraints: list[tuple[str, float]] = [("REQUESTED", requested)]
            if snapshot.equity == 0:
                allowed = 0.0
                binding = "ZERO_EQUITY" if requested else "NONE"
            else:
                constraints.append(("MAX_ASSET_WEIGHT", max(0.0, weights[asset] * snapshot.equity - existing) / price))
                constraints.append(("MAX_GROSS_EXPOSURE", max(0.0, self.config.max_gross_exposure * snapshot.equity - accepted_gross * snapshot.equity) / price))
                constraints.append(("CASH_RESERVE", max(0.0, reserve_cash_limit - cash_spent)
                                   / (price * (1 + transaction_cost_rate))))
                allowed = min(value for _, value in constraints)
                tolerance = max(1e-12, requested * 1e-12)
                binding_names = [name for name, value in constraints if name != "REQUESTED"
                                 and requested - allowed > tolerance
                                 and math.isclose(value, allowed, rel_tol=1e-12, abs_tol=1e-12)]
                if not binding_names:
                    binding = "NONE"
                elif len(binding_names) > 1:
                    binding = "MULTIPLE_CONSTRAINTS"
                else:
                    binding = binding_names[0]
            approved_notional = allowed * price
            reduction = notional - approved_notional
            if allowed > 0:
                accepted_gross += approved_notional / snapshot.equity if snapshot.equity else 0.0
                cash_spent += approved_notional * (1 + transaction_cost_rate)
            resulting = (existing + approved_notional) / snapshot.equity if snapshot.equity else 0.0
            results[asset] = AllocationDecision(
                asset, requested, allowed, notional, approved_notional, current_weight,
                resulting, reduction, binding, price, proposal.timestamp,
                () if binding == "NONE" else (f"reduced_by_{binding.lower()}",),
            )
        ordered = tuple(results[a] for a in self.config.priority_order if a in results)
        return PortfolioDecision(snapshot.timestamp, ordered, accepted_gross)
