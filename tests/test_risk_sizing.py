from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.execution.accounting import CashLedger
from src.execution.orders import Fill, Order
from src.risk.sizing_engine import RiskSizingEngine, SizingDecision
from src.strategy.scale_in import ScaleInDecision
from src.strategy.state_machine import PositionState


def decision(action="BUY_T1", asset="SPY", *, target_weight=0.20, incremental_weight=0.20):
    return ScaleInDecision(
        action=action,
        target_tier=action[-2:] if action.startswith("BUY_T") else None,
        incremental_weight=incremental_weight,
        target_weight=target_weight,
        reason="test proposal",
        z_atr=-1.6,
        previous_filled_z_atr=None,
        asset=asset,
        signal_timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )


def size(engine=None, proposal=None, **overrides):
    params = dict(equity=10_000, available_cash=10_000, reference_price=100, atr=2,
                  realized_vol=0.15)
    params.update(overrides)
    return (engine or RiskSizingEngine()).size(proposal or decision(), **params)


def test_allocation_and_risk_formulas_and_default_vf():
    result = size()
    assert result.allocation_quantity == pytest.approx(20)
    assert result.risk_budget == pytest.approx(100)
    assert result.stop_distance == pytest.approx(6)
    assert result.risk_quantity == pytest.approx(100 / 6)
    assert result.volatility_factor == pytest.approx(1)


@pytest.mark.parametrize("realized, expected", [(0.30, 0.5), (0.075, 1.5), (0.15, 1.0)])
def test_volatility_factor_clips_to_configured_bounds(realized, expected):
    assert size(realized_vol=realized).volatility_factor == pytest.approx(expected)


@pytest.mark.parametrize(
    "proposal, overrides, expected",
    [
        (decision(incremental_weight=0.01, target_weight=0.01), {}, "ALLOCATION"),
        (decision(incremental_weight=0.5, target_weight=0.5),
         {"equity": 1_000_000, "available_cash": 1_000_000}, "RISK"),
        (decision(), {"available_cash": 100}, "CASH"),
    ],
)
def test_binding_constraint(proposal, overrides, expected):
    assert size(proposal=proposal, **overrides).binding_constraint == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"equity": 0}, {"equity": -1}, {"equity": float("nan")},
        {"available_cash": -1}, {"available_cash": float("inf")},
        {"reference_price": 0}, {"reference_price": float("nan")},
        {"atr": 0}, {"atr": float("nan")}, {"realized_vol": 0},
        {"realized_vol": float("nan")},
    ],
)
def test_invalid_runtime_inputs_are_rejected(overrides):
    with pytest.raises(ValueError):
        size(**overrides)


@pytest.mark.parametrize("weight", [-0.1, float("nan"), float("inf")])
def test_invalid_decision_weights_are_rejected(weight):
    with pytest.raises(ValueError):
        size(proposal=decision(incremental_weight=weight))


def test_alias_uses_btc_target_volatility():
    engine = RiskSizingEngine()
    btc = size(engine, decision(asset="BTC"), realized_vol=0.35)
    alias = size(engine, decision(asset="BTC-USD"), realized_vol=0.35)
    assert btc == alias
    assert btc.volatility_factor == pytest.approx(1)


def test_disabling_volatility_adjustment_allows_unavailable_realized_vol(tmp_path):
    config = yaml.safe_load(Path("config/risk.yaml").read_text(encoding="utf-8"))
    config["volatility"]["enabled"] = False
    path = tmp_path / "risk.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    result = size(RiskSizingEngine(path), realized_vol=None)
    assert result.realized_vol is None
    assert result.volatility_factor == 1


@pytest.mark.parametrize(
    "section, key, value",
    [
        ("risk", "stop_atr_multiple", 0),
        ("risk", "risk_budget_fraction", -0.01),
        ("volatility", "min_factor", 0),
        ("volatility", "max_factor", float("nan")),
    ],
)
def test_invalid_centralized_configuration_is_rejected(tmp_path, section, key, value):
    config = yaml.safe_load(Path("config/risk.yaml").read_text(encoding="utf-8"))
    config[section][key] = value
    path = tmp_path / "risk.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError):
        RiskSizingEngine(path)


def test_unsupported_sell_decision_returns_explicit_no_sizing():
    result = size(proposal=decision(action="SELL"))
    assert result.action == "NO_SIZING"
    assert result.reason == "unsupported_action"
    assert result.final_quantity == 0


def test_non_positive_result_does_not_round_up_or_create_lot():
    result = size(proposal=decision(incremental_weight=0))
    assert result.action == "NO_SIZING"
    assert result.final_quantity == 0


def test_sizing_decision_is_immutable_and_does_not_mutate_other_layers():
    proposal = decision()
    state = PositionState()
    ledger = CashLedger(10_000)
    state_before, ledger_before = state, ledger
    result = size(proposal=proposal)
    assert isinstance(result, SizingDecision)
    assert state == state_before and ledger == ledger_before and proposal.action == "BUY_T1"
    assert not hasattr(result, "order") and not hasattr(result, "fill")
    with pytest.raises(FrozenInstanceError):
        result.final_quantity = 0
    assert Order is not type(result) and Fill is not type(result)


def test_future_observations_do_not_change_prior_sizing():
    engine = RiskSizingEngine()
    earlier = dict(equity=10_000, available_cash=10_000, reference_price=100, atr=2, realized_vol=0.15)
    observations = [earlier, {"equity": 500, "available_cash": 500, "reference_price": 250,
                              "atr": 20, "realized_vol": 2.0}]
    original = engine.size(decision(), **observations[0])
    observations[1].update(equity=250, reference_price=300, atr=30, realized_vol=3.0)
    assert engine.size(decision(), **observations[0]) == original


def test_binding_constraint_tie_break_is_deterministic():
    # Allocation and cash quantities tie; ALLOCATION has the documented precedence.
    result = size(proposal=decision(incremental_weight=0.10, target_weight=0.10), available_cash=1_000)
    assert result.allocation_quantity == pytest.approx(result.cash_quantity)
    assert result.binding_constraint == "ALLOCATION"
