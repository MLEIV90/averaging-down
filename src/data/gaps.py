from dataclasses import dataclass

import pandas as pd

from .config import AssetDataConfig
from .validator import Severity, ValidationIssue


@dataclass(frozen=True)
class DataGap:
    start: pd.Timestamp
    end: pd.Timestamp
    missing_observations: int | None
    classification: str
    severity: Severity
    message: str


def detect_gaps(
    frame: pd.DataFrame,
    config: AssetDataConfig,
    *,
    expected_start: str | None = None,
    expected_end: str | None = None,
) -> list[DataGap]:
    """Report daily gaps without imputing values.

    Weekends are recognized for exchange-traded assets. Holiday calendars are
    not bundled, so gaps spanning weekdays are reported as calendar-ambiguous
    instead of being silently filled or asserted to be missing sessions.
    """
    if frame.empty:
        return []
    dates = pd.DatetimeIndex(frame.index).tz_convert("UTC").normalize()
    gaps: list[DataGap] = []
    for left, right in zip(dates[:-1], dates[1:]):
        delta_days = (right - left).days
        if delta_days <= 1:
            continue
        business_days = len(pd.bdate_range(left + pd.Timedelta(days=1), right - pd.Timedelta(days=1)))
        if config.asset_class.lower() == "crypto":
            expected_missing = delta_days - 1
            gaps.append(DataGap(left, right, expected_missing, "unexpected_24_7_gap", Severity.WARNING,
                                f"{expected_missing} daily observation(s) missing for a 24/7 asset."))
        elif business_days == 0:
            gaps.append(DataGap(left, right, 0, "expected_weekend_closure", Severity.INFORMATIONAL,
                                "Gap falls entirely on a weekend; no fill was applied."))
        else:
            gaps.append(DataGap(left, right, business_days, "calendar_ambiguous", Severity.WARNING,
                                f"Gap spans {business_days} weekdays; exchange holidays and missing sessions cannot be distinguished without a holiday calendar."))

    if expected_start:
        bound = pd.Timestamp(expected_start)
        if bound.tzinfo is None:
            bound = bound.tz_localize("UTC")
        first = dates[0]
        if first > bound.normalize():
            gaps.append(DataGap(bound, first, None, "missing_leading_range", Severity.WARNING,
                                f"Loaded history starts after requested start {expected_start}."))
    if expected_end:
        bound = pd.Timestamp(expected_end)
        if bound.tzinfo is None:
            bound = bound.tz_localize("UTC")
        last = dates[-1]
        if last < bound.normalize():
            gaps.append(DataGap(last, bound, None, "missing_trailing_range", Severity.INFORMATIONAL,
                                f"Latest observation precedes requested end {expected_end}; the end may be exclusive or the last session may not have completed."))
    return gaps


def gap_issues(gaps: list[DataGap]) -> list[ValidationIssue]:
    return [ValidationIssue(gap.severity, "data_gap", gap.message) for gap in gaps]
