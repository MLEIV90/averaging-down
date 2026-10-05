"""Structural accounting, record-linkage, and timestamp checks."""

from collections import Counter, defaultdict
import math
from datetime import datetime

from src.backtest.sequential import BacktestResult
from .config import ValidationConfig
from .models import Finding, FindingStatus as S, Severity as V


def _finding(name, ok, message, measured=None, expected=None, severity=V.CRITICAL):
    if isinstance(measured, float) and not math.isfinite(measured):
        measured = "NaN" if math.isnan(measured) else ("Infinity" if measured > 0 else "-Infinity")
    return Finding(name, S.PASS if ok else S.FAIL, V.INFO if ok else severity,
                   message, measured, expected)


def _aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _close(a, b, cfg):
    try:
        return math.isfinite(float(a)) and math.isfinite(float(b)) and math.isclose(
            float(a), float(b), rel_tol=cfg.relative_tolerance, abs_tol=cfg.absolute_tolerance)
    except (TypeError, ValueError, OverflowError):
        return False


def _below(value, threshold):
    try:
        return float(value) < threshold
    except (TypeError, ValueError, OverflowError):
        return False


def _not_positive(value):
    try:
        return not math.isfinite(float(value)) or float(value) <= 0
    except (TypeError, ValueError, OverflowError):
        return True


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def inspect_integrity(result: BacktestResult, cfg: ValidationConfig) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    points, records, trades = result.portfolio_curve, result.orders, result.trades
    all_fills = [(record, record.fill) for record in records if getattr(record, "fill", None) is not None]
    fill_ids = [getattr(fill, "fill_id", None) for _, fill in all_fills]
    order_ids = [getattr(getattr(record, "order", None), "order_id", None) for record in records
                 if getattr(record, "order", None) is not None]
    findings.append(_finding("unique_order_ids", len(order_ids) == len(set(order_ids)),
                             "Order IDs are unique." if len(order_ids) == len(set(order_ids)) else "Duplicate order IDs found.",
                             len(order_ids), len(set(order_ids))))
    findings.append(_finding("unique_fill_ids", len(fill_ids) == len(set(fill_ids)),
                             "Fill IDs are unique." if len(fill_ids) == len(set(fill_ids)) else "Duplicate fill IDs found.",
                             len(fill_ids), len(set(fill_ids))))
    trade_order_ids = [getattr(trade, "order_id", None) for trade in trades]
    findings.append(_finding("unique_trade_order_ids", len(trade_order_ids) == len(set(trade_order_ids)),
                             "Each order has at most one TradeRecord.", len(trade_order_ids), len(set(trade_order_ids))))

    id_counts = Counter(order_ids)
    order_lookup = {getattr(record.order, "order_id", None): record for record in records
                    if getattr(record, "order", None) is not None}
    linkage_errors: list[str] = []
    for record in records:
        order, fill = getattr(record, "order", None), getattr(record, "fill", None)
        status = getattr(record, "status", None)
        order_status = getattr(getattr(order, "status", None), "value", getattr(order, "status", None))
        if status == "FILLED" and fill is None:
            linkage_errors.append("filled order has no Fill")
        if fill is not None:
            if status != "FILLED" or order is None:
                linkage_errors.append("Fill is attached to a non-filled or missing Order")
            else:
                for attr in ("order_id", "asset", "side"):
                    if getattr(fill, attr, None) != getattr(order, attr, None):
                        linkage_errors.append(f"Fill {attr} does not match Order")
                if not _close(getattr(fill, "quantity", math.nan), getattr(order, "quantity", math.nan), cfg):
                    linkage_errors.append("Fill quantity does not match Order")
                if order_status != "FILLED":
                    linkage_errors.append("attached Fill order status is not FILLED")
        if order_status == "FILLED" and fill is None:
            linkage_errors.append("FILLED Order has no Fill")
    findings.append(_finding("order_fill_relationships", not linkage_errors,
                             "Filled orders and attached fills reconcile." if not linkage_errors else "; ".join(linkage_errors[:5]),
                             len(linkage_errors), 0))
    fill_order_ids = [getattr(fill, "order_id", None) for _, fill in all_fills]
    missing_fill_orders = [oid for oid in fill_order_ids if oid not in order_lookup]
    findings.append(_finding("fills_reference_orders", not missing_fill_orders,
                             "Every Fill references an order." if not missing_fill_orders else "Orphan fills reference missing orders.",
                             len(missing_fill_orders), 0))

    trade_errors = []
    filled_by_order = {getattr(fill, "order_id", None): fill for _, fill in all_fills}
    for trade in trades:
        oid = getattr(trade, "order_id", None)
        fill = filled_by_order.get(oid)
        record = order_lookup.get(oid)
        if fill is None or record is None or getattr(record, "status", None) != "FILLED":
            trade_errors.append(f"TradeRecord {oid} has no matching filled order and Fill")
            continue
        for trade_attr, fill_attr in (("asset", "asset"), ("side", "side"), ("fill_timestamp", "fill_timestamp"),
                                      ("fill_price", "fill_price"), ("quantity", "quantity"),
                                      ("commission", "commission"), ("slippage_cost", "slippage_cost")):
            a, b = getattr(trade, trade_attr, None), getattr(fill, fill_attr, None)
            equal = _close(a, b, cfg) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else a == b
            if not equal:
                trade_errors.append(f"TradeRecord {oid} {trade_attr} does not match Fill")
        if not _close(getattr(trade, "notional", math.nan),
                      float(getattr(fill, "quantity", 0)) * float(getattr(fill, "fill_price", 0)), cfg):
            trade_errors.append(f"TradeRecord {oid} notional does not match Fill")
        for trade_attr, order_attr in (("signal_timestamp", "signal_timestamp"),
                                       ("decision_timestamp", "decision_timestamp"),
                                       ("order_timestamp", "order_timestamp")):
            if getattr(trade, trade_attr, None) != getattr(record.order, order_attr, None):
                trade_errors.append(f"TradeRecord {oid} {trade_attr} does not match Order")
    findings.append(_finding("trade_fill_relationships", not trade_errors,
                             "TradeRecords match their filled orders and Fills." if not trade_errors else "; ".join(trade_errors[:5]),
                             len(trade_errors), 0))
    findings.append(_finding("fill_counted_once", len(trades) == len(all_fills) and
                             set(trade_order_ids) == set(fill_order_ids),
                             "Each actual Fill is represented once in TradeRecords." if len(trades) == len(all_fills) and set(trade_order_ids) == set(fill_order_ids)
                             else "TradeRecord and actual Fill counts or order IDs differ.", len(trades), len(all_fills)))

    bad_fill_values = []
    for _, fill in all_fills:
        q, price = getattr(fill, "quantity", math.nan), getattr(fill, "fill_price", math.nan)
        costs = (getattr(fill, "commission", math.nan), getattr(fill, "slippage_cost", math.nan))
        if not isinstance(q, (int, float)) or not math.isfinite(q) or q <= 0:
            bad_fill_values.append("fill quantity must be finite and positive")
        if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            bad_fill_values.append("fill price must be finite and positive")
        if any(not isinstance(c, (int, float)) or not math.isfinite(c) or c < 0 for c in costs):
            bad_fill_values.append("fill costs must be finite and non-negative")
        if getattr(fill, "side", None) not in {"BUY", "SELL"}:
            bad_fill_values.append("fill side must be BUY or SELL")
    findings.append(_finding("fill_values", not bad_fill_values,
                             "Fill quantities, prices, and costs are valid." if not bad_fill_values else "; ".join(bad_fill_values[:5]),
                             len(bad_fill_values), 0))
    bad_fill_timestamps = [fill for _, fill in all_fills if not _aware(getattr(fill, "fill_timestamp", None))]
    findings.append(_finding("fill_timestamp_awareness", not bad_fill_timestamps,
                             "All actual Fill timestamps are timezone-aware." if not bad_fill_timestamps
                             else "One or more actual Fill timestamps are not timezone-aware.",
                             len(bad_fill_timestamps), 0))

    invalid_points = []
    for point in points:
        numeric = ("cash", "market_value", "equity", "gross_exposure", "net_exposure",
                   "realized_pnl", "unrealized_pnl", "total_transaction_costs")
        for field in numeric:
            value = getattr(point, field, math.nan)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                invalid_points.append(f"{field} is not finite")
        if _below(getattr(point, "cash", -math.inf), -cfg.absolute_tolerance):
            invalid_points.append("negative cash")
        if _below(getattr(point, "equity", -math.inf), -cfg.absolute_tolerance):
            invalid_points.append("negative equity")
        if _below(getattr(point, "market_value", -math.inf), -cfg.absolute_tolerance):
            invalid_points.append("negative marked market value")
        if _below(getattr(point, "gross_exposure", -math.inf), -cfg.absolute_tolerance) or _below(getattr(point, "net_exposure", -math.inf), -cfg.absolute_tolerance):
            invalid_points.append("negative long-only exposure")
        if _below(getattr(point, "total_transaction_costs", -math.inf), -cfg.absolute_tolerance):
            invalid_points.append("negative cumulative transaction costs")
    findings.append(_finding("finite_nonnegative_portfolio_values", not invalid_points,
                             "Portfolio cash, equity, P&L, costs, and exposure are finite and non-negative where required."
                             if not invalid_points else "; ".join(invalid_points[:5]), len(invalid_points), 0))

    reconciliation_errors = []
    for point in points:
        try:
            marked_total = float(point.cash) + float(point.market_value)
        except (TypeError, ValueError, OverflowError):
            marked_total = math.nan
        if not _close(point.equity, marked_total, cfg):
            reconciliation_errors.append((point.timestamp.isoformat() if _aware(point.timestamp) else "invalid timestamp",
                                           point.equity, marked_total))
    findings.append(_finding("equity_cash_market_value_reconciliation", not reconciliation_errors,
                             "Equity equals cash plus marked market value at every observation." if not reconciliation_errors
                             else "Equity does not reconcile to cash plus marked market value.",
                             len(reconciliation_errors), 0))

    cost_sum = sum(float(getattr(fill, "commission", 0)) + float(getattr(fill, "slippage_cost", 0))
                   for _, fill in all_fills if all(isinstance(getattr(fill, k, None), (int, float)) and math.isfinite(getattr(fill, k))
                                                   for k in ("commission", "slippage_cost")))
    costs_ok = isinstance(result.total_transaction_costs, (int, float)) and math.isfinite(result.total_transaction_costs) and result.total_transaction_costs >= 0 and _close(result.total_transaction_costs, cost_sum, cfg)
    findings.append(_finding("transaction_cost_reconciliation", costs_ok,
                             "Reported total transaction costs reconcile to actual Fill records." if costs_ok
                             else "Reported transaction costs are negative, non-finite, or do not reconcile to Fill records.",
                             result.total_transaction_costs, cost_sum))

    point_cost_errors = []
    for point in points:
        upto = sum(float(fill.commission) + float(fill.slippage_cost) for _, fill in all_fills
                   if _aware(getattr(fill, "fill_timestamp", None)) and _aware(point.timestamp)
                   and fill.fill_timestamp <= point.timestamp)
        if not _close(point.total_transaction_costs, upto, cfg):
            point_cost_errors.append((point.timestamp, point.total_transaction_costs, upto))
    findings.append(_finding("cumulative_cost_curve_reconciliation", not point_cost_errors,
                             "Cumulative costs at portfolio observations match fills counted through each timestamp."
                             if not point_cost_errors else "Portfolio cost history does not match cumulative actual fill costs.",
                             len(point_cost_errors), 0))

    negative_positions = []
    for position in result.position_history:
        q = getattr(position, "quantity", math.nan)
        if not isinstance(q, (int, float)) or not math.isfinite(q) or q < -cfg.absolute_tolerance:
            negative_positions.append((getattr(position, "asset", None), q))
    findings.append(_finding("nonnegative_position_quantities", not negative_positions,
                             "All position-history quantities are finite and non-negative." if not negative_positions
                             else "Negative or non-finite position quantity found.", len(negative_positions), 0))

    invalid_trade_values = []
    for trade in trades:
        for field in ("reference_price", "fill_price", "quantity", "notional", "commission", "slippage_cost", "realized_pnl"):
            value = getattr(trade, field, math.nan)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                invalid_trade_values.append(f"{field} is non-finite")
        if any(_not_positive(value) for value in
               (getattr(trade, "reference_price", None), getattr(trade, "fill_price", None), getattr(trade, "quantity", None))):
            invalid_trade_values.append("trade price and quantity must be positive")
        if _below(getattr(trade, "commission", -1), 0) or _below(getattr(trade, "slippage_cost", -1), 0):
            invalid_trade_values.append("trade costs must be non-negative")
    findings.append(_finding("trade_record_values", not invalid_trade_values,
                             "TradeRecord numerical values are finite and have valid signs." if not invalid_trade_values
                             else "; ".join(invalid_trade_values[:5]), len(invalid_trade_values), 0))
    invalid_asset_summaries = []
    for summary in result.per_asset:
        if (not isinstance(summary.cycles, int) or summary.cycles < 0 or
                not isinstance(summary.fills, int) or summary.fills < 0 or
                not _finite_number(summary.average_holding_days) or summary.average_holding_days < 0 or
                not _finite_number(summary.total_notional_traded) or summary.total_notional_traded < 0):
            invalid_asset_summaries.append(summary.asset)
    findings.append(_finding("per_asset_summary_values", not invalid_asset_summaries,
                             "Per-asset summary counts and values are finite and non-negative." if not invalid_asset_summaries
                             else "Invalid negative or non-finite per-asset summary values.",
                             len(invalid_asset_summaries), 0))

    fills_in_trade_order = [filled_by_order.get(getattr(t, "order_id", None)) for t in trades]
    quantities: dict[str, float] = defaultdict(float)
    cash = float(result.configuration.initial_capital or 0.0)
    trade_errors = []
    for trade, fill in zip(trades, fills_in_trade_order):
        if fill is None:
            continue
        asset, side = fill.asset, fill.side
        try:
            q, notional = float(fill.quantity), float(fill.quantity) * float(fill.fill_price)
            cost = float(fill.commission) + float(fill.slippage_cost)
        except (TypeError, ValueError, OverflowError):
            continue
        if not all(math.isfinite(v) for v in (q, notional, cost)) or q <= 0 or notional <= 0 or cost < 0:
            continue
        if side == "SELL" and q > quantities[asset] + cfg.absolute_tolerance:
            trade_errors.append(f"SELL {asset} quantity exceeds available position")
        if side == "BUY":
            cash -= notional + cost
            quantities[asset] += q
            if cash < -cfg.absolute_tolerance:
                trade_errors.append(f"BUY {asset} produces negative cash")
        elif side == "SELL":
            cash += notional - cost
            quantities[asset] = max(0.0, quantities[asset] - q)
    findings.append(_finding("sequential_fill_accounting_feasibility", not trade_errors,
                             "Fills can be sequentially replayed without oversells or negative cash." if not trade_errors
                             else "; ".join(trade_errors[:5]), len(trade_errors), 0))
    state_errors = []
    for position in result.position_history:
        if not _aware(getattr(position, "timestamp", None)):
            continue
        expected_quantity = sum(float(fill.quantity) if fill.side == "BUY" else -float(fill.quantity)
                                for trade, fill in zip(trades, fills_in_trade_order)
                                if fill is not None and fill.asset == position.asset
                                and isinstance(getattr(fill, "quantity", None), (int, float)) and math.isfinite(fill.quantity)
                                and _aware(fill.fill_timestamp) and fill.fill_timestamp <= position.timestamp)
        expected_quantity = max(0.0, expected_quantity)
        if not _close(position.quantity, expected_quantity, cfg):
            state_errors.append((position.asset, position.timestamp, position.quantity, expected_quantity))
    findings.append(_finding("no_future_fills_in_position_history", not state_errors,
                             "Position snapshots include only fills timestamped at or before each observation." if not state_errors
                             else "Position history quantity includes future fills or otherwise fails the timestamped fill replay.",
                             len(state_errors), 0))

    curve_timestamps = [getattr(p, "timestamp", None) for p in points]
    curve_aware = all(_aware(ts) for ts in curve_timestamps)
    curve_ordered = curve_aware and all(a < b for a, b in zip(curve_timestamps, curve_timestamps[1:]))
    findings.append(_finding("portfolio_timestamp_order", curve_ordered,
                             "Portfolio timestamps are aware, unique, and strictly increasing." if curve_ordered
                             else "Portfolio timestamps are invalid, duplicated, or out of order.", len(curve_timestamps), "strictly increasing"))
    position_keys = [(getattr(p, "asset", None), getattr(p, "timestamp", None)) for p in result.position_history]
    pos_times = [ts for _, ts in position_keys]
    position_ordered = all(_aware(ts) for ts in pos_times) and all(a <= b for a, b in zip(pos_times, pos_times[1:])) and len(position_keys) == len(set(position_keys))
    findings.append(_finding("position_history_timestamp_order", position_ordered,
                             "Position history is aware, chronological, and unique per asset/timestamp." if position_ordered
                             else "Position history has invalid/duplicate asset timestamps or is out of order.", len(position_keys), "ordered and unique"))

    final_state_errors = []
    if points:
        for asset in set(quantities) | {p.asset for p in result.position_history}:
            history = [p for p in result.position_history if p.asset == asset]
            final_q = history[-1].quantity if history else 0.0
            if not _close(final_q, quantities.get(asset, 0.0), cfg):
                final_state_errors.append((asset, final_q, quantities.get(asset, 0.0)))
    findings.append(_finding("final_open_position_state", not final_state_errors,
                             "Final position history matches sequentially replayed filled quantities; open positions remain explicitly observable."
                             if not final_state_errors else "Final open position quantities do not match sequentially replayed fills.",
                             len(final_state_errors), 0))

    return tuple(findings)


