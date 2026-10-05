from dataclasses import asdict, replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from src.backtest.sequential import BacktestConfig, BacktestEngine
from src.features.config import FeatureConfig
from src.risk.sizing_engine import RiskSizingEngine
from src.strategy.signals import SignalResult


DATES = pd.date_range("2025-01-01", periods=5, tz="UTC")


def bars(opens=None, closes=None, dates=DATES):
    opens = opens or [100.0] * len(dates)
    closes = closes or [100.0] * len(dates)
    return pd.DataFrame({
        "open": opens, "high": [max(o, c) + 1 for o, c in zip(opens, closes)],
        "low": [min(o, c) - 1 for o, c in zip(opens, closes)], "close": closes,
        "volume": [1000.0] * len(dates),
    }, index=dates)


class TinyFeatures:
    config = FeatureConfig(ema_fast=2, ema_medium=3, ema_slow=4, atr_period=2,
                           rsi_fast_period=2, rsi_period=3, realized_vol_period=2,
                           realized_vol_windows=(2,), annualization=252,
                           slope_lookback=1)

    def compute(self, frame):
        out = frame.copy()
        out["atr2"] = 1.0
        out["realized_vol_2"] = 0.15
        out["realized_vol_20"] = 0.15
        out["z_atr"] = -1.5
        out["rsi2"] = 5.0
        if "forced_z" in out:
            out["z_atr"] = out["forced_z"]
        if "forced_rsi" in out:
            out["rsi2"] = out["forced_rsi"]
        out["ema2"] = out["close"] - 1
        return out


class ScriptedSignals:
    def __init__(self, by_asset=None):
        self.by_asset = by_asset or {}

    def classify_series(self, frame, asset):
        specs = self.by_asset.get(asset, {})
        rows = []
        for i, ts in enumerate(frame.index):
            state, z, rsi = specs.get(i, ("NO_SIGNAL", -1.0, 50.0))
            rows.append(asdict(SignalResult(
                timestamp=ts, asset=asset, signal_state=state, trend_regime="BULL",
                stress_regime="NORMAL", z_atr=z, rsi2=rsi, z_atr_extreme=True,
                rsi2_extreme=False, extreme_condition=False, reversal_confirmed=True,
                close_location=0.8, previous_close=100.0, realized_vol_20=0.15,
                regime_eligible=True, stress_blocked=False,
                entry_candidate=state == "ENTRY_CANDIDATE", reason="fixture",
                unavailable_features=(), insufficient_data=False,
            )))
        return pd.DataFrame(rows, index=frame.index)


class OversizedRisk:
    def __init__(self):
        self.engine = RiskSizingEngine()

    def size(self, *args, **kwargs):
        return replace(self.engine.size(*args, **kwargs), final_quantity=10.0)


def engine(**kwargs):
    return BacktestEngine(feature_engine=TinyFeatures(), signal_engine=ScriptedSignals(), **kwargs)


