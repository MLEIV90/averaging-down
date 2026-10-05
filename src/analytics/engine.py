"""Deterministic performance analytics over actual sequential engine outputs."""

from __future__ import annotations

import math
from statistics import median
from typing import Sequence

import numpy as np
import pandas as pd

from src.backtest.sequential import BacktestResult
from .config import AnalyticsConfig, load_analytics_config
from .models import (AnalyticsReport, AssetReport, BenchmarkReport, CostReport,
                     DrawdownReport, ExposureReport, TradeReport)


def _finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def _curve(values: Sequence[float], annualization: int) -> tuple[float | None, float | None, float | None]:
    if len(values) < 2 or values[0] <= 0 or values[-1] < 0:
        return None, None, None
    periods = len(values) - 1
    cagr = (values[-1] / values[0]) ** (annualization / periods) - 1 if values[-1] > 0 else -1.0
    prior = np.asarray(values[:-1], dtype=float)
    if np.any(prior == 0):
        return _finite_or_none(cagr), None, None
    returns = np.diff(np.asarray(values, dtype=float)) / prior
    return _finite_or_none(cagr), _finite_or_none(float(np.std(returns, ddof=1)) * math.sqrt(annualization)) if len(returns) > 1 else None, _finite_or_none(float(returns.mean()))


def _drawdown(values: Sequence[float], timestamps) -> DrawdownReport:
    if not values:
        return DrawdownReport((), (), None, None, None, None, None, None, None)
    arr = np.asarray(values, dtype=float)
    hwm = np.maximum.accumulate(arr)
    dd = np.divide(arr, hwm, out=np.full_like(arr, np.nan), where=hwm != 0) - 1.0
    if not np.isfinite(dd).all():
        dd = np.nan_to_num(dd, nan=0.0)
    trough_i = int(np.argmin(dd))
    max_dd = float(dd[trough_i])
    peaks = np.flatnonzero((hwm[:trough_i + 1] == hwm[trough_i]) & (arr[:trough_i + 1] == hwm[trough_i]))
    start_i = int(peaks[-1]) if len(peaks) and max_dd < 0 else 0
    recovery_i = next((i for i in range(trough_i + 1, len(arr)) if arr[i] >= hwm[start_i]), None) if max_dd < 0 else 0
    duration = (recovery_i if recovery_i is not None else len(arr) - 1) - start_i if max_dd < 0 else 0
    return DrawdownReport(
        tuple(map(float, hwm)), tuple(map(float, dd)), max_dd,
        timestamps[start_i] if max_dd < 0 else None,
        timestamps[trough_i] if max_dd < 0 else None,
        timestamps[recovery_i] if recovery_i is not None and max_dd < 0 else None,
        duration, float(np.mean(dd)), float(np.sqrt(np.mean(np.square(dd)))),
    )


def _streaks(outcomes: Sequence[float]) -> tuple[int, int]:
    best_win = best_loss = wins = losses = 0
    for pnl in outcomes:
        wins, losses = (wins + 1, 0) if pnl > 0 else (0, losses + 1) if pnl < 0 else (0, 0)
        best_win, best_loss = max(best_win, wins), max(best_loss, losses)
    return best_win, best_loss


def _trade_stats(fills, completed: Sequence[float], holding: Sequence[float]) -> TradeReport:
    buy_count = sum(fill.side == "BUY" for fill in fills)
    sell_count = sum(fill.side == "SELL" for fill in fills)
    wins = [p for p in completed if p > 0]
    losses = [p for p in completed if p < 0]
    streak_wins, streak_losses = _streaks(completed)
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    return TradeReport(
        len(fills), buy_count, sell_count, len(completed), len(wins), len(losses),
        len(wins) / len(completed) if completed else None,
        float(np.mean(completed)) if completed else None,
        float(median(completed)) if completed else None,
        max(completed) if completed else None, min(completed) if completed else None,
        gross_profit, gross_loss, gross_profit / gross_loss if gross_loss else None,
        float(np.mean(wins)) if wins else None, float(np.mean(losses)) if losses else None,
        float(np.mean(holding)) if holding else None, streak_losses, streak_wins,
    )


