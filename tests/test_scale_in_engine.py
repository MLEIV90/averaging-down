from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.strategy.scale_in import ScaleInEngine, load_scale_in_config
from src.strategy.signals import SignalResult
from src.strategy.state_machine import PositionState


SIGNAL_TIME = datetime(2024, 1, 2, tzinfo=timezone.utc)


def signal(
    z=-1.6,
    *,
    state="ENTRY_CANDIDATE",
    entry=True,
    trend="BULL",
    stress="NORMAL",
    insufficient=False,
    unavailable=(),
    timestamp=SIGNAL_TIME,
    reversal=True,
):
    return SignalResult(
        timestamp=timestamp,
        asset="SPY",
        signal_state=state,
        trend_regime=trend,
        stress_regime=stress,
        z_atr=z,
        rsi2=8.0,
        z_atr_extreme=True,
        rsi2_extreme=True,
        extreme_condition=True,
        reversal_confirmed=reversal,
        close_location=0.8,
        previous_close=100.0,
        realized_vol_20=0.2,
        regime_eligible=trend == "BULL",
        stress_blocked=stress == "PANIC",
        entry_candidate=entry,
        reason="entry_candidate" if entry else "not_entry_candidate",
        unavailable_features=unavailable,
        insufficient_data=insufficient,
    )


def engine(asset="SPY", config_path="config/strategy.yaml"):
    return ScaleInEngine(asset, config_path=config_path)


def fill(engine_, state, decision, price, day):
    return engine_.apply_fill(
        state,
        decision,
        fill_price=price,
        fill_timestamp=datetime(2024, 1, day, 15, tzinfo=timezone.utc),
    )


def test_default_config_has_exact_provisional_tiers_and_asset_alias():
    tiers = load_scale_in_config()
    assert [tier.cumulative_weight for tier in tiers["SPY"]] == [0.20, 0.45, 0.70]
    assert [tier.z_atr for tier in tiers["BTC"]] == [-1.75, -2.75, -4.0]
    assert [tier.cumulative_weight for tier in tiers["GLD"]] == [0.15, 0.35, 0.55]
    assert engine("BTC-USD").asset == engine("BTC").asset == "BTC"
    with pytest.raises(ValueError, match="No scale-in tier configuration"):
        engine("UNKNOWN")

    btc_signal = replace(signal(z=-1.8), asset="BTC-USD")
    btc_decision = engine("BTC").evaluate(btc_signal, PositionState())
    alias_decision = engine("BTC-USD").evaluate(btc_signal, PositionState())
    assert btc_decision == alias_decision
    assert btc_decision.incremental_weight == pytest.approx(0.10)


def test_t1_proposal_requires_entry_candidate_and_does_not_mutate_position():
    scale = engine()
    state = PositionState()
    decision = scale.evaluate(signal(z=-1.6), state)
    assert decision.action == "BUY_T1"
    assert decision.target_tier == "T1"
    assert decision.incremental_weight == pytest.approx(0.20)
    assert decision.target_weight == pytest.approx(0.20)
    assert decision.signal_timestamp == SIGNAL_TIME
    assert decision.reason == "tier_1_entry"
    assert state == PositionState()

    not_entry = scale.evaluate(signal(z=-1.8, state="WATCH", entry=False), state)
    assert not_entry.action == "NO_ACTION"
    assert not_entry.reason == "entry_candidate_required"
    above_t1 = scale.evaluate(signal(z=-1.4), state)
    assert above_t1.action == "NO_ACTION"
    assert above_t1.reason == "tier_1_threshold_not_met"


def test_fill_uses_actual_price_and_fill_timestamp_not_signal_timestamp():
    scale = engine()
    state = PositionState()
    decision = scale.evaluate(signal(z=-1.6), state)
    fill_timestamp = datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc)
    filled = scale.apply_fill(state, decision, fill_price=98.0, fill_timestamp=fill_timestamp)
    assert filled.anchor_price == 98.0
    assert filled.lowest_price == 98.0
    assert filled.average_entry_price == 98.0
    assert filled.entry_timestamp == fill_timestamp
    assert filled.entry_timestamp != decision.signal_timestamp
    assert filled.position_weight == pytest.approx(0.20)
    assert filled.last_filled_z_atr == pytest.approx(-1.6)
    assert filled.last_tier == "T1"
    assert filled.partial_sell_stage == 0


def test_t1_cannot_repeat_and_each_fill_advances_at_most_one_tier():
    scale = engine()
    flat = PositionState()
    deep_signal = signal(z=-4.0)
    t1 = scale.evaluate(deep_signal, flat)
    assert t1.action == "BUY_T1"
    t1_state = fill(scale, flat, t1, 100.0, 2)
    assert scale.evaluate(deep_signal, t1_state).action == "NO_ACTION"
    assert scale.evaluate(deep_signal, t1_state).reason == "z_atr_not_deeper_than_last_fill"


