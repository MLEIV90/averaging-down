"""Deterministic, immutable cash and long-only position accounting."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import math
from numbers import Real

from src.execution.orders import Fill, Order, OrderStatus


def _finite(value: Real, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite.")


@dataclass(frozen=True)
class Position:
    asset: str
    quantity: float = 0.0
    average_entry_price: float = 0.0
    market_value: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.asset, str) or not self.asset.strip():
            raise ValueError("asset must be a non-empty string.")
        for field in ("quantity", "average_entry_price", "market_value", "realized_pnl", "unrealized_pnl"):
            _finite(getattr(self, field), field)
        if self.quantity < 0 or self.average_entry_price < 0 or self.market_value < 0:
            raise ValueError("quantity, average_entry_price, and market_value cannot be negative.")
        if self.quantity > 0 and self.average_entry_price <= 0:
            raise ValueError("An open position requires a positive average_entry_price.")
        if self.quantity == 0 and self.average_entry_price != 0:
            raise ValueError("A flat position must have zero average_entry_price.")

    def unrealized_pnl_at(self, current_market_price: float) -> float:
        _finite(current_market_price, "current_market_price")
        if current_market_price <= 0:
            raise ValueError("current_market_price must be positive.")
        return self.quantity * (float(current_market_price) - self.average_entry_price)

    def valued_at(self, current_market_price: float) -> Position:
        _finite(current_market_price, "current_market_price")
        if current_market_price <= 0:
            raise ValueError("current_market_price must be positive.")
        return replace(self, market_value=self.quantity * float(current_market_price),
                       unrealized_pnl=self.unrealized_pnl_at(current_market_price))


@dataclass(frozen=True)
class CashLedger:
    initial_cash: float
    cash: float | None = None
    positions: tuple[Position, ...] = ()
    realized_pnl: float = 0.0
    cash_before: float | None = None
    applied_fill_ids: tuple[str, ...] = ()
    applied_order_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _finite(self.initial_cash, "initial_cash")
        cash = self.initial_cash if self.cash is None else self.cash
        _finite(cash, "cash")
        if self.initial_cash < 0 or cash < 0:
            raise ValueError("Cash cannot be negative without an explicit margin configuration.")
        _finite(self.realized_pnl, "realized_pnl")
        before = cash if self.cash_before is None else self.cash_before
        _finite(before, "cash_before")
        if before < 0:
            raise ValueError("cash_before cannot be negative.")
        object.__setattr__(self, "cash", float(cash))
        object.__setattr__(self, "cash_before", float(before))
        if not isinstance(self.positions, tuple) or any(not isinstance(p, Position) for p in self.positions):
            raise ValueError("positions must be a tuple of Position values.")
        assets = [p.asset for p in self.positions]
        if len(set(assets)) != len(assets):
            raise ValueError("CashLedger cannot contain duplicate asset positions.")
        if len(set(self.applied_fill_ids)) != len(self.applied_fill_ids):
            raise ValueError("CashLedger contains duplicate applied fill IDs.")
        if len(set(self.applied_order_ids)) != len(self.applied_order_ids):
            raise ValueError("CashLedger contains duplicate applied order IDs.")

    @property
    def cash_after(self) -> float:
        return float(self.cash)


@dataclass(frozen=True)
class AccountSnapshot:
    timestamp: datetime
    cash: float
    market_value: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    positions: tuple[Position, ...]


class AccountingEngine:
    """Apply externally supplied fills; never creates fills or mutates strategy state."""

    def apply_fill(self, ledger: CashLedger, order: Order, fill: Fill) -> CashLedger:
        if not isinstance(ledger, CashLedger) or not isinstance(order, Order) or not isinstance(fill, Fill):
            raise TypeError("apply_fill requires a CashLedger, Order, and Fill.")
        if order.status is not OrderStatus.PROPOSED:
            raise ValueError("Only a PROPOSED order can be filled.")
        if fill.fill_id in ledger.applied_fill_ids:
            raise ValueError("Fill has already been applied.")
        if order.order_id in ledger.applied_order_ids:
            raise ValueError("Order has already been filled.")
        if order.order_id != fill.order_id:
            raise ValueError("Fill order_id does not match Order.")
        if order.asset != fill.asset or order.side != fill.side:
            raise ValueError("Fill asset or side does not match Order.")
        if not math.isclose(order.quantity, fill.quantity, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("Fill quantity does not match Order quantity.")
        if fill.fill_timestamp < order.order_timestamp:
            raise ValueError("fill_timestamp must be >= order_timestamp.")

        current = next((p for p in ledger.positions if p.asset == fill.asset), Position(fill.asset))
        costs = fill.commission + fill.slippage_cost
        notional = fill.quantity * fill.fill_price
        if fill.side == "BUY":
            cash_after = ledger.cash - notional - costs
            if cash_after < 0:
                raise ValueError("BUY fill would make cash negative.")
            new_quantity = current.quantity + fill.quantity
            average = ((current.quantity * current.average_entry_price) + notional) / new_quantity
            updated = Position(fill.asset, new_quantity, average, 0.0,
                               current.realized_pnl, 0.0)
            realized_delta = 0.0
        else:
            if fill.quantity > current.quantity:
                raise ValueError("SELL fill quantity exceeds existing position quantity.")
            cash_after = ledger.cash + notional - costs
            if cash_after < 0:
                raise ValueError("SELL fill would make cash negative.")
            realized_delta = fill.quantity * (fill.fill_price - current.average_entry_price) - costs
            remaining = current.quantity - fill.quantity
            average = current.average_entry_price if remaining else 0.0
            updated = Position(fill.asset, remaining, average, 0.0,
                               current.realized_pnl + realized_delta, 0.0)

        positions = {p.asset: p for p in ledger.positions}
        if updated.quantity == 0:
            positions.pop(fill.asset, None)
        else:
            positions[fill.asset] = updated
        return CashLedger(ledger.initial_cash, cash_after,
                          tuple(positions[key] for key in sorted(positions)),
                          ledger.realized_pnl + realized_delta, ledger.cash,
                          ledger.applied_fill_ids + (fill.fill_id,),
                          ledger.applied_order_ids + (order.order_id,))

    def snapshot(
        self, ledger: CashLedger, timestamp: datetime, market_prices: dict[str, float]
    ) -> AccountSnapshot:
        if not isinstance(ledger, CashLedger):
            raise TypeError("ledger must be a CashLedger.")
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware.")
        valued: list[Position] = []
        for position in ledger.positions:
            if position.asset not in market_prices:
                raise ValueError(f"Missing current market price for {position.asset}.")
            valued.append(position.valued_at(market_prices[position.asset]))
        market_value = sum(p.market_value for p in valued)
        unrealized = sum(p.unrealized_pnl for p in valued)
        return AccountSnapshot(timestamp, ledger.cash, market_value, ledger.cash + market_value,
                               ledger.realized_pnl, unrealized, tuple(valued))
