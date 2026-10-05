from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.analytics import AnalyticsConfig, run_analytics
from src.backtest.sequential import (AssetSummary, BacktestConfig, BacktestResult,
                                     PortfolioPoint, PositionPoint, TradeRecord)
from src.execution.orders import Fill
from src.strategy.state_machine import PositionState


BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def result(equities=(100.0,), *, trades=(), fills=(), positions=(), assets=(), capital=100.0):
    points = tuple(PortfolioPoint(BASE + timedelta(days=i), 40.0, e - 40.0, e,
                                  (e - 40.0) / e if e else 0.0,
                                  (e - 40.0) / e if e else 0.0, 0.0, 0.0, 0.0)
                   for i, e in enumerate(equities))
    return BacktestResult(points, tuple(trades), tuple(SimpleNamespace(fill=f) for f in fills), (),
                          tuple(positions), tuple(assets), sum(f.commission + f.slippage_cost for f in fills),
                          BacktestConfig(initial_capital=capital))


def test_total_return_and_known_cagr():
    report = run_analytics(result((100, 110, 120)), config=AnalyticsConfig(annualization=2))
    assert report.total_return == pytest.approx(.2)
    assert report.cagr == pytest.approx(1.2 ** (2 / 2) - 1)


def test_volatility_sharpe_sortino_known_returns():
    report = run_analytics(result((100, 110, 99, 118.8)), config=AnalyticsConfig(annualization=1))
    returns = np.array([.1, -.1, .2])
    assert report.daily_returns == pytest.approx(returns)
    assert report.annualized_volatility == pytest.approx(np.std(returns, ddof=1))
    assert report.sharpe_ratio == pytest.approx(returns.mean() / np.std(returns, ddof=1))
    downside = np.sqrt(np.mean(np.square(np.minimum(returns, 0))))
    assert report.downside_deviation == pytest.approx(downside)
    assert report.sortino_ratio == pytest.approx(returns.mean() / downside)


def test_drawdown_duration_ulcer_and_recovery_at_equal_high():
    report = run_analytics(result((100, 110, 100, 110)), config=AnalyticsConfig(annualization=1))
    dd = report.drawdowns
    assert report.maximum_drawdown == pytest.approx(-1 / 11)
    assert report.maximum_drawdown_duration_observations == 2
    assert dd.start == BASE + timedelta(days=1)
    assert dd.trough == BASE + timedelta(days=2)
    assert dd.recovery == BASE + timedelta(days=3)
    assert dd.high_water_mark == pytest.approx((100, 110, 110, 110))
    assert dd.ulcer_index == pytest.approx(np.sqrt(np.mean(np.square([0, 0, -1 / 11, 0]))))


def test_trade_statistics_use_completed_cycles_and_actual_fills():
    realized = [10.0, -5.0, 0.0, 3.0]
    trades = tuple(TradeRecord(str(i), "SPY", "SELL", "EXIT", "test", None, BASE, BASE, BASE,
                               BASE + timedelta(days=i), 10, 10, 1, 10, 0, 0, pnl)
                   for i, pnl in enumerate(realized))
    positions = tuple(PositionPoint(BASE + timedelta(days=i), "SPY", 0, 0, PositionState()) for i in range(4))
    fills = tuple(Fill(f"f{i}", str(i), "SPY", "SELL", 1, 10, BASE + timedelta(days=i)) for i in range(4))
    report = run_analytics(result((100, 101, 100, 103), trades=trades, fills=fills, positions=positions),
                           config=AnalyticsConfig(annualization=1))
    stats = report.trades
    assert (stats.filled_trades, stats.buy_fills, stats.sell_fills, stats.completed_cycles) == (4, 0, 4, 4)
    assert stats.winning_exits == 2 and stats.losing_exits == 1
    assert stats.win_rate == pytest.approx(2 / 4)
    assert stats.profit_factor == pytest.approx(13 / 5)
    assert stats.average_trade_pnl == pytest.approx(2)
    assert stats.best_trade == 10 and stats.worst_trade == -5
    assert stats.maximum_consecutive_winning_trades == 1
    assert stats.maximum_consecutive_losing_trades == 1


