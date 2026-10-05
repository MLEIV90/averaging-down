from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.backtest.sequential import (AssetSummary, BacktestConfig, BacktestResult,
                                     OrderRecord, PortfolioPoint, PositionPoint,
                                     TradeRecord)
from src.execution.orders import Fill, Order, OrderStatus
from src.strategy.state_machine import PositionState
from src.validation import (FindingStatus, OverallStatus, SampleLabel, ValidationConfig,
                            canonical_json, run_backtest_twice, run_validation,
                            validation_report_sha256)


T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _state(tier, price, ts):
    return PositionState(True, tier, price, price, .1, price, ts, -1.0, 0)


def make_result(*, multi=False, costs=False, slippage=False, open_position=False, partial=False):
    ts = [T0 + timedelta(days=i) for i in range(4 if multi or partial else 3)]
    cfg = BacktestConfig(1000.0, 10.0 if costs else 0.0, 5.0 if slippage else 0.0, "next_bar_open")
    orders, trades, fills = [], [], []
    fillspec = [("BUY", 1, 100.0, 1, "T1", 0)]
    if multi:
        fillspec.append(("BUY", 1, 90.0, 2, "T2", 0))
    if partial and not open_position:
        fillspec.extend((("SELL", .4, 110.0, 2, "T1", 0),
                         ("SELL", .6, 110.0, 3, "T1", 0)))
    elif not open_position:
        fillspec.append(("SELL", 1 if not multi else 2, 110.0 if not multi else 100.0,
                         len(ts) - 1, "T1" if not multi else "T2", 0))
    cash = 1000.0
    quantity = 0.0
    cumulative_costs = 0.0
    trade_by_time = {}
    for number, (side, qty, price, fill_i, tier, _) in enumerate(fillspec):
        signal_i = fill_i - 1
        commission = qty * price * cfg.commission_bps / 10000 if costs else 0.0
        slip_cost = qty * price * cfg.slippage_bps / 10000 if slippage else 0.0
        fill = Fill(f"fill-{number}", f"order-{number}", "SPY", side, qty, price, ts[fill_i], commission, slip_cost)
        order = Order(f"order-{number}", "SPY", side, qty, "MARKET", ts[signal_i], ts[signal_i], ts[signal_i], OrderStatus.FILLED)
        action = f"{side}_{tier}" if side == "BUY" else ("PARTIAL_SELL" if partial and qty < 1 else "FULL_EXIT")
        record = OrderRecord(order, action, "test", tier, price, fill, "FILLED", qty, qty)
        orders.append(record)
        prior_quantity = quantity
        if side == "BUY":
            cash -= qty * price + commission + slip_cost
            quantity += qty
            avg = ((prior_quantity * (100 if not multi or number == 1 else 100)) + qty * price) / quantity
            realized = 0.0
        else:
            avg = 100.0 if not multi else 95.0
            cash += qty * price - commission - slip_cost
            quantity -= qty
            realized = qty * (price - avg) - commission - slip_cost
        cumulative_costs += commission + slip_cost
        trades.append(TradeRecord(order.order_id, "SPY", side, action, "test", tier,
                                  ts[signal_i], ts[signal_i], ts[signal_i], ts[fill_i],
                                  price, price, qty, qty * price, commission, slip_cost, realized))
        fills.append(fill)
        trade_by_time[ts[fill_i]] = (cash, quantity, avg if quantity else 0.0)

    points, positions = [], []
    cash = 1000.0
    quantity = 0.0
    avg = 0.0
    cumulative_costs = 0.0
    for i, timestamp in enumerate(ts):
        for order in orders:
            if order.fill.fill_timestamp == timestamp:
                fill = order.fill
                cost = fill.commission + fill.slippage_cost
                cumulative_costs += cost
                if fill.side == "BUY":
                    avg = ((quantity * avg) + fill.quantity * fill.fill_price) / (quantity + fill.quantity)
                    quantity += fill.quantity
                    cash -= fill.quantity * fill.fill_price + cost
                else:
                    quantity -= fill.quantity
                    cash += fill.quantity * fill.fill_price - cost
                    if quantity == 0:
                        avg = 0.0
        mark = 90.0 if multi and i == 2 else (100.0 if i < len(ts) - 1 or open_position else 0.0)
        mv = quantity * mark
        equity = cash + mv
        points.append(PortfolioPoint(timestamp, cash, mv, equity, mv / equity if equity else 0,
                                     mv / equity if equity else 0,
                                     sum(t.realized_pnl for t in trades if t.side == "SELL" and t.fill_timestamp <= timestamp),
                                     mv - quantity * avg, cumulative_costs))
        state = PositionState()
        if quantity:
            entry_time = next(f.fill_timestamp for f in fills if f.side == "BUY")
            active_tier = "T2" if multi and i >= 2 else "T1"
            state = _state(active_tier, 100.0, entry_time)
        positions.append(PositionPoint(timestamp, "SPY", quantity, avg, state))
    pending = ()
    if open_position:
        # No BUY can fill on the final bar, so this flag uses a synthetic extra entry window only when needed.
        points[-1] = replace(points[-1], equity=points[-1].cash + points[-1].market_value)
    summary_fills = len(fills)
    asset_summary = (AssetSummary("SPY", 1 if not open_position else 1, summary_fills,
                                  1.0, sum(f.quantity * f.fill_price for f in fills)),)
    return BacktestResult(tuple(points), tuple(trades), tuple(orders), pending,
                          tuple(positions), asset_summary, sum(f.commission + f.slippage_cost for f in fills), cfg)


