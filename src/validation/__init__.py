"""Research-integrity diagnostics for sequential BacktestResult objects."""

from .config import ValidationConfig, load_validation_config
from .engine import (canonical_json, report_sha256, run_backtest_twice,
                     run_validation, validation_report_sha256)
from .models import (BenchmarkComparison, Finding, FindingStatus, OverallStatus,
                     SampleLabel, Severity, ValidationReport)

__all__ = ["BenchmarkComparison", "Finding", "FindingStatus", "OverallStatus",
           "SampleLabel", "Severity", "ValidationConfig", "ValidationReport",
           "canonical_json", "load_validation_config", "report_sha256",
           "run_backtest_twice", "run_validation", "validation_report_sha256"]
