from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from src.execution.accounting import AccountingEngine, CashLedger, Position
from src.execution.orders import Fill, Order, OrderStatus


SIGNAL = datetime(2025, 1, 2, 14, tzinfo=timezone.utc)
DECISION = SIGNAL + timedelta(minutes=1)
ORDER_TIME = DECISION + timedelta(minutes=1)
FILL_TIME = ORDER_TIME + timedelta(minutes=1)


def order(side="BUY", quantity=10, *, asset="SPY", order_id="o1"):
    return Order(order_id, asset, side, quantity, "MARKET", SIGNAL, DECISION, ORDER_TIME)


def fill(qty=10, price=100, *, asset="SPY", side="BUY", order_id="o1", commission=0, slippage_cost=0):
    return Fill(f"f-{order_id}", order_id, asset, side, qty, price, FILL_TIME, commission, slippage_cost)


def apply(ledger, o, f):
    return AccountingEngine().apply_fill(ledger, o, f)


def test_order_timestamps_and_immutability():
    o = order()
    assert o.status is OrderStatus.PROPOSED
    with pytest.raises(FrozenInstanceError):
        o.status = OrderStatus.FILLED
    with pytest.raises(ValueError, match="decision_timestamp"):
        Order("x", "SPY", "BUY", 1, "MARKET", DECISION, SIGNAL, ORDER_TIME)
    with pytest.raises(ValueError, match="order_timestamp"):
        Order("x", "SPY", "BUY", 1, "MARKET", SIGNAL, DECISION, SIGNAL)
    with pytest.raises(ValueError):
        order(side="hold")


@pytest.mark.parametrize("kwargs", [
    {"qty": 0}, {"qty": -1}, {"price": 0}, {"price": float("nan")},
    {"commission": -1},
])
def test_invalid_fills_are_rejected(kwargs):
    with pytest.raises(ValueError):
        fill(**kwargs)


def test_fill_rejects_naive_timestamp_and_wrong_order_timing():
    with pytest.raises(ValueError, match="timezone-aware"):
        Fill("f", "o1", "SPY", "BUY", 1, 10, datetime(2025, 1, 1))
    too_early = Fill("f", "o1", "SPY", "BUY", 1, 10, ORDER_TIME - timedelta(seconds=1))
    with pytest.raises(ValueError, match="fill_timestamp"):
        AccountingEngine().apply_fill(CashLedger(100), order(quantity=1), too_early)


def test_buy_and_weighted_average_cost_basis():
    ledger = CashLedger(10_000)
    ledger2 = apply(ledger, order(), fill())
    assert ledger.cash == 10_000
    assert ledger2.cash == 9_000
    assert ledger2.positions[0].quantity == 10
    assert ledger2.positions[0].average_entry_price == 100
    o2 = order(quantity=20, order_id="o2")
    f2 = fill(20, 90, order_id="o2")
    ledger3 = apply(ledger2, o2, f2)
    assert ledger3.cash == 7_200
    assert ledger3.positions[0].quantity == 30
    assert ledger3.positions[0].average_entry_price == pytest.approx((10 * 100 + 20 * 90) / 30)


def test_sell_realizes_pnl_preserves_average_and_costs_reduce_cash_and_pnl():
    ledger = apply(CashLedger(10_000), order(), fill())
    sell = order("SELL", 4, order_id="o2")
    sold = fill(4, 110, side="SELL", order_id="o2", commission=2, slippage_cost=1)
    result = apply(ledger, sell, sold)
    position = result.positions[0]
    assert result.cash == 9_437
    assert position.quantity == 6
    assert position.average_entry_price == 100
    assert position.realized_pnl == 37


@pytest.mark.parametrize("ledger, o, f", [
    (CashLedger(100), order(quantity=2), fill(qty=2)),
    (CashLedger(10_000), order(), fill(order_id="other")),
    (CashLedger(10_000), order(asset="GLD"), fill()),
    (CashLedger(10_000), order("SELL", 1), fill(1, side="SELL")),
])
def test_fill_consistency_cash_and_position_rejections(ledger, o, f):
    with pytest.raises(ValueError):
        apply(ledger, o, f)


def test_unrealized_pnl_and_snapshot_are_observations_only():
    ledger = apply(CashLedger(10_000), order(), fill())
    position = ledger.positions[0]
    assert position.unrealized_pnl_at(120) == 200
    snapshot = AccountingEngine().snapshot(ledger, FILL_TIME, {"SPY": 120})
    assert snapshot.market_value == 1_200
    assert snapshot.equity == 10_200
    assert snapshot.unrealized_pnl == 200
    assert position == ledger.positions[0]


def test_explicit_costs_and_zero_defaults():
    assert fill().commission == fill().slippage_cost == 0
    ledger = apply(CashLedger(1_000), order(quantity=2), fill(2, 100, commission=3, slippage_cost=2))
    assert ledger.cash == 795


def test_sell_over_position_rejected_and_positions_are_immutable():
    ledger = apply(CashLedger(1_000), order(quantity=2), fill(2))
    with pytest.raises(ValueError, match="exceeds"):
        apply(ledger, order("SELL", 3, order_id="o2"), fill(3, side="SELL", order_id="o2"))
    with pytest.raises(FrozenInstanceError):
        Position("SPY", 1, 1).quantity = 2