def test_sell_fills_are_aggregated_until_position_cycle_closes():
    trades = tuple(TradeRecord(str(i), "SPY", "SELL", "EXIT", "test", None, BASE, BASE, BASE,
                               BASE + timedelta(days=i), 10, 10, 1, 10, 0, 0, pnl)
                   for i, pnl in enumerate((2, 3)))
    positions = (PositionPoint(BASE, "SPY", 1, 10, PositionState()),
                 PositionPoint(BASE + timedelta(days=1), "SPY", 0, 0, PositionState()))
    report = run_analytics(result((100, 101), trades=trades, positions=positions),
                           config=AnalyticsConfig(annualization=1))
    assert report.trades.completed_cycles == 1
    assert report.trades.average_trade_pnl == 5


def test_consecutive_trade_streaks():
    pnls = [1, 2, -1, -2, -3, 4]
    trades = tuple(TradeRecord(str(i), "SPY", "SELL", "EXIT", "test", None, BASE, BASE, BASE,
                               BASE + timedelta(days=i), 10, 10, 1, 10, 0, 0, pnl) for i, pnl in enumerate(pnls))
    positions = tuple(PositionPoint(BASE + timedelta(days=i), "SPY", 0, 0, PositionState()) for i in range(6))
    stats = run_analytics(result(tuple(100 + i for i in range(6)), trades=trades, positions=positions)).trades
    assert stats.maximum_consecutive_winning_trades == 2
    assert stats.maximum_consecutive_losing_trades == 3


def test_only_buy_fills_have_no_completed_trade_statistics():
    fill = Fill("f", "o", "BTC", "BUY", 1, 10, BASE)
    stats = run_analytics(result((100, 101), fills=(fill,))).trades
    assert stats.filled_trades == 1 and stats.buy_fills == 1 and stats.sell_fills == 0
    assert stats.completed_cycles == 0 and stats.win_rate is None and stats.profit_factor is None


def test_zero_volatility_and_undefined_ratios_are_none():
    report = run_analytics(result((100, 100, 100)), config=AnalyticsConfig(annualization=252))
    assert report.annualized_volatility == 0
    assert report.sharpe_ratio is None and report.sortino_ratio is None and report.calmar_ratio is None
    assert report.trades.win_rate is None and report.total_return == 0
    assert all(v is None or np.isfinite(v) for v in (report.cagr, report.sharpe_ratio, report.sortino_ratio))


def test_no_trades_zero_costs_and_exposure():
    report = run_analytics(result((100, 100)))
    assert report.trades.filled_trades == 0
    assert report.costs.total == 0 and report.costs.fraction_of_traded_notional is None
    assert report.exposure.percent_invested == 100 and report.exposure.percent_zero_position == 0
    assert report.exposure.minimum_cash == report.exposure.average_cash == 40


def test_transaction_cost_totals_from_actual_fills():
    fills = (Fill("f1", "o1", "SPY", "BUY", 2, 10, BASE, 0.4, 0.2),
             Fill("f2", "o2", "SPY", "SELL", 2, 11, BASE + timedelta(days=1), 0.44, 0.22))
    report = run_analytics(result((100, 101), fills=fills))
    assert report.costs.commissions == pytest.approx(.84)
    assert report.costs.slippage == pytest.approx(.42)
    assert report.costs.total == pytest.approx(1.26)
    assert report.costs.fraction_of_traded_notional == pytest.approx(1.26 / 42)


