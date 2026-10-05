from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from src.strategy.state_machine import PositionState, StateMachine


def active_state(**changes):
    values = dict(
        cycle_active=True,
        last_tier="T1",
        anchor_price=100.0,
        lowest_price=100.0,
        position_weight=0.20,
        average_entry_price=100.0,
        entry_timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        last_filled_z_atr=-1.6,
        partial_sell_stage=0,
    )
    values.update(changes)
    return PositionState(**values)


def test_initial_position_state_is_flat_and_has_specified_defaults():
    state = PositionState()
    assert state.tier_state == "FLAT"
    assert state.cycle_active is False
    assert state.last_tier == "NONE"
    assert state.anchor_price is None
    assert state.lowest_price is None
    assert state.position_weight == 0.0
    assert state.average_entry_price is None
    assert state.entry_timestamp is None
    assert state.last_filled_z_atr is None
    assert state.partial_sell_stage == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"last_tier": "T2"},
        {"cycle_active": True, "last_tier": "T1", "position_weight": 0.20},
        {"cycle_active": True, "last_tier": "T1", "position_weight": 0.20,
         "anchor_price": 100.0, "lowest_price": 100.0, "average_entry_price": 100.0,
         "entry_timestamp": datetime(2024, 1, 2), "last_filled_z_atr": -1.6},
        {"position_weight": 1.1},
    ],
)
def test_impossible_or_unsupported_position_states_fail_explicitly(changes):
    with pytest.raises(ValueError):
        PositionState(**changes)


def test_active_position_state_requires_consistent_filled_fields():
    state = active_state()
    assert state.tier_state == "T1_ACTIVE"
    assert state.cycle_active
    with pytest.raises(FrozenInstanceError):
        state.position_weight = 0.45


def test_partial_sell_stage_records_completed_partial_fill_count():
    assert active_state(partial_sell_stage=1).partial_sell_stage == 1
    with pytest.raises(ValueError):
        active_state(partial_sell_stage=-1)


def test_state_machine_stores_only_valid_immutable_position_states():
    store = StateMachine()
    assert store.get("SPY") == PositionState()
    active = active_state()
    store.set("SPY", active)
    assert store.get("SPY") is active
    with pytest.raises(TypeError):
        store.set("GLD", {})