def report_for(result, **kwargs):
    return run_validation(result, config=ValidationConfig(insufficient_cycles=1, limited_cycles=3,
                                                           insufficient_fills=1), **kwargs)


def make_two_cycles_result():
    timestamps = [T0 + timedelta(days=i) for i in range(5)]
    cfg = BacktestConfig(1000.0, 0.0, 0.0, "next_bar_open")
    specs = (("BUY", 100.0, 1, 0, "T1"), ("SELL", 110.0, 1, 1, "T1"),
             ("BUY", 105.0, 1, 2, "T1"), ("SELL", 100.0, 1, 3, "T1"))
    orders, trades = [], []
    for i, (side, price, quantity, signal_index, tier) in enumerate(specs):
        fill_time = timestamps[signal_index + 1]
        fill = Fill(f"two-fill-{i}", f"two-order-{i}", "SPY", side, quantity, price, fill_time)
        order = Order(f"two-order-{i}", "SPY", side, quantity, "MARKET", timestamps[signal_index],
                      timestamps[signal_index], timestamps[signal_index], OrderStatus.FILLED)
        orders.append(OrderRecord(order, f"{side}_{tier}", "two-cycle", tier, price, fill, "FILLED", quantity, quantity))
        pnl = quantity * (price - (100.0 if i == 1 else 105.0)) if side == "SELL" else 0.0
        trades.append(TradeRecord(order.order_id, "SPY", side, f"{side}_{tier}", "two-cycle", tier,
                                  order.signal_timestamp, order.decision_timestamp, order.order_timestamp,
                                  fill_time, price, price, quantity, quantity * price, 0, 0, pnl))
    cash, quantity, avg = 1000.0, 0.0, 0.0
    points, positions = [], []
    for i, timestamp in enumerate(timestamps):
        for record in orders:
            if record.fill.fill_timestamp == timestamp:
                fill = record.fill
                if fill.side == "BUY":
                    avg = fill.fill_price
                    quantity += fill.quantity
                    cash -= fill.quantity * fill.fill_price
                else:
                    cash += fill.quantity * fill.fill_price
                    quantity -= fill.quantity
                    if quantity == 0:
                        avg = 0.0
        mark = avg if quantity else 0.0
        market_value = quantity * mark
        equity = cash + market_value
        realized = sum(t.realized_pnl for t in trades if t.side == "SELL" and t.fill_timestamp <= timestamp)
        points.append(PortfolioPoint(timestamp, cash, market_value, equity,
                                     market_value / equity if equity else 0,
                                     market_value / equity if equity else 0,
                                     realized, 0.0, 0.0))
        active_tier = "T1"
        positions.append(PositionPoint(timestamp, "SPY", quantity, avg,
                                       _state(active_tier, avg, timestamp) if quantity else PositionState()))
    return BacktestResult(tuple(points), tuple(trades), tuple(orders), (), tuple(positions),
                          (AssetSummary("SPY", 2, 4, 1.0, 415.0),), 0.0, cfg)


