from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from src.risk.sizing_engine import SizingDecision
from src.portfolio.engine import (
    AllocationProposal, PortfolioEngine, PortfolioSnapshot, PortfolioHolding,
)


NOW = datetime(2025, 1, 2, tzinfo=timezone.utc)


def sizing(asset, quantity, price=100.0):
    return SizingDecision(
        asset=asset, action="BUY_T1" if quantity else "NO_SIZING", target_weight=0.2,
        incremental_weight=0.2, reference_price=price, atr=1, risk_budget=1,
        stop_distance=3, realized_vol=0.2, volatility_factor=1, allocation_quantity=quantity,
        risk_quantity=quantity, vol_adjusted_risk_budget=1, vol_adjusted_risk_quantity=quantity,
        cash_quantity=quantity, final_quantity=quantity, binding_constraint="ALLOCATION",
        reason="sized" if quantity else "non_positive_quantity",
    )


def proposal(asset, quantity, price=100.0, timestamp=NOW):
    return AllocationProposal(sizing(asset, quantity, price), timestamp)


def snapshot(equity=1000, cash=1000, holdings=()):
    return PortfolioSnapshot(NOW, equity, cash, holdings)


def evaluate(state, proposals, prices, config_path=None):
    engine = PortfolioEngine(config_path) if config_path else PortfolioEngine()
    return engine.evaluate(state, proposals, prices)


def test_unconstrained_proposal_is_accepted():
    result = evaluate(snapshot(), [proposal("SPY", 1)], {"SPY": 100})
    decision = result.decisions[0]
    assert decision.approved_quantity == 1
    assert decision.binding_constraint == "NONE"
    assert decision.resulting_exposure == pytest.approx(0.1)


def test_gross_exposure_cap_limits_increment():
    # Config uses a 70% provisional gross cap; 60% is already held.
    import yaml
    from pathlib import Path
    raw = yaml.safe_load(Path("config/portfolio.yaml").read_text(encoding="utf-8"))
    raw["portfolio"]["allocation_constraints"]["minimum_cash_reserve"] = 0.10
    config_path = Path(".pytest-tmp/gross-portfolio.yaml")
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    state = snapshot(equity=1000, cash=400, holdings={"SPY": 6})
    result = evaluate(state, [proposal("GLD", 2)], {"SPY": 100, "GLD": 100}, config_path)
    decision = result.decisions[0]
    assert decision.approved_quantity == pytest.approx(1)
    assert decision.binding_constraint == "MAX_GROSS_EXPOSURE"
    assert result.gross_exposure_after == pytest.approx(0.7)


def test_cash_reserve_limits_increment_when_tighter_than_gross_cap(tmp_path):
    import yaml
    raw = yaml.safe_load(open("config/portfolio.yaml", encoding="utf-8"))
    raw["portfolio"]["allocation_constraints"]["max_gross_exposure"] = 0.9
    raw["portfolio"]["allocation_constraints"]["minimum_cash_reserve"] = 0.4
    path = tmp_path / "portfolio.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    state = snapshot(equity=1000, cash=500, holdings={"SPY": 5})
    decision = evaluate(state, [proposal("GLD", 2)], {"SPY": 100, "GLD": 100}, path).decisions[0]
    assert decision.approved_quantity == pytest.approx(1)
    assert decision.binding_constraint == "CASH_RESERVE"


def test_per_asset_concentration_limit():
    state = snapshot(equity=1000, cash=700, holdings={"SPY": 3})
    decision = evaluate(state, [proposal("SPY", 2)], {"SPY": 100}).decisions[0]
    assert decision.current_exposure == pytest.approx(0.3)
    assert decision.approved_quantity == pytest.approx(0.5)
    assert decision.resulting_exposure == pytest.approx(0.35)
    assert decision.binding_constraint == "MAX_ASSET_WEIGHT"


def test_existing_exposure_and_proposals_are_both_counted():
    state = snapshot(equity=1000, cash=600, holdings={"SPY": 2, "GLD": 2})
    result = evaluate(state, [proposal("SPY", 1), proposal("GLD", 1)], {"SPY": 100, "GLD": 100})
    assert result.gross_exposure_after == pytest.approx(0.55)
    assert {d.asset: d.approved_quantity for d in result.decisions} == {"SPY": 1, "GLD": .5}


