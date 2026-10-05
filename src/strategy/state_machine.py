"""Validated position state that represents completed fills only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math


@dataclass(frozen=True)
class PositionState:
    cycle_active: bool = False
    last_tier: str = "NONE"
    anchor_price: float | None = None
    lowest_price: float | None = None
    position_weight: float = 0.0
    average_entry_price: float | None = None
    entry_timestamp: datetime | None = None
    last_filled_z_atr: float | None = None
    partial_sell_stage: int = 0

    def __post_init__(self) -> None:
        self.validate()

    @property
    def tier_state(self) -> str:
        return "FLAT" if not self.cycle_active else f"{self.last_tier}_ACTIVE"

    def validate(self) -> None:
        """Raise rather than silently repairing an inconsistent position."""
        if type(self.cycle_active) is not bool:
            raise ValueError("cycle_active must be a boolean.")
        if not isinstance(self.last_tier, str) or self.last_tier not in {"NONE", "T1", "T2", "T3"}:
            raise ValueError("last_tier must be NONE, T1, T2, or T3.")
        if isinstance(self.position_weight, bool) or not isinstance(self.position_weight, (int, float)) \
                or not math.isfinite(self.position_weight) or not 0 <= self.position_weight <= 1:
            raise ValueError("position_weight must be finite and between 0 and 1.")
        if type(self.partial_sell_stage) is not int or self.partial_sell_stage < 0:
            raise ValueError("partial_sell_stage must be a non-negative integer.")

        fields = (
            self.anchor_price, self.lowest_price, self.average_entry_price,
            self.entry_timestamp, self.last_filled_z_atr,
        )
        if not self.cycle_active:
            if self.last_tier != "NONE" or self.position_weight != 0 or any(value is not None for value in fields):
                raise ValueError("A flat position must contain only initial state values.")
            return

        if self.last_tier == "NONE" or self.position_weight <= 0:
            raise ValueError("An active cycle requires a filled tier and positive position weight.")
        for name, value in (
            ("anchor_price", self.anchor_price),
            ("lowest_price", self.lowest_price),
            ("average_entry_price", self.average_entry_price),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value <= 0:
                raise ValueError(f"An active cycle requires a finite positive {name}.")
        if self.lowest_price > self.anchor_price:
            raise ValueError("lowest_price cannot exceed the first-fill anchor_price.")
        if self.lowest_price > self.average_entry_price:
            raise ValueError("lowest_price cannot exceed average_entry_price.")
        if isinstance(self.last_filled_z_atr, bool) or not isinstance(self.last_filled_z_atr, (int, float)) \
                or not math.isfinite(self.last_filled_z_atr):
            raise ValueError("An active cycle requires a finite last_filled_z_atr.")
        if not isinstance(self.entry_timestamp, datetime) or self.entry_timestamp.tzinfo is None \
                or self.entry_timestamp.utcoffset() is None:
            raise ValueError("An active cycle requires a timezone-aware entry_timestamp.")


class StateMachine:
    """Small per-asset store for the latest immutable, fill-derived states."""

    def __init__(self):
        self.states: dict[str, PositionState] = {}

    def get(self, asset: str) -> PositionState:
        if asset not in self.states:
            self.states[asset] = PositionState()
        return self.states[asset]

    def set(self, asset: str, state: PositionState) -> None:
        if not isinstance(state, PositionState):
            raise TypeError("StateMachine only stores PositionState values.")
        state.validate()
        self.states[asset] = state
