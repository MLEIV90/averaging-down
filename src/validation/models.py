from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias


class FindingStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class OverallStatus(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class SampleLabel(str, Enum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    LIMITED_SAMPLE = "LIMITED_SAMPLE"
    ADEQUATE_FOR_DESCRIPTIVE_ANALYSIS = "ADEQUATE_FOR_DESCRIPTIVE_ANALYSIS"


Scalar: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True)
class Finding:
    check_name: str
    status: FindingStatus
    severity: Severity
    message: str
    measured_value: Scalar = None
    expected_value: Scalar = None


@dataclass(frozen=True)
class Metric:
    name: str
    value: Scalar
    unit: str | None = None


@dataclass(frozen=True)
class Section:
    status: FindingStatus
    findings: tuple[Finding, ...]
    metrics: tuple[Metric, ...] = ()


@dataclass(frozen=True)
class BenchmarkComparison:
    strategy_total_return: float | None
    benchmark_total_return: float | None
    excess_return: float | None
    strategy_cagr: float | None
    benchmark_cagr: float | None
    strategy_maximum_drawdown: float | None
    benchmark_maximum_drawdown: float | None
    drawdown_difference: float | None
    strategy_volatility: float | None
    benchmark_volatility: float | None
    strategy_sharpe: float | None
    benchmark_sharpe: float | None
    strategy_final_equity_common_capital: float | None
    benchmark_final_equity_common_capital: float | None


@dataclass(frozen=True)
class AssetConcentration:
    asset: str
    realized_pnl: float | None
    realized_pnl_contribution: float | None
    realized_pnl_abs_share: float | None
    fills: int
    fill_share: float | None
    traded_notional: float | None
    traded_notional_share: float | None
    average_cost_basis_exposure: float | None
    exposure_share: float | None


@dataclass(frozen=True)
class ScaleInDiagnostic:
    status: FindingStatus
    findings: tuple[Finding, ...]
    scale_in_fills: int | None
    completed_cycles: int | None
    multi_entry_cycles: int | None
    multi_entry_cycle_percentage: float | None
    average_entries_per_completed_cycle: float | None
    maximum_entries_in_cycle: int | None
    multi_entry_traded_notional: float | None
    multi_entry_realized_pnl: float | None
    single_entry_realized_pnl: float | None
    open_cycles: int | None
    counterfactual_no_scale_in: float | None


@dataclass(frozen=True)
class CostDiagnostic:
    findings: tuple[Finding, ...]
    configured_commission_bps: float | None
    configured_slippage_bps: float | None
    total_costs: float | None
    cost_over_initial_capital: float | None
    cost_over_traded_notional: float | None
    final_equity_after_costs: float | None
    total_return_after_costs: float | None
    mechanically_added_back_costs_final_equity: float | None
    mechanically_added_back_costs_return: float | None
    mechanical_cost_addback_difference: float | None
    counterfactual_no_cost_strategy_return: float | None


@dataclass(frozen=True)
class SampleSizeDiagnostic:
    findings: tuple[Finding, ...]
    label: SampleLabel
    portfolio_observations: int
    fills: int
    completed_cycles: int
    winning_cycles: int
    losing_cycles: int
    multi_entry_cycles: int | None


@dataclass(frozen=True)
class ExposureDiagnostic:
    findings: tuple[Finding, ...]
    average_gross_exposure: float | None
    maximum_gross_exposure: float | None
    average_net_exposure: float | None
    maximum_net_exposure: float | None
    time_invested_percent: float | None
    assets: tuple[AssetConcentration, ...]
    maximum_realized_pnl_concentration: float | None
    maximum_fill_concentration: float | None
    maximum_notional_concentration: float | None
    maximum_exposure_concentration: float | None


@dataclass(frozen=True)
class ValidationReport:
    integrity: Section
    temporal_integrity: Section
    determinism: Section
    benchmark: Section
    benchmark_comparison: BenchmarkComparison | None
    costs: CostDiagnostic
    scale_in: ScaleInDiagnostic
    exposure: ExposureDiagnostic
    sample_size: SampleSizeDiagnostic
    degeneracy: Section
    overall_status: OverallStatus
    interpretation: str
    limitations: tuple[str, ...]