def finding(report, name, section="integrity"):
    return next(item for item in getattr(report, section).findings if item.check_name == name)


def test_valid_result_passes_integrity_and_temporal_contract():
    report = report_for(make_result())
    assert report.integrity.status == FindingStatus.PASS
    assert report.temporal_integrity.status == FindingStatus.WARNING  # raw OHLC bars are unavailable
    assert finding(report, "sequential_fill_accounting_feasibility").status == FindingStatus.PASS
    assert finding(report, "strictly_later_fill", "temporal_integrity").status == FindingStatus.PASS
    assert finding(report, "pending_orders_unfilled", "temporal_integrity").status == FindingStatus.PASS


def test_negative_cash_fails():
    result = make_result()
    bad = replace(result, portfolio_curve=(replace(result.portfolio_curve[0], cash=-1), *result.portfolio_curve[1:]))
    assert finding(report_for(bad), "finite_nonnegative_portfolio_values").status == FindingStatus.FAIL


def test_negative_position_quantity_fails():
    result = make_result()
    bad_pos = replace(result.position_history[0], quantity=-1)
    report = report_for(replace(result, position_history=(bad_pos, *result.position_history[1:])))
    assert finding(report, "nonnegative_position_quantities").status == FindingStatus.FAIL


def test_equity_reconciliation_failure_is_critical():
    result = make_result()
    bad = replace(result, portfolio_curve=(replace(result.portfolio_curve[0], equity=999), *result.portfolio_curve[1:]))
    report = report_for(bad)
    assert finding(report, "equity_cash_market_value_reconciliation").status == FindingStatus.FAIL
    assert report.overall_status == OverallStatus.FAIL


def test_nan_equity_is_reported_without_crashing_canonical_serialization():
    result = make_result()
    bad = replace(result, portfolio_curve=(result.portfolio_curve[0],
                                           replace(result.portfolio_curve[1], equity=float("nan")),
                                           *result.portfolio_curve[2:]))
    report = report_for(bad)
    assert finding(report, "finite_nonnegative_portfolio_values").status == FindingStatus.FAIL
    assert report.overall_status == OverallStatus.FAIL


def test_duplicate_fill_ids_fail():
    result = make_result()
    second = replace(result.orders[1].fill, fill_id=result.orders[0].fill.fill_id)
    second_record = replace(result.orders[1], fill=second)
    bad = replace(result, orders=(result.orders[0], second_record, *result.orders[2:]))
    assert finding(report_for(bad), "unique_fill_ids").status == FindingStatus.FAIL


def test_duplicate_order_ids_fail():
    result = make_result()
    second_order = replace(result.orders[1].order, order_id=result.orders[0].order.order_id)
    bad = replace(result, orders=(result.orders[0], replace(result.orders[1], order=second_order), *result.orders[2:]))
    assert finding(report_for(bad), "unique_order_ids").status == FindingStatus.FAIL


