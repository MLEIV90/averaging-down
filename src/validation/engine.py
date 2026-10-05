"""Standalone research-integrity validation for the sequential backtest result."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime
from enum import Enum
import hashlib
import json
from typing import Callable, Sequence

import pandas as pd

from src.backtest.sequential import BacktestResult
from .benchmarks import inspect_benchmark
from .config import ValidationConfig, load_validation_config
from .diagnostics import (cost_diagnostic, degeneracy_diagnostic, exposure_diagnostic,
                          sample_size_diagnostic, scale_in_diagnostic, _status)
from .invariants import inspect_integrity, inspect_temporal
from .models import (Finding, FindingStatus as S, OverallStatus, Section,
                     Severity as V, ValidationReport)


def _jsonable(value):
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted((_jsonable(item) for item in value), key=repr)
    return value


def canonical_json(value) -> str:
    """Canonical JSON for stable validation reports and deterministic hashes."""
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def report_sha256(report: ValidationReport) -> str:
    return hashlib.sha256(canonical_json(report).encode("utf-8")).hexdigest()


def _section(findings, metrics=()):
    return Section(_status(findings), tuple(findings), tuple(metrics))


def _core(result: BacktestResult, benchmark, benchmark_timestamps, cfg: ValidationConfig):
    integrity_findings = inspect_integrity(result, cfg)
    temporal_findings = inspect_temporal(result, cfg)
    scale = scale_in_diagnostic(result, cfg)
    exposure = exposure_diagnostic(result, cfg, scale)
    sample = sample_size_diagnostic(result, scale, cfg)
    benchmark_section, comparison = inspect_benchmark(result, benchmark, benchmark_timestamps, cfg)
    costs = cost_diagnostic(result, cfg)
    degeneracy = degeneracy_diagnostic(result, cfg, scale, exposure)
    if not result.portfolio_curve:
        empty_finding = Finding("portfolio_observations", S.NOT_EVALUABLE, V.WARNING,
                                "BacktestResult has no portfolio observations; return and drawdown checks are not evaluable.", 0, "> 0")
        integrity_findings = integrity_findings + (empty_finding,)
    return {
        "integrity": _section(integrity_findings),
        "temporal_integrity": _section(temporal_findings),
        "benchmark": benchmark_section,
        "benchmark_comparison": comparison,
        "costs": costs,
        "scale_in": scale,
        "exposure": exposure,
        "sample_size": sample,
        "degeneracy": degeneracy,
    }


def _overall(core, determinism: Section) -> OverallStatus:
    if core["integrity"].status == S.FAIL or core["temporal_integrity"].status == S.FAIL or determinism.status == S.FAIL:
        return OverallStatus.FAIL
    findings = []
    for name in ("integrity", "temporal_integrity", "benchmark", "degeneracy"):
        findings.extend(core[name].findings)
    findings.extend(core["costs"].findings)
    findings.extend(core["scale_in"].findings)
    findings.extend(core["exposure"].findings)
    findings.extend(core["sample_size"].findings)
    findings.extend(determinism.findings)
    if all(f.status == S.NOT_EVALUABLE for f in findings):
        return OverallStatus.NOT_EVALUABLE
    if any(f.status in {S.WARNING, S.NOT_EVALUABLE, S.FAIL} for f in findings):
        return OverallStatus.PASS_WITH_WARNINGS
    return OverallStatus.PASS


def _make_report(core, deterministic: bool, digest: str, result: BacktestResult):
    finding = Finding("repeated_validation", S.PASS if deterministic else S.FAIL,
                      V.INFO if deterministic else V.CRITICAL,
                      "Repeated validation of the same immutable input produced the same canonical report."
                      if deterministic else "Repeated validation of the same input produced different canonical reports.",
                      digest, digest if deterministic else "identical digest")
    determinism = Section(S.PASS if deterministic else S.FAIL, (finding,))
    limitations = (
        "Passing M12 does not establish that the strategy has predictive power, positive expected return, statistical significance, or live-trading viability.",
        "Structural timestamp checks provide evidence against specified timing violations; they are not a mathematical proof of no look-ahead.",
        "BacktestResult contains no source OHLC bars, so exact next-available-bar open-price matching cannot be independently checked.",
        "Mechanical cost add-back describes accounting costs on the observed path; it is not a no-cost strategy counterfactual because costs can affect accepted quantities.",
        "Scale-in diagnostics group actual tiered entry fills and confirmed flat cycles; they do not fabricate a no-scale-in result.",
        "Per-asset exposure is a position-history average-entry-price proxy; exact per-asset marked exposures and open-position unrealized P&L cannot be reconstructed without per-asset marks.",
        "Sample labels are configurable descriptive warnings, not formal power, significance, or profitability tests.",
        "Benchmark comparisons use only caller-supplied aligned equity curves and do not establish alpha or causation.",
    )
    status = _overall(core, determinism)
    return ValidationReport(**core, determinism=determinism, overall_status=status,
                            interpretation="This report assesses internal consistency and research diagnostics only; it does not rate profitability.",
                            limitations=limitations)


def run_validation(backtest_result: BacktestResult, *,
                   benchmark: pd.Series | Sequence[float] | None = None,
                   benchmark_timestamps: Sequence | None = None,
                   config: ValidationConfig | None = None) -> ValidationReport:
    """Validate one sequential result without changing or re-running the strategy."""
    if not isinstance(backtest_result, BacktestResult):
        raise TypeError("backtest_result must be a BacktestResult.")
    cfg = config or load_validation_config()
    first = _core(backtest_result, benchmark, benchmark_timestamps, cfg)
    second = _core(backtest_result, benchmark, benchmark_timestamps, cfg)
    first_json, second_json = canonical_json(first), canonical_json(second)
    digest = hashlib.sha256(first_json.encode("utf-8")).hexdigest()
    return _make_report(first, first_json == second_json, digest, backtest_result)


def run_backtest_twice(backtest_function: Callable, *args, **kwargs) -> tuple[bool, str, str]:
    """Run a caller-supplied deterministic backtest twice and compare canonical results."""
    first = backtest_function(*args, **kwargs)
    second = backtest_function(*args, **kwargs)
    first_hash = hashlib.sha256(canonical_json(first).encode("utf-8")).hexdigest()
    second_hash = hashlib.sha256(canonical_json(second).encode("utf-8")).hexdigest()
    return first_hash == second_hash, first_hash, second_hash


def validation_report_sha256(report: ValidationReport) -> str:
    """Stable digest of the full immutable report, including findings and metrics."""
    return report_sha256(report)