def test_asset_attribution_and_missing_data():
    trade = TradeRecord("o", "GLD", "SELL", "EXIT", "test", None, BASE, BASE, BASE, BASE, 10, 10, 1, 10, 0, 0, 5)
    fill = Fill("f", "o", "GLD", "SELL", 1, 10, BASE, .1, .2)
    summary = AssetSummary("GLD", 2, 1, 3.0, 10.0)
    pos = PositionPoint(BASE, "GLD", 1, 8, PositionState())
    report = run_analytics(result((100, 105), trades=(trade,), fills=(fill,), positions=(pos,), assets=(summary,)))
    asset = report.assets[0]
    assert asset.asset == "GLD" and asset.cycles == 2 and asset.fills == 1
    assert asset.realized_pnl == 5 and asset.contribution_to_realized_pnl == 1
    assert asset.approximate_return_contribution == .05
    assert asset.transaction_costs == pytest.approx(.3)
    assert asset.average_exposure == asset.maximum_exposure == 8
    assert run_analytics(result()).assets == ()


def test_benchmark_comparison_and_timestamp_validation():
    base = result((100, 110, 120))
    index = pd.DatetimeIndex([p.timestamp for p in base.portfolio_curve])
    report = run_analytics(base, benchmark=pd.Series([100, 105, 110], index=index), config=AnalyticsConfig(annualization=2))
    assert report.benchmark.strategy_total_return == pytest.approx(.2)
    assert report.benchmark.benchmark_total_return == pytest.approx(.1)
    assert report.benchmark.excess_return == pytest.approx(.1)
    with pytest.raises(ValueError):
        run_analytics(base, benchmark=[100])


def test_deterministic_repeat_and_empty_result():
    empty = result((), capital=100)
    assert run_analytics(empty) == run_analytics(empty)
    assert run_analytics(empty).final_equity is None
    assert run_analytics(empty).maximum_drawdown is None
    assert run_analytics(empty).trades.win_rate is None


def test_one_observation_and_zero_initial_capital():
    assert run_analytics(result((100,))).cagr is None
    report = run_analytics(result((0, 0), capital=0))
    assert report.total_return is None and report.cagr is None


def test_configured_annualization_and_risk_free_rate():
    report = run_analytics(result((100, 110, 100)), config=AnalyticsConfig(annualization=12, risk_free_rate=.12))
    assert report.annualization == 12 and report.risk_free_rate == .12


def test_best_and_worst_period_are_observation_returns():
    report = run_analytics(result((100, 110, 99, 108.9)), config=AnalyticsConfig(annualization=1))
    assert report.best_period == pytest.approx(.1)
    assert report.worst_period == pytest.approx(-.1)


def test_unrecovered_drawdown_ends_at_final_observation():
    report = run_analytics(result((100, 90, 80)), config=AnalyticsConfig(annualization=1))
    assert report.drawdowns.recovery is None
    assert report.maximum_drawdown_duration_observations == 2
    assert report.drawdowns.start == BASE
    assert report.drawdowns.trough == BASE + timedelta(days=2)


def test_position_exposure_fields_use_observed_portfolio_curve():
    report = run_analytics(result((100, 100)))
    assert report.exposure.average_gross_exposure == pytest.approx(.6)
    assert report.exposure.maximum_net_exposure == pytest.approx(.6)
    assert report.exposure.percent_invested == 100


def test_open_sell_does_not_count_as_completed_cycle():
    trade = TradeRecord("o", "SPY", "SELL", "EXIT", "partial", None, BASE, BASE, BASE,
                        BASE, 10, 10, 1, 10, 0, 0, -3)
    position = PositionPoint(BASE, "SPY", 1, 12, PositionState())
    fill = Fill("f", "o", "SPY", "SELL", 1, 10, BASE)
    stats = run_analytics(result((100,), trades=(trade,), fills=(fill,), positions=(position,))).trades
    assert stats.sell_fills == 1
    assert stats.completed_cycles == 0 and stats.win_rate is None


def test_zero_equity_return_is_null_and_benchmark_nan_rejected():
    bankrupt = run_analytics(result((100, 0, 10)), config=AnalyticsConfig(annualization=1))
    assert bankrupt.daily_returns == (-1.0, None)
    assert bankrupt.annualized_volatility is None and bankrupt.sharpe_ratio is None
    with pytest.raises(ValueError):
        run_analytics(result((100, 101)), benchmark=[100, float("nan")])