def test_invalid_timestamp_and_duplicate_portfolio_times_fail():
    result = make_result()
    bad_point = replace(result.portfolio_curve[1], timestamp=T0.replace(tzinfo=None))
    bad = replace(result, portfolio_curve=(result.portfolio_curve[0], bad_point, result.portfolio_curve[2]))
    assert finding(report_for(bad), "portfolio_timestamp_order").status == FindingStatus.FAIL
    duplicate = replace(result, portfolio_curve=(result.portfolio_curve[0], result.portfolio_curve[0], result.portfolio_curve[2]))
    assert finding(report_for(duplicate), "portfolio_timestamp_order").status == FindingStatus.FAIL


def test_invalid_order_fill_relationship_fails():
    result = make_result()
    wrong_fill = replace(result.orders[0].fill, asset="BTC")
    bad = replace(result, orders=(replace(result.orders[0], fill=wrong_fill), *result.orders[1:]))
    assert finding(report_for(bad), "order_fill_relationships").status == FindingStatus.FAIL


def test_cost_reconciliation_and_cumulative_costs():
    result = make_result(costs=True)
    report = report_for(result)
    assert finding(report, "transaction_cost_reconciliation").status == FindingStatus.PASS
    assert finding(report, "cumulative_cost_curve_reconciliation").status == FindingStatus.PASS
    bad = replace(result, total_transaction_costs=result.total_transaction_costs + 1)
    assert finding(report_for(bad), "transaction_cost_reconciliation").status == FindingStatus.FAIL


def test_buy_that_would_make_cash_negative_and_oversell_are_detected():
    result = make_result()
    first = result.orders[0]
    huge_fill = replace(first.fill, quantity=100)
    huge_order = replace(first.order, quantity=100)
    huge_trade = replace(result.trades[0], quantity=100, notional=10000)
    bad_buy = replace(result, orders=(replace(first, order=huge_order, fill=huge_fill), *result.orders[1:]),
                      trades=(huge_trade, *result.trades[1:]))
    buy_report = report_for(bad_buy)
    assert finding(buy_report, "sequential_fill_accounting_feasibility").status == FindingStatus.FAIL

    sell_index = next(i for i, record in enumerate(result.orders) if record.fill.side == "SELL")
    record = result.orders[sell_index]
    sell_fill = replace(record.fill, quantity=2)
    sell_order = replace(record.order, quantity=2)
    sell_trade = replace(result.trades[sell_index], quantity=2, notional=2 * sell_fill.fill_price)
    bad_sell_orders = list(result.orders)
    bad_sell_orders[sell_index] = replace(record, order=sell_order, fill=sell_fill)
    bad_sell_trades = list(result.trades)
    bad_sell_trades[sell_index] = sell_trade
    sell_report = report_for(replace(result, orders=tuple(bad_sell_orders), trades=tuple(bad_sell_trades)))
    assert finding(sell_report, "sequential_fill_accounting_feasibility").status == FindingStatus.FAIL


def test_filled_order_without_fill_and_future_state_are_detected():
    result = make_result()
    missing = replace(result, orders=(replace(result.orders[0], fill=None), *result.orders[1:]))
    assert finding(report_for(missing), "order_fill_relationships").status == FindingStatus.FAIL
    future = replace(result, position_history=(result.position_history[0],
                                              replace(result.position_history[1], quantity=0),
                                              result.position_history[2]))
    assert finding(report_for(future), "no_future_fills_in_position_history").status == FindingStatus.FAIL


def test_same_bar_fill_fails_temporal_check():
    result = make_result()
    order = result.orders[0].order
    fill = replace(result.orders[0].fill, fill_timestamp=order.decision_timestamp)
    bad = replace(result, orders=(replace(result.orders[0], fill=fill), *result.orders[1:]))
    assert finding(report_for(bad), "strictly_later_fill", "temporal_integrity").status == FindingStatus.FAIL