def run_analytics(backtest_result: BacktestResult, *, benchmark: pd.Series | Sequence[float] | None = None,
                  config: AnalyticsConfig | None = None) -> AnalyticsReport:
    """Summarize a BacktestResult; benchmark values must align observation-for-observation."""
    if not isinstance(backtest_result, BacktestResult):
        raise TypeError("backtest_result must be a BacktestResult.")
    cfg = config or load_analytics_config()
    points = backtest_result.portfolio_curve
    timestamps = tuple(point.timestamp for point in points)
    equities = tuple(float(point.equity) for point in points)
    if any(not math.isfinite(v) or v < 0 for v in equities):
        raise ValueError("Portfolio equity observations must be finite and non-negative.")
    initial = float(backtest_result.configuration.initial_capital or 0.0)
    final = equities[-1] if equities else None
    total_return = (final / initial - 1) if final is not None and initial > 0 else None
    daily_returns = tuple((equities[i] / equities[i - 1] - 1) if equities[i - 1] else None for i in range(1, len(equities)))
    dd = _drawdown(equities, timestamps)
    cagr, volatility, _ = _curve(equities, cfg.annualization)
    if len(daily_returns) >= cfg.minimum_observations and all(r is not None for r in daily_returns):
        excess = np.asarray(daily_returns, dtype=float) - cfg.risk_free_rate / cfg.annualization
        sample_std = float(np.std(excess, ddof=1))
        downside = float(np.sqrt(np.mean(np.square(np.minimum(excess, 0.0)))))
        downside_ann = _finite_or_none(downside * math.sqrt(cfg.annualization))
        sharpe = _finite_or_none(float(np.mean(excess) / sample_std * math.sqrt(cfg.annualization))) if sample_std else None
        sortino = _finite_or_none(float(np.mean(excess) / downside * math.sqrt(cfg.annualization))) if downside else None
    else:
        downside_ann = sharpe = sortino = None
    calmar = _finite_or_none(cagr / abs(dd.maximum_drawdown)) if cagr is not None and dd.maximum_drawdown else None

    fills = tuple(record.fill for record in backtest_result.orders if record.fill is not None)
    position_by_asset_time = {(p.asset, p.timestamp): p for p in backtest_result.position_history}
    cycle_pnl: dict[str, float] = {}
    completed_pnl: list[float] = []
    completed_holding: list[float] = []
    for trade in backtest_result.trades:
        if trade.side != "SELL":
            continue
        cycle_pnl[trade.asset] = cycle_pnl.get(trade.asset, 0.0) + float(trade.realized_pnl)
        position = position_by_asset_time.get((trade.asset, trade.fill_timestamp))
        if position is not None and position.quantity == 0:
            completed_pnl.append(cycle_pnl.pop(trade.asset, 0.0))
            prior = [p for p in backtest_result.position_history
                     if p.asset == trade.asset and p.timestamp < trade.fill_timestamp and p.quantity > 0]
            state = prior[-1].state if prior else None
            if state is not None and state.entry_timestamp is not None:
                completed_holding.append((trade.fill_timestamp - state.entry_timestamp).total_seconds() / 86400)
    trade_report = _trade_stats(fills, completed_pnl, completed_holding)

    curves = [p.gross_exposure for p in points]
    net = [p.net_exposure for p in points]
    cash = [p.cash for p in points]
    invested = [p.market_value != 0 for p in points]
    exposure = ExposureReport(
        float(np.mean(curves)) if curves else None, max(curves) if curves else None,
        float(np.mean(net)) if net else None, max(net) if net else None,
        min(cash) if cash else None, float(np.mean(cash)) if cash else None,
        100.0 * sum(invested) / len(points) if points else None,
        100.0 * sum(not x for x in invested) / len(points) if points else None,
    )
    commissions = float(sum(f.commission for f in fills))
    slippage = float(sum(f.slippage_cost for f in fills))
    total_cost = commissions + slippage
    notional = float(sum(f.quantity * f.fill_price for f in fills))
    costs = CostReport(commissions, slippage, total_cost,
                       total_cost / initial if initial > 0 else None,
                       total_cost / notional if notional > 0 else None)

    asset_reports = []
    realized_total = sum(float(t.realized_pnl) for t in backtest_result.trades if t.side == "SELL")
    assets = sorted(set(a.asset for a in backtest_result.per_asset) | {p.asset for p in backtest_result.position_history} | {f.asset for f in fills})
    for asset in assets:
        summary = next((a for a in backtest_result.per_asset if a.asset == asset), None)
        asset_fills = [f for f in fills if f.asset == asset]
        asset_realized = sum(float(t.realized_pnl) for t in backtest_result.trades if t.asset == asset and t.side == "SELL")
        position_points = [p for p in backtest_result.position_history if p.asset == asset]
        exposures = [p.quantity * p.average_entry_price for p in position_points]
        asset_reports.append(AssetReport(
            asset, summary.cycles if summary else 0, len(asset_fills),
            float(sum(f.quantity * f.fill_price for f in asset_fills)),
            summary.average_holding_days if summary else None,
            asset_realized, asset_realized / realized_total if realized_total else None,
            asset_realized / initial if initial > 0 else None,
            float(sum(f.commission + f.slippage_cost for f in asset_fills)),
            float(np.mean(exposures)) if exposures else None, max(exposures) if exposures else None,
        ))

    benchmark_report = None
    if benchmark is not None:
        if isinstance(benchmark, pd.Series):
            bench_values = tuple(float(x) for x in benchmark.to_list())
            if len(benchmark) != len(points) or (len(points) and not pd.DatetimeIndex(benchmark.index).equals(pd.DatetimeIndex(timestamps))):
                raise ValueError("Benchmark Series must have timestamps matching portfolio_curve exactly.")
        else:
            bench_values = tuple(float(x) for x in benchmark)
            if len(bench_values) != len(points):
                raise ValueError("Benchmark values must match portfolio_curve length.")
        if any(not math.isfinite(v) or v < 0 for v in bench_values):
            raise ValueError("Benchmark equity values must be finite and non-negative.")
        b_cagr, _, _ = _curve(bench_values, cfg.annualization)
        b_dd = _drawdown(bench_values, timestamps)
        s_total = total_return
        b_total = bench_values[-1] / bench_values[0] - 1 if len(bench_values) > 1 and bench_values[0] > 0 else None
        benchmark_report = BenchmarkReport(s_total, b_total, cagr, b_cagr, dd.maximum_drawdown,
                                           b_dd.maximum_drawdown,
                                           s_total - b_total if s_total is not None and b_total is not None else None)

    return AnalyticsReport(
        initial, final, _finite_or_none(total_return) if total_return is not None else None,
        cagr, daily_returns, volatility, downside_ann, sharpe, sortino,
        dd.maximum_drawdown, dd.maximum_duration_observations, calmar,
        max((r for r in daily_returns if r is not None), default=None),
        min((r for r in daily_returns if r is not None), default=None),
        dd, trade_report, exposure, costs, tuple(asset_reports), benchmark_report,
        cfg.annualization, cfg.risk_free_rate,
        ("Returns are close-to-close portfolio-curve changes; each observation is treated as one session.",
         "Annualization and CAGR use 252 sessions by default; elapsed calendar days are not used.",
         "Volatility uses sample standard deviation (ddof=1); Sharpe uses daily mean excess return / sample deviation.",
         "Returns after a zero-equity observation are undefined and represented by null; volatility and ratios are then undefined.",
         "Sortino uses RMS of negative daily excess returns; risk-free rate is annual and divided by annualization.",
         "Drawdown is equity / running high-water mark - 1; recovery occurs at equality or a new high.",
         "Maximum drawdown duration counts observation intervals from its last peak to recovery; an unrecovered drawdown ends at the final observation.",
         "Average drawdown and Ulcer Index use signed fractional drawdown observations (the Ulcer Index is their RMS magnitude).",
         "A trade is a completed asset position cycle, aggregating realized SELL fill P&L until quantity reaches zero.",
         "Profit factor is gross positive completed-cycle P&L / absolute gross negative completed-cycle P&L.",
         "Buy-and-hold benchmark equity must be supplied by the caller and align exactly by observation.",
         "Per-asset exposure is quantity times recorded average entry price, a cost-basis proxy because no per-asset marked values are stored in position_history."),
    )
