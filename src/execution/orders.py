"""Immutable paper order and fill records; these models never submit orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from numbers import Real


class OrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


def _aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware timestamp.")


def _positive(value: Real, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)) or value <= 0:
        raise ValueError(f"{name} must be finite and positive.")


def _nonnegative(value: Real, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative.")


def _asset(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("asset must be a non-empty string.")


@dataclass(frozen=True)
class Order:
    order_id: str
    asset: str
    side: str
    quantity: float
    order_type: str
    signal_timestamp: datetime
    decision_timestamp: datetime
    order_timestamp: datetime
    status: OrderStatus = OrderStatus.PROPOSED

    def __post_init__(self) -> None:
        if not isinstance(self.order_id, str) or not self.order_id.strip():
            raise ValueError("order_id must be a non-empty string.")
        _asset(self.asset)
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL.")
        _positive(self.quantity, "quantity")
        if not isinstance(self.order_type, str) or not self.order_type.strip():
            raise ValueError("order_type must be a non-empty string.")
        if not isinstance(self.status, OrderStatus):
            try:
                object.__setattr__(self, "status", OrderStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise ValueError("status is invalid.") from exc
        _aware(self.signal_timestamp, "signal_timestamp")
        _aware(self.decision_timestamp, "decision_timestamp")
        _aware(self.order_timestamp, "order_timestamp")
        if self.decision_timestamp < self.signal_timestamp:
            raise ValueError("decision_timestamp must be >= signal_timestamp.")
        if self.order_timestamp < self.decision_timestamp:
            raise ValueError("order_timestamp must be >= decision_timestamp.")


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    asset: str
    side: str
    quantity: float
    fill_price: float
    fill_timestamp: datetime
    commission: float = 0.0
    slippage_cost: float = 0.0

    def __post_init__(self) -> None:
        for name in ("fill_id", "order_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")
        _asset(self.asset)
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL.")
        _positive(self.quantity, "quantity")
        _positive(self.fill_price, "fill_price")
        _nonnegative(self.commission, "commission")
        _nonnegative(self.slippage_cost, "slippage_cost")
        _aware(self.fill_timestamp, "fill_timestamp")


def create_paper_order(
    asset: str,
    side: str,
    quantity: float,
    *,
    order_id: str,
    signal_timestamp: datetime,
    decision_timestamp: datetime,
    order_timestamp: datetime,
    order_type: str = "MARKET",
) -> Order:
    """Construct a local order proposal; does not route or simulate a fill."""
    return Order(order_id, asset, side, quantity, order_type, signal_timestamp,
                 decision_timestamp, order_timestamp)
