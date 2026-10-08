"""Immutable models for walk-forward research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WalkForwardWindow:
    """One chronological walk-forward evaluation window.

    The warmup interval provides historical context required by indicators.
    Only the test interval is scored as OOS.
    """

    window_id: int

    warmup_start: datetime
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime

    embargo_start: datetime | None
    embargo_end: datetime | None

    config_hash: str

    def __post_init__(self) -> None:
        ordered = (
            self.warmup_start,
            self.train_start,
            self.train_end,
            self.validation_start,
            self.validation_end,
            self.test_start,
            self.test_end,
        )

        if any(
            left >= right
            for left, right in zip(ordered, ordered[1:])
        ):
            raise ValueError(
                "Walk-forward window timestamps must be strictly chronological."
            )

        if self.window_id < 0:
            raise ValueError("window_id must be non-negative.")

        if not self.config_hash:
            raise ValueError("config_hash must not be empty.")

        if self.embargo_start is None and self.embargo_end is not None:
            raise ValueError(
                "embargo_start is required when embargo_end is supplied."
            )

        if self.embargo_start is not None and self.embargo_end is None:
            raise ValueError(
                "embargo_end is required when embargo_start is supplied."
            )

        if (
            self.embargo_start is not None
            and self.embargo_end is not None
            and self.embargo_start >= self.embargo_end
        ):
            raise ValueError("Embargo interval must be strictly increasing.")

    @property
    def warmup_duration_days(self) -> float:
        return (
            self.train_start - self.warmup_start
        ).total_seconds() / 86400.0

    @property
    def train_duration_days(self) -> float:
        return (
            self.train_end - self.train_start
        ).total_seconds() / 86400.0

    @property
    def validation_duration_days(self) -> float:
        return (
            self.validation_end - self.validation_start
        ).total_seconds() / 86400.0

    @property
    def test_duration_days(self) -> float:
        return (
            self.test_end - self.test_start
        ).total_seconds() / 86400.0


@dataclass(frozen=True)
class WalkForwardConfig:
    """Configuration for chronological walk-forward splitting."""

    train_days: int = 756
    validation_days: int = 252
    test_days: int = 126
    step_days: int = 126

    warmup_days: int = 300
    embargo_days: int = 0

    expanding: bool = True

    min_windows: int = 2

    def __post_init__(self) -> None:
        for name in (
            "train_days",
            "validation_days",
            "test_days",
            "step_days",
            "warmup_days",
            "embargo_days",
            "min_windows",
        ):
            value = getattr(self, name)

            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer.")

            if value < 0:
                raise ValueError(f"{name} cannot be negative.")

        if self.train_days <= 0:
            raise ValueError("train_days must be positive.")

        if self.validation_days <= 0:
            raise ValueError("validation_days must be positive.")

        if self.test_days <= 0:
            raise ValueError("test_days must be positive.")

        if self.step_days <= 0:
            raise ValueError("step_days must be positive.")

        if self.min_windows <= 0:
            raise ValueError("min_windows must be positive.")
        
        if self.step_days < self.test_days:
            raise ValueError(
                "step_days must be greater than or equal to test_days "
                "to prevent overlapping OOS test windows."
            )