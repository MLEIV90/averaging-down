"""Immutable output types for reproducible research diagnostics."""
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ResearchMetricDelta:
    metric: str
    baseline_value: float | int | None
    experiment_value: float | int | None
    absolute_difference: float | None
    relative_difference: float | None

@dataclass(frozen=True)
class ResearchExperimentResult:
    experiment_id: str
    experiment_type: str
    component: str
    parameter: str | None
    value: Any
    baseline_value: Any
    baseline_configuration_hash: str
    configuration_hash: str
    status: str
    description: str
    analytics: Any = None
    validation: Any = None
    metric_deltas: tuple[ResearchMetricDelta, ...] = ()
    backtest_result: Any = None

@dataclass(frozen=True)
class AblationResult(ResearchExperimentResult):
    pass

@dataclass(frozen=True)
class SensitivityResult(ResearchExperimentResult):
    pass

@dataclass(frozen=True)
class ResearchSuiteResult:
    baseline_configuration_hash: str
    baseline: ResearchExperimentResult
    ablations: tuple[AblationResult, ...]
    sensitivities: tuple[SensitivityResult, ...]
    report_json: str
