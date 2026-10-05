from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DrawdownReport:
    high_water_mark: tuple[float, ...]
    drawdown: tuple[float, ...]
    maximum_drawdown: float | None
    start: datetime | None
    trough: datetime | None
    recovery: datetime | None
    maximum_duration_observations: int | None
    average_drawdown: float | None
    ulcer_index: float | None


@dataclass(frozen=True)
class TradeReport:
    filled_trades: int
    buy_fills: int
    sell_fills: int
    completed_cycles: int
    winning_exits: int
    losing_exits: int
    win_rate: float | None
    average_trade_pnl: float | None
    median_trade_pnl: float | None
    best_trade: float | None
    worst_trade: float | None
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    average_winning_trade: float | None
    average_losing_trade: float | None
    average_holding_period_days: float | None
    maximum_consecutive_losing_trades: int
    maximum_consecutive_winning_trades: int


@dataclass(frozen=True)
class ExposureReport:
    average_gross_exposure: float | None
    maximum_gross_exposure: float | None
    average_net_exposure: float | None
    maximum_net_exposure: float | None
    minimum_cash: float | None
    average_cash: float | None
    percent_invested: float | None
    percent_zero_position: float | None


@dataclass(frozen=True)
class AssetReport:
    asset: str
    cycles: int
    fills: int
    total_traded_notional: float
    average_holding_period_days: float | None
    realized_pnl: float
    contribution_to_realized_pnl: float | None
    approximate_return_contribution: float | None
    transaction_costs: float
    average_exposure: float | None
    maximum_exposure: float | None


@dataclass(frozen=True)
class CostReport:
    commissions: float
    slippage: float
    total: float
    fraction_of_initial_capital: float | None
    fraction_of_traded_notional: float | None


@dataclass(frozen=True)
class BenchmarkReport:
    strategy_total_return: float | None
    benchmark_total_return: float | None
    strategy_cagr: float | None
    benchmark_cagr: float | None
    strategy_maximum_drawdown: float | None
    benchmark_maximum_drawdown: float | None
    excess_return: float | None


@dataclass(frozen=True)
class AnalyticsReport:
    initial_capital: float
    final_equity: float | None
    total_return: float | None
    cagr: float | None
    daily_returns: tuple[float | None, ...]
    annualized_volatility: float | None
    downside_deviation: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    maximum_drawdown: float | None
    maximum_drawdown_duration_observations: int | None
    calmar_ratio: float | None
    best_period: float | None
    worst_period: float | None
    drawdowns: DrawdownReport
    trades: TradeReport
    exposure: ExposureReport
    costs: CostReport
    assets: tuple[AssetReport, ...]
    benchmark: BenchmarkReport | None
    annualization: int
    risk_free_rate: float
    conventions: tuple[str, ...]