def test_t2_requires_deeper_z_atr_and_not_a_new_reversal():
    scale = engine()
    flat = PositionState()
    t1 = scale.evaluate(signal(z=-1.6), flat)
    state_t1 = fill(scale, flat, t1, 100.0, 2)

    t2_signal = signal(z=-2.3, state="WATCH", entry=False, reversal=False)
    t2 = scale.evaluate(t2_signal, state_t1)
    assert t2.action == "BUY_T2"
    assert t2.incremental_weight == pytest.approx(0.25)
    assert t2.target_weight == pytest.approx(0.45)
    assert t2.previous_filled_z_atr == pytest.approx(-1.6)

    not_deep_enough = scale.evaluate(signal(z=-2.2, state="WATCH", entry=False), state_t1)
    assert not_deep_enough.action == "NO_ACTION"
    assert not_deep_enough.reason == "tier_2_threshold_not_met"

    state_with_deep_t1 = PositionState(
        cycle_active=True, last_tier="T1", anchor_price=100, lowest_price=100,
        position_weight=0.20, average_entry_price=100,
        entry_timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc), last_filled_z_atr=-2.4,
    )
    recovering = scale.evaluate(signal(z=-2.3, state="WATCH", entry=False), state_with_deep_t1)
    assert recovering.action == "NO_ACTION"
    assert recovering.reason == "z_atr_not_deeper_than_last_fill"


def test_t3_uses_incremental_weight_and_preserves_anchor_and_entry_time():
    scale = engine()
    flat = PositionState()
    t1 = scale.evaluate(signal(z=-1.6), flat)
    after_t1 = fill(scale, flat, t1, 100.0, 2)
    t2 = scale.evaluate(signal(z=-2.3, state="WATCH", entry=False), after_t1)
    after_t2 = fill(scale, after_t1, t2, 90.0, 3)
    t3 = scale.evaluate(signal(z=-3.1, state="WATCH", entry=False), after_t2)
    assert t3.action == "BUY_T3"
    assert t3.incremental_weight == pytest.approx(0.25)
    assert t3.target_weight == pytest.approx(0.70)
    after_t3 = fill(scale, after_t2, t3, 80.0, 4)
    assert after_t3.last_tier == "T3"
    assert after_t3.anchor_price == 100.0
    assert after_t3.lowest_price == 80.0
    assert after_t3.entry_timestamp == after_t1.entry_timestamp
    assert after_t3.average_entry_price == pytest.approx((0.20 * 100 + 0.25 * 90 + 0.25 * 80) / 0.70)
    assert scale.evaluate(signal(z=-5, state="WATCH", entry=False), after_t3).reason == "tier_3_already_active"


@pytest.mark.parametrize("stress", ["PANIC", "UNKNOWN"])
def test_panic_or_unknown_stress_blocks_new_buy_in_any_position_tier(stress):
    scale = engine()
    flat = PositionState()
    no_entry = scale.evaluate(signal(z=-1.6, stress=stress), flat)
    assert no_entry.action == "NO_ACTION"
    assert no_entry.reason == ("panic_blocked" if stress == "PANIC" else "stress_unknown")

    t1 = scale.evaluate(signal(z=-1.6), flat)
    state_t1 = fill(scale, flat, t1, 100, 2)
    t2_panic = scale.evaluate(signal(z=-2.3, stress=stress, state="WATCH", entry=False), state_t1)
    assert t2_panic.action == "NO_ACTION"

    state_t2 = fill(scale, state_t1, scale.evaluate(signal(z=-2.3, state="WATCH", entry=False), state_t1), 90, 3)
    t3_panic = scale.evaluate(signal(z=-3.1, stress=stress, state="WATCH", entry=False), state_t2)
    assert t3_panic.action == "NO_ACTION"


@pytest.mark.parametrize("trend", ["NEUTRAL", "BEAR", "UNKNOWN"])
def test_non_bull_or_unknown_trend_does_not_create_new_purchase(trend):
    decision = engine().evaluate(signal(trend=trend), PositionState())
    assert decision.action == "NO_ACTION"
    assert decision.reason == ("trend_unknown" if trend == "UNKNOWN" else "trend_regime_not_eligible")


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"state": "UNKNOWN", "entry": False}, "signal_unknown"),
        ({"insufficient": True}, "signal_unknown"),
        ({"z": None}, "z_atr_unavailable"),
    ],
)
def test_unknown_or_unavailable_signal_data_never_buys(overrides, reason):
    decision = engine().evaluate(signal(**overrides), PositionState())
    assert decision.action == "NO_ACTION"
    assert decision.reason == reason


