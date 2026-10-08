"""Chronological walk-forward window generation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

import pandas as pd

from .models import WalkForwardConfig, WalkForwardWindow


def _as_timestamp(value: datetime | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Walk-forward timestamps must be timezone-aware.")

    return timestamp.tz_convert("UTC")


def _unique_sorted_timestamps(
    timestamps: Sequence[datetime | pd.Timestamp],
) -> list[pd.Timestamp]:
    result = sorted({_as_timestamp(value) for value in timestamps})

    if not result:
        raise ValueError("At least one timestamp is required.")

    return result


def _first_at_or_after(
    timestamps: list[pd.Timestamp],
    target: pd.Timestamp,
) -> pd.Timestamp | None:
    for timestamp in timestamps:
        if timestamp >= target:
            return timestamp
    return None


def _last_at_or_before(
    timestamps: list[pd.Timestamp],
    target: pd.Timestamp,
) -> pd.Timestamp | None:
    result = None

    for timestamp in timestamps:
        if timestamp > target:
            break
        result = timestamp

    return result


def generate_walk_forward_windows(
    timestamps: Sequence[datetime | pd.Timestamp],
    config: WalkForwardConfig,
    *,
    config_hash: str,
) -> tuple[WalkForwardWindow, ...]:
    """Generate deterministic chronological walk-forward windows.

    The supplied timestamps are the union of the available market timestamps.

    Important semantics:

    - ``warmup`` is historical context used only to initialize indicators.
    - ``train`` and ``validation`` are research context and are NOT traded.
    - only ``test`` is traded/scored OOS.
    - expanding windows keep the training start fixed and extend training
      forward by ``step_days``.
    - rolling windows move the training block forward by ``step_days``.
    - test windows are required to be non-overlapping.
    - dates are calendar-day targets snapped to actual supplied timestamps.
    """

    if not isinstance(config, WalkForwardConfig):
        raise TypeError("config must be WalkForwardConfig.")

    if not config_hash:
        raise ValueError("config_hash must not be empty.")

    ordered = _unique_sorted_timestamps(timestamps)

    first_timestamp = ordered[0]
    last_timestamp = ordered[-1]

    # The first actual training observation starts after enough historical
    # context has been reserved for indicator warmup.
    base_train_start_target = (
        first_timestamp + timedelta(days=config.warmup_days)
    )

    base_train_start = _first_at_or_after(
        ordered,
        base_train_start_target,
    )

    if base_train_start is None:
        raise ValueError(
            "Insufficient timestamps to establish the configured warmup period."
        )

    windows: list[WalkForwardWindow] = []
    iteration = 0

    while True:
        step_offset = timedelta(days=iteration * config.step_days)

        if config.expanding:
            train_start = base_train_start
            train_end_target = (
                base_train_start
                + timedelta(days=config.train_days)
                + step_offset
            )
            warmup_start = first_timestamp
        else:
            train_start_target = (
                base_train_start + step_offset
            )

            train_start = _first_at_or_after(
                ordered,
                train_start_target,
            )

            if train_start is None:
                break

            train_end_target = (
                train_start + timedelta(days=config.train_days)
            )

            warmup_start_target = (
                train_start - timedelta(days=config.warmup_days)
            )

            warmup_start = _first_at_or_after(
                ordered,
                warmup_start_target,
            )

            if warmup_start is None or warmup_start >= train_start:
                break

        train_end = _last_at_or_before(
            ordered,
            train_end_target,
        )

        if train_end is None or train_end <= train_start:
            break

        validation_start_target = (
            train_end_target
        )

        validation_start = _first_at_or_after(
            ordered,
            validation_start_target,
        )

        validation_end_target = (
            validation_start_target
            + timedelta(days=config.validation_days)
        )

        validation_end = _last_at_or_before(
            ordered,
            validation_end_target,
        )

        if (
            validation_start is None
            or validation_end is None
            or validation_end <= validation_start
        ):
            break

        test_start_target = (
            validation_end_target
            + timedelta(days=config.embargo_days)
        )

        test_start = _first_at_or_after(
            ordered,
            test_start_target,
        )

        test_end_target = (
            test_start_target
            + timedelta(days=config.test_days)
        )

        test_end = _last_at_or_before(
            ordered,
            test_end_target,
        )

        if (
            test_start is None
            or test_end is None
            or test_end <= test_start
        ):
            break

        embargo_start: pd.Timestamp | None = None
        embargo_end: pd.Timestamp | None = None

        if config.embargo_days > 0:
            embargo_start = validation_end
            embargo_end = test_start

            if embargo_end <= embargo_start:
                break

        window = WalkForwardWindow(
            window_id=len(windows),
            warmup_start=warmup_start.to_pydatetime(),
            train_start=train_start.to_pydatetime(),
            train_end=train_end.to_pydatetime(),
            validation_start=validation_start.to_pydatetime(),
            validation_end=validation_end.to_pydatetime(),
            test_start=test_start.to_pydatetime(),
            test_end=test_end.to_pydatetime(),
            embargo_start=(
                embargo_start.to_pydatetime()
                if embargo_start is not None
                else None
            ),
            embargo_end=(
                embargo_end.to_pydatetime()
                if embargo_end is not None
                else None
            ),
            config_hash=config_hash,
        )

        windows.append(window)

        iteration += 1

        next_cursor = (
            base_train_start
            + timedelta(days=iteration * config.step_days)
        )

        if next_cursor > last_timestamp:
            break

    if len(windows) < config.min_windows:
        raise ValueError(
            f"Only {len(windows)} walk-forward windows could be generated; "
            f"minimum required is {config.min_windows}."
        )

    _validate_window_sequence(windows)

    return tuple(windows)


def _validate_window_sequence(
    windows: Sequence[WalkForwardWindow],
) -> None:
    """Validate global chronological integrity and OOS non-overlap."""

    previous_test_end: datetime | None = None

    for window in windows:
        if previous_test_end is not None:
            if window.test_start <= previous_test_end:
                raise ValueError(
                    "Walk-forward test windows must not overlap."
                )

        previous_test_end = window.test_end