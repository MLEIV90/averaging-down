import json
import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum

from src.backtest.engine import run_backtest
from src.data.config import REPOSITORY_ROOT, load_assets_config
from src.data.engine import DataEngine
from src.analytics import run_analytics
from src.validation import run_validation


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def run(*, analytics: bool = False, validation: bool = False):
    configured_assets, _ = load_assets_config()
    data_engine = DataEngine()
    data_dict = {}
    output_dir = REPOSITORY_ROOT / "data" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)

    for ticker, config in configured_assets.items():
        if not config.enabled:
            continue
        frame = data_engine.load_or_download(ticker, allow_download=True)
        data_dict[ticker] = frame

    result = run_backtest(data_dict)
    if not result.portfolio_curve:
        raise RuntimeError("Backtest engine returned an empty portfolio curve.")

    result.equity_curve.to_csv(output_dir / "equity_curve.csv", header=["Equity"], index_label="Date")
    result.cash_curve.to_csv(output_dir / "cash_curve.csv", header=["Cash"], index_label="Date")
    (output_dir / "backtest_portfolio.json").write_text(json.dumps(
        _jsonable(result.portfolio_curve), indent=2), encoding="utf-8")
    (output_dir / "backtest_positions.json").write_text(json.dumps(
        _jsonable(result.position_history), indent=2), encoding="utf-8")
    (output_dir / "backtest_trades.json").write_text(json.dumps(
        _jsonable(result.trades), indent=2), encoding="utf-8")
    (output_dir / "backtest_orders.json").write_text(json.dumps(
        _jsonable(result.orders), indent=2), encoding="utf-8")
    raw_summary = {
        "total_transaction_costs": result.total_transaction_costs,
        "configuration": _jsonable(result.configuration),
        "order_count": len(result.orders),
        "filled_trade_count": len(result.trades),
        "pending_order_count": len(result.pending_orders),
        "initial_equity": result.portfolio_curve[0].equity,
        "final_equity": result.portfolio_curve[-1].equity,
        "per_asset": _jsonable(result.per_asset),
        "pending_orders": [{"asset": record.order.asset if record.order else None,
                            "status": record.status, "action": record.action,
                            "reason": record.reason} for record in result.pending_orders],
    }
    summary = _jsonable(run_analytics(result)) if analytics else raw_summary
    (output_dir / "backtest_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if validation:
        report = run_validation(result)
        (output_dir / "backtest_validation.json").write_text(
            json.dumps(_jsonable(report), indent=2, allow_nan=False), encoding="utf-8")
    print("Sequential backtest completed; portfolio curves and trade records exported.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run sequential backtest and export raw outputs.")
    parser.add_argument("--analytics", action="store_true", help="Write performance analytics to backtest_summary.json.")
    parser.add_argument("--validation", action="store_true", help="Write research-integrity findings to backtest_validation.json.")
    options = parser.parse_args()
    run(analytics=options.analytics, validation=options.validation)