@pytest.mark.parametrize(
    "price, timestamp",
    [
        (0, datetime(2024, 1, 2, tzinfo=timezone.utc)),
        (float("nan"), datetime(2024, 1, 2, tzinfo=timezone.utc)),
        (100, datetime(2024, 1, 2)),
    ],
)
def test_apply_fill_rejects_invalid_prices_and_naive_timestamps(price, timestamp):
    scale = engine()
    state = PositionState()
    decision = scale.evaluate(signal(), state)
    with pytest.raises(ValueError):
        scale.apply_fill(state, decision, price, timestamp)


def test_apply_fill_rejects_wrong_order_duplicate_tier_and_stale_decision():
    scale = engine()
    flat = PositionState()
    t1 = scale.evaluate(signal(), flat)
    filled_t1 = fill(scale, flat, t1, 100, 2)
    t2 = scale.evaluate(signal(z=-2.3, state="WATCH", entry=False), filled_t1)
    with pytest.raises(ValueError, match="cannot be applied from FLAT"):
        scale.apply_fill(flat, t2, 90, SIGNAL_TIME)
    state_t1 = fill(scale, flat, t1, 100, 2)
    other_t1_state = PositionState(
        cycle_active=True, last_tier="T1", anchor_price=100, lowest_price=100,
        position_weight=0.20, average_entry_price=100,
        entry_timestamp=state_t1.entry_timestamp, last_filled_z_atr=-1.7,
    )
    with pytest.raises(ValueError, match="different filled position state"):
        scale.apply_fill(other_t1_state, t2, 90, SIGNAL_TIME)
    bad_target = type(t1)(**{**t1.__dict__, "target_weight": 0.45})
    with pytest.raises(ValueError, match="target weight"):
        scale.apply_fill(flat, bad_target, 100, SIGNAL_TIME)


def test_invalid_state_weight_is_not_silently_corrected():
    scale = engine()
    inconsistent = PositionState(
        cycle_active=True, last_tier="T1", anchor_price=100, lowest_price=100,
        position_weight=0.45, average_entry_price=100,
        entry_timestamp=SIGNAL_TIME, last_filled_z_atr=-1.6,
    )
    with pytest.raises(ValueError, match="does not match"):
        scale.evaluate(signal(z=-2.3, state="WATCH", entry=False), inconsistent)


def test_explicit_reset_returns_every_field_to_flat_defaults():
    scale = engine()
    flat = PositionState()
    decision = scale.evaluate(signal(), flat)
    active = fill(scale, flat, decision, 100, 2)
    assert scale.reset_cycle(active) == PositionState()


def test_future_signal_changes_do_not_change_prior_transition_path():
    scale = engine()
    history = [
        signal(z=-1.6, timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc)),
        signal(z=-2.3, state="WATCH", entry=False, timestamp=datetime(2024, 1, 3, tzinfo=timezone.utc)),
        signal(z=-3.1, state="WATCH", entry=False, timestamp=datetime(2024, 1, 4, tzinfo=timezone.utc)),
    ]
    changed_future = list(history)
    changed_future[-1] = signal(z=12, trend="BEAR", stress="PANIC", state="NO_SIGNAL", entry=False,
                                timestamp=history[-1].timestamp)

    def walk(signals):
        state = PositionState()
        decisions = []
        states = []
        for i, item in enumerate(signals):
            decision = scale.evaluate(item, state)
            decisions.append(decision)
            if decision.action.startswith("BUY_"):
                state = fill(scale, state, decision, 100 - i * 10, i + 2)
            states.append(state)
        return decisions, states

    original_decisions, original_states = walk(history)
    changed_decisions, changed_states = walk(changed_future)
    assert original_decisions[:2] == changed_decisions[:2]
    assert original_states[:2] == changed_states[:2]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["strategy"]["scale_in"]["SPY"]["tiers"].append(
            deepcopy(raw["strategy"]["scale_in"]["SPY"]["tiers"][0])
        ),
        lambda raw: raw["strategy"]["scale_in"]["SPY"]["tiers"].pop(),
        lambda raw: raw["strategy"]["scale_in"]["SPY"]["tiers"][1].update(z_atr=-1.0),
        lambda raw: raw["strategy"]["scale_in"]["SPY"]["tiers"][1].update(cumulative_weight=0.20),
        lambda raw: raw["strategy"]["scale_in"]["SPY"]["tiers"][2].update(cumulative_weight=1.1),
        lambda raw: raw["strategy"]["scale_in"]["SPY"]["tiers"][0].update(cumulative_weight=0),
        lambda raw: raw["strategy"]["scale_in"].update(ABC=deepcopy(raw["strategy"]["scale_in"]["SPY"])),
        lambda raw: raw["strategy"]["scale_in"]["SPY"]["tiers"][0].update(z_atr="-1.5"),
    ],
)
def test_strategy_configuration_rejects_ambiguous_or_invalid_tiers(tmp_path, mutate):
    raw = yaml.safe_load(Path("config/strategy.yaml").read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "strategy.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_scale_in_config(path)
