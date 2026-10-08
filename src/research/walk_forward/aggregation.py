"""OOS return chaining; Analytics formulas remain in M11."""
from src.analytics import run_analytics
from src.backtest.sequential import BacktestConfig, BacktestResult, PortfolioPoint
from .models import OOSAggregateResult, OOSAnalytics, OOSGap

def aggregate_oos(results, timeline, *, initial_capital=1.0, calculate=True):
    all_test_dates = [point.timestamp for row in results if row.test_backtest
                      for point in row.test_backtest.portfolio_curve]
    unique_dates = tuple(sorted(set(all_test_dates)))
    duplicates = len(all_test_dates) - len(unique_dates)
    gaps = []
    by_index = {stamp.to_pydatetime(): i for i, stamp in enumerate(timeline)}
    ordered_windows = [row.window for row in results]
    for left, right in zip(ordered_windows, ordered_windows[1:]):
        skipped = by_index[right.test_start] - by_index[left.test_end] - 1
        if skipped > 0:
            gaps.append(OOSGap(left.test_end, right.test_start, skipped))

    aggregate_analytics = None
    if calculate and not duplicates and all(row.test_backtest and row.test_backtest.portfolio_curve for row in results):
        chained = []
        equity = initial_capital
        for row in results:
            curve = row.test_backtest.portfolio_curve
            prior_value = None
            for point_index, point in enumerate(curve):
                if prior_value is not None:
                    if prior_value <= 0:
                        aggregate_analytics = None
                        chained = []
                        break
                    equity *= point.equity / prior_value
                elif chained and point_index == 0:
                    # A reset-window opening mark is a new capital base, not a zero return.
                    prior_value = point.equity
                    continue
                gross = point.gross_exposure
                chained.append(PortfolioPoint(
                    point.timestamp, equity * (1.0-gross), equity*gross, equity, gross,
                    point.net_exposure, point.realized_pnl, point.unrealized_pnl,
                    point.total_transaction_costs,
                ))
                prior_value = point.equity
            if not chained:
                break
        if chained and not duplicates:
            synthetic = BacktestResult(tuple(chained), (), (), (), (), (), 0.0,
                                       BacktestConfig(initial_capital=initial_capital))
            report = run_analytics(synthetic)
            exposure_samples = [
                (row.analytics.exposure.average_gross_exposure, len(row.test_backtest.portfolio_curve))
                for row in results if row.analytics is not None and row.analytics.exposure.average_gross_exposure is not None
            ]
            average_gross = (
                sum(value * count for value, count in exposure_samples) / sum(count for _, count in exposure_samples)
                if exposure_samples else None
            )
            maximum_gross = max(
                (row.analytics.exposure.maximum_gross_exposure for row in results
                 if row.analytics is not None and row.analytics.exposure.maximum_gross_exposure is not None),
                default=None,
            )
            aggregate_analytics = OOSAnalytics(
                report.total_return, report.cagr, report.annualized_volatility,
                report.sharpe_ratio, report.sortino_ratio, report.maximum_drawdown,
                report.maximum_drawdown_duration_observations, report.drawdowns.ulcer_index,
                average_gross, maximum_gross,
            )

    analytics_reports = [row.analytics for row in results if row.analytics is not None]
    return OOSAggregateResult(
        aggregate_analytics, len(all_test_dates), len(unique_dates), duplicates, tuple(gaps),
        sum(a.trades.filled_trades for a in analytics_reports),
        sum(a.trades.completed_cycles for a in analytics_reports),
        sum(a.trades.winning_exits for a in analytics_reports),
        sum(a.trades.losing_exits for a in analytics_reports),
        sum(a.costs.total for a in analytics_reports),
        sum(sum(asset.realized_pnl for asset in a.assets) for a in analytics_reports),
        sum(a.trades.filled_trades == 0 for a in analytics_reports),
        sum(a.total_return is None for a in analytics_reports),
    )
