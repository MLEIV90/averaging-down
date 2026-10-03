from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import pandas as pd


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFORMATIONAL = "INFORMATIONAL"


@dataclass(frozen=True)
class ValidationIssue:
    severity: Severity
    code: str
    message: str


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def add(self, severity: Severity, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(severity, code, message))


class DataValidator:
    """OHLCV checks for source or normalized market data."""

    REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

    def validate(
        self,
        frame: pd.DataFrame | None,
        *,
        duplicate_rows_are_errors: bool = True,
        volume_required: bool = True,
    ) -> ValidationReport:
        report = ValidationReport()
        if frame is None or frame.empty:
            report.add(Severity.ERROR, "empty_dataset", "Dataset is empty or missing.")
            return report

        if not isinstance(frame.index, pd.DatetimeIndex):
            report.add(Severity.ERROR, "invalid_index", "Index must be a DatetimeIndex.")
            return report
        if frame.index.tz is None:
            report.add(Severity.ERROR, "timezone_naive", "Validated timestamps must carry an explicit timezone.")

        required = list(self.REQUIRED_COLUMNS if volume_required else self.REQUIRED_COLUMNS[:-1])
        missing = [column for column in required if column not in frame.columns]
        if missing:
            report.add(Severity.ERROR, "missing_columns", f"Missing required columns: {missing}.")
            return report
        if frame.columns.duplicated().any():
            report.add(Severity.ERROR, "duplicate_columns", "Column names must be unique.")
            return report

        if not frame.index.is_monotonic_increasing:
            report.add(Severity.ERROR, "unordered_timestamps", "Timestamps must be ascending.")
        if frame.index.has_duplicates:
            report.add(Severity.ERROR, "duplicate_timestamps", "Timestamps must be unique.")
        if duplicate_rows_are_errors and frame.reset_index(drop=False).duplicated().any():
            report.add(Severity.ERROR, "duplicate_rows", "Fully duplicated rows are not allowed.")

        essentials = [column for column in required if column in frame.columns]
        numeric: dict[str, pd.Series] = {}
        for column in essentials:
            values = pd.to_numeric(frame[column], errors="coerce")
            numeric[column] = values
            if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float, na_value=np.nan)).all():
                report.add(Severity.ERROR, "invalid_numeric", f"'{column}' contains null or non-finite values.")
        if report.errors:
            return report

        if any((numeric[column] <= 0).any() for column in ("open", "high", "low", "close")):
            report.add(Severity.ERROR, "non_positive_price", "OHLC prices must be positive.")
        if (numeric["high"] < pd.concat([numeric["open"], numeric["close"], numeric["low"]], axis=1).max(axis=1)).any():
            report.add(Severity.ERROR, "invalid_high", "High must be >= max(Open, Close, Low).")
        if (numeric["low"] > pd.concat([numeric["open"], numeric["close"], numeric["high"]], axis=1).min(axis=1)).any():
            report.add(Severity.ERROR, "invalid_low", "Low must be <= min(Open, Close, High).")
        if "volume" in frame.columns:
            volume = numeric.get("volume", pd.to_numeric(frame["volume"], errors="coerce"))
            if volume.isna().any() or (volume < 0).any():
                report.add(Severity.ERROR, "invalid_volume", "Volume must be present and non-negative.")
        return report


def validate_ohlcv(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """Compatibility wrapper for the original validator API."""
    report = DataValidator().validate(df)
    return report.is_valid, [issue.message for issue in report.issues if issue.severity == Severity.ERROR]