def inspect_temporal(result: BacktestResult, cfg: ValidationConfig) -> tuple[Finding, ...]:
    findings = []
    errors = []
    ordering_errors = []
    for record in result.orders:
        order = getattr(record, "order", None)
        if order is None:
            continue
        fields = (getattr(order, "signal_timestamp", None), getattr(order, "decision_timestamp", None),
                  getattr(order, "order_timestamp", None))
        if not all(_aware(t) for t in fields):
            ordering_errors.append("order timestamp is not timezone-aware")
        elif not fields[0] <= fields[1] <= fields[2]:
            ordering_errors.append("signal, decision, and order timestamps are not ordered")
    findings.append(_finding("order_timestamp_order", not ordering_errors,
                             "All orders have aware, ordered signal/decision/order timestamps." if not ordering_errors
                             else "; ".join(ordering_errors[:5]), len(ordering_errors), 0))
    filled = [(record.order, record.fill) for record in result.orders if record.fill is not None and record.order is not None]
    for order, fill in filled:
        fields = (order.signal_timestamp, order.decision_timestamp, order.order_timestamp, fill.fill_timestamp)
        if not all(_aware(t) for t in fields):
            errors.append("order/fill timestamp is not timezone-aware")
            continue
        if not order.signal_timestamp <= order.decision_timestamp <= order.order_timestamp:
            errors.append("signal, decision, and order timestamps are not ordered")
        if not (fill.fill_timestamp > order.signal_timestamp and fill.fill_timestamp > order.decision_timestamp):
            errors.append("fill is not strictly later than signal and decision (same-bar/future-order violation)")
        if fill.fill_timestamp < order.order_timestamp:
            errors.append("fill precedes order timestamp")
    findings.append(_finding("strictly_later_fill", not errors,
                             "Every recorded Fill occurs after its signal and decision timestamps." if not errors
                             else "; ".join(errors[:5]), len(errors), 0))
    model = getattr(result.configuration, "execution_model", None)
    findings.append(_finding("explicit_next_bar_open_model", model == "next_bar_open",
                             "Configured execution model is next_bar_open." if model == "next_bar_open"
                             else "Execution model is absent or differs from the documented next_bar_open contract.", model, "next_bar_open"))
    pending_errors = []
    executed_ids = {getattr(getattr(record, "order", None), "order_id", None)
                    for record in result.orders if getattr(record, "fill", None) is not None}
    for record in result.pending_orders:
        if getattr(record, "fill", None) is not None or getattr(record, "status", None) == "FILLED":
            pending_errors.append("pending order is marked as executed")
        order = getattr(record, "order", None)
        order_status = getattr(getattr(order, "status", None), "value", getattr(order, "status", None)) if order else None
        if order is not None and order.order_id in executed_ids:
            pending_errors.append("pending order ID is also recorded as executed")
        if order is not None and getattr(record, "status", None) == "PENDING" and order_status == "FILLED":
            pending_errors.append("pending order's Order status is FILLED")
    findings.append(_finding("pending_orders_unfilled", not pending_errors,
                             "End-of-data pending orders contain no fills." if not pending_errors else "; ".join(pending_errors),
                             len(pending_errors), 0))
    trade_times = [getattr(trade, "fill_timestamp", None) for trade in result.trades]
    trade_times_valid = all(_aware(ts) for ts in trade_times) and all(a <= b for a, b in zip(trade_times, trade_times[1:]))
    findings.append(_finding("trade_fill_chronology", trade_times_valid,
                             "TradeRecords are in timezone-aware nondecreasing fill-time order." if trade_times_valid
                             else "TradeRecords contain invalid or out-of-order fill timestamps.", len(trade_times), "chronological"))
    findings.append(Finding("next_available_bar_open_price", S.NOT_EVALUABLE, V.WARNING,
                            "BacktestResult has no source OHLC bars, so the fill timestamp and price cannot be matched to the exact next bar open.",
                            None, "source next-bar open"))
    return tuple(findings)