def test_competing_proposals_follow_configured_deterministic_asset_order(tmp_path):
    import yaml
    raw = yaml.safe_load(open("config/portfolio.yaml", encoding="utf-8"))
    raw["portfolio"]["allocation_constraints"]["max_gross_exposure"] = 0.5
    raw["portfolio"]["allocation_constraints"]["minimum_cash_reserve"] = 0.0
    raw["portfolio"]["allocation_constraints"]["max_asset_weight"] = {"SPY": .5, "BTC": .5, "GLD": .5}
    path = tmp_path / "portfolio.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    state = snapshot()
    prices = {"SPY": 100, "BTC": 100, "GLD": 100}
    first = evaluate(state, [proposal("SPY", 2), proposal("BTC", 2), proposal("GLD", 2)], prices, path)
    second = evaluate(state, [proposal("GLD", 2), proposal("SPY", 2), proposal("BTC", 2)], dict(reversed(list(prices.items()))), path)
    assert first == second
    assert [(d.asset, d.approved_quantity) for d in first.decisions] == [
        ("BTC", 2), ("GLD", 2), ("SPY", 1)
    ]


def test_zero_proposal_and_zero_cash():
    assert evaluate(snapshot(), [proposal("SPY", 0)], {"SPY": 100}).decisions[0].approved_quantity == 0
    zero_risk_output = AllocationProposal(sizing("SPY", 0, price=0), NOW)
    assert evaluate(snapshot(), [zero_risk_output], {"SPY": 100}).decisions[0].requested_notional == 0
    state = snapshot(equity=1000, cash=300, holdings={"SPY": 7})
    decision = evaluate(state, [proposal("GLD", 1)], {"SPY": 100, "GLD": 100}).decisions[0]
    assert decision.approved_quantity == 0
    assert decision.binding_constraint == "MULTIPLE_CONSTRAINTS"


def test_zero_equity_allows_only_empty_state_and_approves_zero():
    result = evaluate(snapshot(equity=0, cash=0), [proposal("SPY", 1)], {"SPY": 100})
    assert result.decisions[0].approved_quantity == 0
    assert result.decisions[0].binding_constraint == "ZERO_EQUITY"


@pytest.mark.parametrize("equity,cash,holdings", [(-1, 0, {}), (100, -1, {})])
def test_invalid_or_inconsistent_state_rejected(equity, cash, holdings):
    with pytest.raises(ValueError):
        snapshot(equity, cash, holdings)


def test_holdings_must_reconcile_with_equity_at_supplied_prices():
    state = snapshot(100, 20, {"SPY": 1})
    with pytest.raises(ValueError):
        evaluate(state, [], {"SPY": 100})


@pytest.mark.parametrize("quantity", [-1, float("nan"), float("inf")])
def test_invalid_proposal_quantity_rejected(quantity):
    with pytest.raises(ValueError):
        proposal("SPY", quantity)


@pytest.mark.parametrize("price", [-1, 0, float("nan"), float("inf")])
def test_invalid_current_prices_rejected(price):
    with pytest.raises(ValueError):
        evaluate(snapshot(), [proposal("SPY", 1)], {"SPY": price})


def test_aliases_are_normalized_and_duplicate_aliases_rejected():
    result = evaluate(snapshot(), [proposal("BTC-USD", 1)], {"BTC": 100})
    assert result.decisions[0].asset == "BTC"
    with pytest.raises(ValueError):
        evaluate(snapshot(), [proposal("BTC", 1), proposal("BTC-USD", 1)], {"BTC": 100})


def test_decisions_are_immutable_and_inputs_and_risk_proposals_unchanged():
    risk_proposal = sizing("SPY", 1)
    proposal_input = AllocationProposal(risk_proposal, NOW)
    holdings = {"SPY": 2}
    state = snapshot(equity=1000, cash=800, holdings=holdings)
    before = (risk_proposal, proposal_input, state, holdings.copy())
    decision = evaluate(state, [proposal_input], {"SPY": 100}).decisions[0]
    assert (risk_proposal, proposal_input, state, holdings) == before
    with pytest.raises(FrozenInstanceError):
        decision.approved_quantity = 99


def test_exact_boundaries_do_not_reduce_proposal():
    state = snapshot(equity=1000, cash=700, holdings={"SPY": 3})
    decision = evaluate(state, [proposal("SPY", 0.5)], {"SPY": 100}).decisions[0]
    assert decision.approved_quantity == pytest.approx(0.5)
    assert decision.binding_constraint == "NONE"


def test_proposal_timestamp_must_not_be_after_snapshot():
    with pytest.raises(ValueError):
        evaluate(snapshot(), [proposal("SPY", 1, timestamp=NOW.replace(year=2026))], {"SPY": 100})