def test_next_open_entry_accounting_state_and_no_same_close_fill():
    signals = ScriptedSignals({"SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)}})
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run({"SPY": bars()})
    assert len(result.orders) == 1
    trade = result.trades[0]
    assert trade.signal_timestamp == DATES[0].to_pydatetime()
    assert trade.fill_timestamp == DATES[1].to_pydatetime()
    assert trade.fill_price == 100
    assert trade.side == "BUY" and trade.quantity > 0
    assert result.position_history[0].quantity == 0
    assert result.position_history[1].quantity == trade.quantity
    assert result.orders[0].order.order_timestamp == trade.signal_timestamp


def test_scale_in_t1_then_t2_updates_only_after_next_bar_fills():
    signals = ScriptedSignals({"SPY": {
        0: ("ENTRY_CANDIDATE", -1.5, 5),
        2: ("WATCH", -2.5, 5),
    }})
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run({"SPY": bars()})
    assert [trade.tier for trade in result.trades] == ["T1", "T2"]
    assert result.trades[0].fill_timestamp == DATES[1].to_pydatetime()
    assert result.trades[1].fill_timestamp == DATES[3].to_pydatetime()
    assert result.position_history[3].state.last_tier == "T2"


def test_stop_exit_fills_at_next_open_after_gap_not_stop_threshold():
    frame = bars(opens=[100, 100, 100, 80, 80], closes=[100, 100, 96, 80, 80])
    signals = ScriptedSignals({"SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)}})
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run({"SPY": frame})
    exit_trade = next(t for t in result.trades if t.side == "SELL")
    assert exit_trade.reason == "STRUCTURAL_STOP"
    assert exit_trade.reference_price == 96
    assert exit_trade.fill_price == 80
    assert result.position_history[3].state.cycle_active is False


def test_partial_exit_advances_stage_after_fill_and_cannot_repeat():
    frame = bars(closes=[100, 101, 102, 103, 104])
    frame["forced_z"] = [-1.5, -1.0, 1.5, 1.5, 1.0]
    frame["forced_rsi"] = [5, 20, 91, 91, 50]
    signals = ScriptedSignals({"SPY": {
        0: ("ENTRY_CANDIDATE", -1.5, 5),
        2: ("WATCH", 1.5, 91),
        3: ("WATCH", 1.5, 91),
    }})
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run({"SPY": frame})
    sells = [t for t in result.trades if t.side == "SELL"]
    assert len(sells) == 1
    assert result.position_history[3].state.partial_sell_stage == 1


def test_zero_costs_and_explicit_costs_reconcile_once():
    signals = ScriptedSignals({"SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)}})
    data = {"SPY": bars()}
    zero = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals,
                          config=BacktestConfig(initial_capital=100_000)).run(data)
    assert zero.total_transaction_costs == 0
    costed = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals,
                            config=BacktestConfig(commission_bps=10, slippage_bps=20,
                                                  initial_capital=100_000)).run(data)
    buy = costed.trades[0]
    assert buy.fill_price == pytest.approx(100.0)  # next bar open; slippage is a separate cost
    assert buy.commission > 0 and buy.slippage_cost > 0
    assert costed.total_transaction_costs == pytest.approx(buy.commission + buy.slippage_cost)
    assert zero.portfolio_curve[-1].equity - costed.portfolio_curve[-1].equity == pytest.approx(
        costed.total_transaction_costs
    )
    assert costed.portfolio_curve[-1].equity < zero.portfolio_curve[-1].equity


def test_empty_and_insufficient_warmup_return_structured_empty_results():
    empty = engine().run({})
    assert not empty.portfolio_curve and not empty.trades
    no_signal = engine().run({"SPY": bars()})
    assert no_signal.portfolio_curve and not no_signal.trades


def test_real_feature_regime_signal_pipeline_handles_insufficient_warmup():
    result = BacktestEngine().run({"SPY": bars(dates=DATES[:3])})
    assert len(result.portfolio_curve) == 3
    assert not result.trades


def test_market_data_validation_precedes_feature_calculation():
    class TrackedFeatures(TinyFeatures):
        called = False

        def compute(self, frame):
            self.called = True
            return super().compute(frame)

    features = TrackedFeatures()
    invalid = bars()
    invalid.iloc[0, invalid.columns.get_loc("high")] = 1
    with pytest.raises(ValueError, match="Invalid OHLCV"):
        BacktestEngine(feature_engine=features, signal_engine=ScriptedSignals()).run({"SPY": invalid})
    assert features.called is False


def test_no_future_bar_keeps_order_pending_without_fabricating_fill():
    short = bars(dates=DATES[:1])
    signals = ScriptedSignals({"SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)}})
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run({"SPY": short})
    assert not result.trades
    assert len(result.pending_orders) == 1
    assert result.position_history[-1].quantity == 0


def test_btc_uses_its_own_next_available_timestamp_and_alias():
    btc_dates = DATES[[0, 2, 4]]
    data = {"BTC-USD": bars(dates=btc_dates)}
    signals = ScriptedSignals({"BTC": {0: ("ENTRY_CANDIDATE", -1.75, 5)}})
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run(data)
    assert result.trades[0].asset == "BTC"
    assert result.trades[0].fill_timestamp == btc_dates[1].to_pydatetime()


def test_portfolio_reduction_becomes_a_reduced_order_and_is_auditable():
    signals = ScriptedSignals({"SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)}})
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals,
                            risk_engine=OversizedRisk()).run({"SPY": bars()})
    assert len(result.trades) == 1
    order = result.orders[0]
    assert order.approved_quantity < order.requested_quantity
    assert "reduced_by_max_asset_weight" in order.reason
    assert order.allocation.binding_constraint == "MAX_ASSET_WEIGHT"
    assert result.trades[0].quantity == order.approved_quantity


def test_spy_btc_gld_coexist_with_limits_applied_deterministically():
    signals = ScriptedSignals({
        "SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)},
        "BTC": {0: ("ENTRY_CANDIDATE", -1.75, 5)},
        "GLD": {0: ("ENTRY_CANDIDATE", -1.5, 5)},
    })
    data = {asset: bars() for asset in ("SPY", "BTC", "GLD")}
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals,
                            risk_engine=OversizedRisk()).run(data)
    by_asset = {p.asset: p for p in result.position_history if p.timestamp == DATES[1].to_pydatetime()}
    assert all(by_asset[asset].quantity > 0 for asset in ("SPY", "BTC", "GLD"))
    assert by_asset["SPY"].quantity * 100 / result.portfolio_curve[1].equity <= 0.35 + 1e-10
    assert by_asset["BTC"].quantity * 100 / result.portfolio_curve[1].equity <= 0.10 + 1e-10
    assert by_asset["GLD"].quantity * 100 / result.portfolio_curve[1].equity <= 0.25 + 1e-10
    assert result.portfolio_curve[1].gross_exposure <= 0.70 + 1e-10


def test_costs_are_reserved_by_portfolio_engine_and_cash_stays_nonnegative():
    signals = ScriptedSignals({
        "SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)},
        "BTC": {0: ("ENTRY_CANDIDATE", -1.75, 5)},
        "GLD": {0: ("ENTRY_CANDIDATE", -1.5, 5)},
    })
    config = BacktestConfig(initial_capital=1100, commission_bps=4000, slippage_bps=4000)
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals,
                            risk_engine=OversizedRisk(), config=config).run(
                                {asset: bars() for asset in ("SPY", "BTC", "GLD")}
                            )
    spy_order = next(order for order in result.orders if order.action == "BUY_T1" and order.order.asset == "SPY")
    assert spy_order.allocation.binding_constraint == "CASH_RESERVE"
    assert all(order.status == "FILLED" for order in result.orders)
    assert result.portfolio_curve[1].cash >= 1100 * 0.30
    assert all(point.cash >= 0 for point in result.portfolio_curve)


def test_open_gap_that_exceeds_cash_rejects_order_without_negative_cash_or_state_fill():
    frame = bars(opens=[100, 1000, 1000, 1000, 1000])
    signals = ScriptedSignals({"SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)}})
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run({"SPY": frame})
    assert result.orders[0].status == "REJECTED"
    assert not result.trades
    assert all(point.cash >= 0 for point in result.portfolio_curve)
    assert not any(point.state.cycle_active for point in result.position_history)


def test_equity_reconciles_to_cash_and_marked_positions_and_exit_realizes_pnl():
    frame = bars(opens=[100, 100, 100, 80, 80], closes=[100, 100, 96, 80, 80])
    signals = ScriptedSignals({"SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)}})
    result = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run({"SPY": frame})
    for point in result.portfolio_curve:
        assert point.equity == pytest.approx(point.cash + point.market_value)
    exit_trade = next(trade for trade in result.trades if trade.side == "SELL")
    assert exit_trade.realized_pnl < 0
    assert result.portfolio_curve[-1].realized_pnl == pytest.approx(exit_trade.realized_pnl)


def test_future_price_changes_do_not_change_earlier_decision_or_trade():
    signals = ScriptedSignals({"SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)}})
    original = bars()
    revised = original.copy()
    revised.iloc[3:, revised.columns.get_loc("close")] = 500
    revised.iloc[3:, revised.columns.get_loc("open")] = 500
    revised.iloc[3:, revised.columns.get_loc("high")] = 501
    revised.iloc[3:, revised.columns.get_loc("low")] = 499
    first = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run({"SPY": original})
    second = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run({"SPY": revised})
    assert first.trades[0] == second.trades[0]
    assert first.position_history[:3] == second.position_history[:3]


def test_same_inputs_produce_identical_results():
    signals = ScriptedSignals({"SPY": {0: ("ENTRY_CANDIDATE", -1.5, 5)}})
    data = {"SPY": bars()}
    one = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run(data)
    two = BacktestEngine(feature_engine=TinyFeatures(), signal_engine=signals).run(data)
    assert one == two
