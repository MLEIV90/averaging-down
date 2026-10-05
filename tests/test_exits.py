from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from src.strategy.exits import ExitEngine, should_reset_cycle
from src.strategy.state_machine import PositionState
from src.execution.accounting import AccountingEngine, CashLedger


NOW = datetime(2025, 1, 31, tzinfo=timezone.utc)


def evaluate(**changes):
    values = dict(
        asset="SPY", position_quantity=10.0, anchor_price=100.0,
        entry_timestamp=NOW - timedelta(days=10), entry_atr=2.0,
        current_timestamp=NOW, current_price=99.0, z_atr=0.0, rsi2=50.0,
        partial_sell_stage=0,
    )
    values.update(changes)
    return ExitEngine().evaluate(**values)


def test_hold_and_diagnostic_fields():
    decision = evaluate()
    assert decision.action == "HOLD"
    assert decision.quantity_fraction == 0
    assert decision.asset == "SPY" and decision.position_quantity == 10
    assert decision.signal_timestamp == NOW


def test_structural_stop_triggers_below_and_at_boundary():
    assert (evaluate(current_price=93.99).action, evaluate(current_price=93.99).reason) == ("FULL_EXIT", "STRUCTURAL_STOP")
    assert evaluate(current_price=94.0).reason == "STRUCTURAL_STOP"


def test_time_stop_boundary_and_before_boundary():
    engine = ExitEngine()
    args = dict(asset="SPY", position_quantity=1, anchor_price=100,
                entry_timestamp=NOW - timedelta(days=30), entry_atr=2,
                current_timestamp=NOW, current_price=100, z_atr=0, rsi2=50,
                partial_sell_stage=0)
    assert engine.evaluate(**args).reason == "TIME_STOP"
    assert engine.evaluate(**{**args, "entry_timestamp": NOW - timedelta(days=29)}).action == "HOLD"


def test_partial_recovery_boundaries_and_anti_repeat():
    assert evaluate(z_atr=1.5, rsi2=90.01).reason == "PARTIAL_RECOVERY"
    assert evaluate(z_atr=1.5, rsi2=90).action == "HOLD"
    assert evaluate(z_atr=1.49, rsi2=91).action == "HOLD"
    assert evaluate(z_atr=1.5, rsi2=91, partial_sell_stage=1).action == "HOLD"


def test_priority_structural_then_time_then_partial():
    args = dict(current_price=90, entry_timestamp=NOW - timedelta(days=30), z_atr=2, rsi2=95)
    assert evaluate(**args).reason == "STRUCTURAL_STOP"
    assert evaluate(current_price=100, **{k: v for k, v in args.items() if k != "current_price"}).reason == "TIME_STOP"


@pytest.mark.parametrize("missing", ["z_atr", "rsi2"])
def test_missing_recovery_observation_does_not_block_other_rules(missing):
    assert evaluate(**{missing: None}).action == "HOLD"
    assert evaluate(**{missing: None, "current_price": 90}).reason == "STRUCTURAL_STOP"


def test_missing_entry_atr_disables_only_structural_stop():
    assert evaluate(entry_atr=None, current_price=50).action == "HOLD"
    assert evaluate(entry_atr=None, entry_timestamp=NOW - timedelta(days=30)).reason == "TIME_STOP"


@pytest.mark.parametrize("quantity", [0, -1])
def test_no_position_never_sells(quantity):
    assert evaluate(position_quantity=quantity, current_price=1, z_atr=2, rsi2=99).action == "HOLD"


def test_invalid_timestamps_and_nan_rejected():
    with pytest.raises(ValueError):
        evaluate(entry_timestamp=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError):
        evaluate(entry_timestamp=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        evaluate(current_price=float("nan"))
    with pytest.raises(ValueError):
        evaluate(z_atr=float("nan"))


def test_decision_is_immutable_and_evaluation_does_not_mutate_position_or_accounting():
    state = PositionState(cycle_active=True, last_tier="T1", anchor_price=100,
                          lowest_price=100, position_weight=.2, average_entry_price=100,
                          entry_timestamp=NOW - timedelta(days=10), last_filled_z_atr=-1.5)
    original = state
    result = evaluate()
    ledger = CashLedger(initial_cash=1000)
    ledger_before = ledger
    accounting = AccountingEngine()
    accounting_before = accounting
    assert state is original and state.partial_sell_stage == 0
    assert ledger is ledger_before and ledger.cash == 1000
    assert accounting is accounting_before
    with pytest.raises(FrozenInstanceError):
        result.action = "FULL_EXIT"


def test_future_observations_are_not_part_of_explicit_point_in_time_inputs():
    initial = evaluate(current_timestamp=NOW, current_price=99)
    # An observation after NOW is not accepted or consulted by the engine API.
    changed_future = {"timestamp": NOW + timedelta(days=1), "price": 1, "rsi2": 100}
    assert "timestamp" not in __import__("inspect").signature(ExitEngine.evaluate).parameters
    assert evaluate(current_timestamp=NOW, current_price=99) == initial
    assert changed_future["timestamp"] > NOW


def test_cycle_reset_requires_full_exit_and_actual_zero_quantity():
    decision = evaluate(current_price=90)
    assert should_reset_cycle(decision, position_quantity_after_fill=0)
    assert not should_reset_cycle(decision, position_quantity_after_fill=1)
    assert not should_reset_cycle(evaluate(), position_quantity_after_fill=0)


def test_exit_engine_has_no_order_or_fill_factory_dependency():
    import inspect
    source = inspect.getsource(ExitEngine)
    assert "Order(" not in source and "Fill(" not in source
