from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd

from src.analytics import load_analytics_config, run_analytics
from src.backtest.sequential import BacktestResult
from .config import ValidationConfig
from .models import BenchmarkComparison, Finding, FindingStatus as S, Severity as V, Section


def inspect_benchmark(result: BacktestResult, benchmark: pd.Series | Sequence[float] | None,
                      benchmark_timestamps: Sequence | None, cfg: ValidationConfig):
    if benchmark is None:
        finding = Finding("benchmark_supplied", S.WARNING, V.WARNING,
                          "No benchmark supplied; relative performance is not evaluated.")
        return Section(S.WARNING, (finding,)), None
    points = result.portfolio_curve
    values: tuple[float, ...]
    timestamps = None
    errors = []
    if isinstance(benchmark, pd.Series):
        try:
            values = tuple(float(v) for v in benchmark.to_list())
        except (TypeError, ValueError, OverflowError):
            values = ()
            errors.append(("benchmark_values", "invalid", "finite numeric values", "Benchmark equity must contain numeric values."))
        timestamps = tuple(benchmark.index.to_list())
    else:
        try:
            values = tuple(float(v) for v in benchmark)
        except (TypeError, ValueError, OverflowError):
            values = ()
    if len(values) != len(points):
        errors.append(("benchmark_length", len(values), len(points), "Benchmark length must match portfolio observations."))
    if timestamps is not None and len(timestamps) == len(points):
        expected = tuple(p.timestamp for p in points)
        if timestamps != expected:
            errors.append(("benchmark_timestamps", "mismatch", "strategy timestamps", "Benchmark timestamps must match exactly."))
    if benchmark_timestamps is not None:
        supplied = tuple(benchmark_timestamps)
        if len(supplied) != len(points) or supplied != tuple(p.timestamp for p in points):
            errors.append(("benchmark_timestamps", "mismatch", "strategy timestamps", "Supplied benchmark timestamps must match exactly."))
    invalid = [v for v in values if not math.isfinite(v) or v < 0]
    if invalid:
        errors.append(("benchmark_values", len(invalid), 0, "Benchmark equity must be finite and non-negative."))
    if values and values[0] <= 0:
        errors.append(("benchmark_starting_equity", values[0], "> 0", "Benchmark requires positive starting equity for returns."))
    if errors:
        findings = tuple(Finding(name, S.FAIL, V.ERROR, message, measured, expected)
                         for name, measured, expected, message in errors)
        return Section(S.FAIL, findings), None
    if not values:
        finding = Finding("benchmark_values", S.NOT_EVALUABLE, V.WARNING,
                          "Benchmark curve is empty; comparison cannot be evaluated.")
        return Section(S.NOT_EVALUABLE, (finding,)), None

    try:
        analytics = run_analytics(result)
        strategy_metrics_available = True
    except (ValueError, TypeError, OverflowError, FloatingPointError):
        analytics = None
        strategy_metrics_available = False
    convention = load_analytics_config()
    annualization = analytics.annualization if analytics else convention.annualization
    if len(values) > 1 and all(x > 0 for x in values[:-1]):
        b_returns = np.diff(np.asarray(values, dtype=float)) / np.asarray(values[:-1], dtype=float)
        b_vol = float(np.std(b_returns, ddof=1) * math.sqrt(annualization)) if len(b_returns) > 1 else None
        b_std = float(np.std(b_returns, ddof=1)) if len(b_returns) > 1 else 0.0
        rf_daily = (analytics.risk_free_rate if analytics else convention.risk_free_rate) / annualization
        b_sharpe = float((np.mean(b_returns) - rf_daily) / b_std * math.sqrt(annualization)) if b_std else None
    else:
        b_returns = np.asarray([])
        b_vol = b_sharpe = None
    b_total = values[-1] / values[0] - 1 if len(values) > 1 else None
    years = (len(values) - 1) / annualization
    b_cagr = (values[-1] / values[0]) ** (1 / years) - 1 if years > 0 and values[-1] > 0 else (-1.0 if years > 0 else None)
    b_hwm = np.maximum.accumulate(values)
    b_dd = np.asarray(values) / b_hwm - 1
    b_max_dd = float(np.min(b_dd)) if len(values) else None
    strategy = analytics
    initial_value = getattr(result.configuration, "initial_capital", None)
    initial = float(initial_value) if isinstance(initial_value, (int, float)) and math.isfinite(initial_value) and initial_value > 0 else 0.0
    normalized_bench_final = initial * values[-1] / values[0] if initial > 0 else None
    normalized_strategy_final = (initial * strategy.final_equity / points[0].equity
                                 if initial > 0 and strategy and points and points[0].equity > 0 else None)
    comparison = BenchmarkComparison(
        strategy.total_return if strategy else None, b_total,
        strategy.total_return - b_total if strategy and strategy.total_return is not None and b_total is not None else None,
        strategy.cagr if strategy else None, b_cagr,
        strategy.maximum_drawdown if strategy else None, b_max_dd,
        strategy.maximum_drawdown - b_max_dd if strategy and strategy.maximum_drawdown is not None and b_max_dd is not None else None,
        strategy.annualized_volatility if strategy else None, b_vol,
        strategy.sharpe_ratio if strategy else None, b_sharpe,
        normalized_strategy_final, normalized_bench_final,
    )
    finding = Finding("benchmark_alignment_and_values", S.PASS if strategy_metrics_available else S.WARNING,
                      V.INFO if strategy_metrics_available else V.WARNING,
                      "Caller-supplied benchmark matches strategy observations and contains valid equity values; comparison is descriptive only."
                      if strategy_metrics_available else "Benchmark is valid, but strategy metrics are unavailable because portfolio observations failed validation.",
                      len(values), len(points))
    return Section(finding.status, (finding,)), comparison
