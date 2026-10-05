"""Canonical public backtest entry point (sequential strategy simulation)."""

from __future__ import annotations

from src.backtest.sequential import (
    AssetSummary,
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    OrderRecord,
    PortfolioPoint,
    PositionPoint,
    TradeRecord,
    load_backtest_config,
)
from src.backtest.legacy_engine import get_benchmark_curve
from src.features.config import FeatureConfig
from src.features.engine import FeatureEngine


def run_backtest(data_dict, feature_config: FeatureConfig | None = None, **engine_options) -> BacktestResult:
    """Run raw validated OHLCV through the canonical event-driven engine."""
    feature_engine = engine_options.pop("feature_engine", None)
    if feature_engine is None:
        feature_engine = FeatureEngine(feature_config)
    return BacktestEngine(feature_engine=feature_engine, **engine_options).run(data_dict)


__all__ = [
    "AssetSummary", "BacktestConfig", "BacktestEngine", "BacktestResult",
    "OrderRecord", "PortfolioPoint", "PositionPoint", "TradeRecord",
    "get_benchmark_curve", "load_backtest_config", "run_backtest",
]