def test_fill_before_decision_fails_temporal_check():
    result = make_result()
    fill = replace(result.orders[0].fill, fill_timestamp=T0 - timedelta(seconds=1))
    bad = replace(result, orders=(replace(result.orders[0], fill=fill), *result.orders[1:]))
    assert finding(report_for(bad), "strictly_later_fill", "temporal_integrity").status == FindingStatus.FAIL


def test_pending_order_is_not_counted_as_fill():
    result = make_result()
    order = Order("pending", "SPY", "BUY", 1, "MARKET", T0, T0, T0)
    pending = OrderRecord(order, "BUY_T1", "eod", "T1", 100, None, "PENDING", 1, 1)
    report = report_for(replace(result, pending_orders=(pending,)))
    assert report.sample_size.fills == 2
    assert finding(report, "pending_orders_unfilled", "temporal_integrity").status == FindingStatus.PASS


def test_deterministic_validation_report_and_hash():
    result = make_result()
    one, two = report_for(result), report_for(result)
    assert one == two
    assert canonical_json(one) == canonical_json(two)
    assert validation_report_sha256(one) == validation_report_sha256(two)


def test_run_backtest_twice_helper_detects_nondeterminism():
    values = iter([1, 2])
    same, first, second = run_backtest_twice(lambda: next(values))
    assert not same and first != second
    same, first, second = run_backtest_twice(lambda: {"a": 1, "b": 2})
    assert same and first == second


def test_benchmark_valid_aligned_comparison():
    result = make_result()
    index = pd.DatetimeIndex([point.timestamp for point in result.portfolio_curve])
    report = report_for(result, benchmark=pd.Series([1000, 1000, 1000], index=index))
    assert report.benchmark.status == FindingStatus.PASS
    assert report.benchmark_comparison is not None
    assert report.benchmark_comparison.excess_return == pytest.approx(.01)


def test_missing_benchmark_is_warning_not_downloaded():
    report = report_for(make_result())
    assert report.benchmark.status == FindingStatus.WARNING
    assert report.benchmark_comparison is None


@pytest.mark.parametrize("benchmark", ([1000], [1000, float("nan"), 1000], [0, 1000, 1000], [1000, -1, 1000]))
def test_invalid_benchmark_curves_are_rejected(benchmark):
    assert report_for(make_result(), benchmark=benchmark).benchmark.status == FindingStatus.FAIL


def test_benchmark_timestamp_mismatch_is_rejected():
    result = make_result()
    index = pd.DatetimeIndex([T0 + timedelta(days=8 + i) for i in range(len(result.portfolio_curve))])
    report = report_for(result, benchmark=pd.Series([1000] * len(index), index=index))
    assert report.benchmark.status == FindingStatus.FAIL


def test_valid_benchmark_is_still_reported_when_strategy_curve_is_invalid():
    result = make_result()
    points = (result.portfolio_curve[0], replace(result.portfolio_curve[1], equity=float("nan")),
              result.portfolio_curve[2])
    report = report_for(replace(result, portfolio_curve=points), benchmark=[1000, 1000, 1000])
    assert report.benchmark.status == FindingStatus.WARNING
    assert report.benchmark_comparison is not None
    assert report.benchmark_comparison.strategy_total_return is None


def test_cost_diagnostic_reports_actual_cost_once_and_no_counterfactual():
    report = report_for(make_result(costs=True))
    assert report.costs.total_costs == pytest.approx(.21)
    assert report.costs.cost_over_initial_capital == pytest.approx(.00021)
    assert report.costs.final_equity_after_costs == pytest.approx(1009.79)
    assert report.costs.mechanically_added_back_costs_final_equity == pytest.approx(1010)
    assert report.costs.counterfactual_no_cost_strategy_return is None
    assert report.costs.configured_commission_bps == 10
    assert report.costs.configured_slippage_bps == 0
    assert report.costs.mechanical_cost_addback_difference == pytest.approx(.21)


def test_commission_and_slippage_are_both_counted_once():
    report = report_for(make_result(costs=True, slippage=True))
    assert report.costs.total_costs == pytest.approx(.315)
    assert report.costs.final_equity_after_costs == pytest.approx(1009.685)
    assert report.costs.mechanical_cost_addback_difference == pytest.approx(.315)


def test_zero_cost_trading_warns_explicitly():
    report = report_for(make_result(costs=False))
    assert any(f.check_name == "zero_costs_while_trading" and f.status == FindingStatus.WARNING
               for f in report.costs.findings)


def test_single_entry_and_multi_entry_scale_in_cycles():
    single = report_for(make_result())
    assert single.scale_in.completed_cycles == 1
    assert single.scale_in.multi_entry_cycles == 0
    assert single.scale_in.average_entries_per_completed_cycle == 1
    multi = report_for(make_result(multi=True))
    assert multi.scale_in.scale_in_fills == 1
    assert multi.scale_in.multi_entry_cycles == 1
    assert multi.scale_in.multi_entry_cycle_percentage == 100
    assert multi.scale_in.average_entries_per_completed_cycle == 2
    assert multi.scale_in.multi_entry_realized_pnl == pytest.approx(10)
    assert multi.scale_in.single_entry_realized_pnl == 0
    assert multi.scale_in.counterfactual_no_scale_in is None
    assert multi.scale_in.multi_entry_traded_notional == pytest.approx(390)


def test_partial_exits_remain_one_completed_entry_cycle():
    report = report_for(make_result(partial=True))
    assert report.scale_in.completed_cycles == 1
    assert report.scale_in.average_entries_per_completed_cycle == 1
    assert report.sample_size.winning_cycles == 1
    assert report.integrity.status == FindingStatus.PASS


def test_multiple_completed_cycles_have_independent_outcomes():
    report = report_for(make_two_cycles_result())
    assert report.sample_size.completed_cycles == 2
    assert report.sample_size.winning_cycles == 1
    assert report.sample_size.losing_cycles == 1
    assert report.scale_in.completed_cycles == 2
    assert report.scale_in.multi_entry_cycles == 0
    assert report.scale_in.single_entry_realized_pnl == pytest.approx(5)


def test_empty_and_one_cycle_sample_labels():
    empty = make_result()
    empty = replace(empty, portfolio_curve=(), orders=(), trades=(), position_history=(), per_asset=(), total_transaction_costs=0)
    report = run_validation(empty)
    assert report.sample_size.label == SampleLabel.INSUFFICIENT_SAMPLE
    assert report.sample_size.portfolio_observations == 0
    one = report_for(make_result())
    assert one.sample_size.completed_cycles == 1
    assert one.sample_size.label == SampleLabel.INSUFFICIENT_SAMPLE


def test_degenerate_no_trades_and_buy_only_results_warn():
    empty = make_result()
    no_trades = replace(empty, orders=(), trades=(), position_history=(), per_asset=(), total_transaction_costs=0)
    assert any(f.check_name == "no_trades" and f.status == FindingStatus.WARNING
               for f in run_validation(no_trades).degeneracy.findings)
    open_buy = make_result(open_position=True)
    report = report_for(open_buy)
    assert any(f.check_name == "buys_without_exits" and f.status == FindingStatus.WARNING
               for f in report.degeneracy.findings)
    assert any(f.check_name == "open_position_without_unrealized_contribution"
               and f.status == FindingStatus.WARNING for f in report.degeneracy.findings)


def test_one_asset_and_single_cycle_pnl_concentration_are_diagnostics():
    report = report_for(make_result())
    assert report.exposure.assets[0].asset == "SPY"
    assert report.exposure.maximum_realized_pnl_concentration == 1
    assert any(f.check_name == "pnl_concentrated_in_one_cycle" and f.status == FindingStatus.WARNING
               for f in report.degeneracy.findings)
    assert report.exposure.assets[0].realized_pnl_contribution == pytest.approx(1)
