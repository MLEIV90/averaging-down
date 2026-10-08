"""Sequential, next-available-bar backtest using the production research engines."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import math
from pathlib import Path
from typing import Mapping

import pandas as pd
import yaml

from src.data.config import REPOSITORY_ROOT
from src.data.validator import DataValidator
from src.execution.accounting import AccountingEngine, CashLedger
from src.execution.orders import Fill, Order, OrderStatus, create_paper_order
from src.features.engine import FeatureEngine
from src.features.regime import RegimeEngine
from src.portfolio.engine import AllocationDecision, AllocationProposal, PortfolioEngine, PortfolioSnapshot
from src.risk.sizing_engine import RiskSizingEngine, SizingDecision
from src.strategy.exits import ExitDecision, ExitEngine, should_reset_cycle
from src.strategy.scale_in import ScaleInDecision, ScaleInEngine
from src.strategy.signals import SignalEngine, SignalResult
from src.strategy.state_machine import PositionState

DEFAULT_BACKTEST_CONFIG = REPOSITORY_ROOT / "config" / "backtest.yaml"
SUPPORTED_ASSETS = ("SPY", "BTC", "GLD")


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float | None = None
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    execution_model: str = "next_bar_open"

    def __post_init__(self) -> None:
        for name in ("commission_bps", "slippage_bps"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite.")
        if self.initial_capital is not None and (
            isinstance(self.initial_capital, bool)
            or not isinstance(self.initial_capital, (int, float))
            or not math.isfinite(self.initial_capital)
        ):
            raise ValueError("initial_capital must be finite when supplied.")
        if ((self.initial_capital is not None and self.initial_capital < 0)
                or self.commission_bps < 0 or self.slippage_bps < 0):
            raise ValueError("Capital and transaction costs cannot be negative.")
        if self.slippage_bps + self.commission_bps >= 10_000:
            raise ValueError("Combined commission and slippage must be less than 10000 bps.")
        if self.execution_model != "next_bar_open":
            raise ValueError("Only the explicit next_bar_open execution model is supported.")


def load_backtest_config(path: str | Path = DEFAULT_BACKTEST_CONFIG) -> BacktestConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        section = raw["backtest"]
        execution = section["execution_model"]
        commission = section["commission_bps"]
        slippage = section["slippage_bps"]
        portfolio_raw = yaml.safe_load((REPOSITORY_ROOT / "config" / "portfolio.yaml").read_text(encoding="utf-8"))
        initial_capital = portfolio_raw["portfolio"]["initial_capital"]
    except (OSError, yaml.YAMLError, TypeError, KeyError) as exc:
        raise ValueError(f"Invalid backtest configuration at {config_path}: {exc}") from exc
    return BacktestConfig(initial_capital, commission, slippage, execution)


@dataclass(frozen=True)
class PortfolioPoint:
    timestamp: datetime
    cash: float
    market_value: float
    equity: float
    gross_exposure: float
    net_exposure: float
    realized_pnl: float
    unrealized_pnl: float
    total_transaction_costs: float


@dataclass(frozen=True)
class PositionPoint:
    timestamp: datetime
    asset: str
    quantity: float
    average_entry_price: float
    state: PositionState


@dataclass(frozen=True)
class TradeRecord:
    order_id: str
    asset: str
    side: str
    action: str
    reason: str
    tier: str | None
    signal_timestamp: datetime
    decision_timestamp: datetime
    order_timestamp: datetime
    fill_timestamp: datetime
    reference_price: float
    fill_price: float
    quantity: float
    notional: float
    commission: float
    slippage_cost: float
    realized_pnl: float


@dataclass(frozen=True)
class OrderRecord:
    order: Order | None
    action: str
    reason: str
    tier: str | None
    reference_price: float
    fill: Fill | None
    status: str
    requested_quantity: float
    approved_quantity: float
    allocation: AllocationDecision | None = None


@dataclass(frozen=True)
class AssetSummary:
    asset: str
    cycles: int
    fills: int
    average_holding_days: float
    total_notional_traded: float


@dataclass(frozen=True)
class BacktestResult:
    portfolio_curve: tuple[PortfolioPoint, ...]
    trades: tuple[TradeRecord, ...]
    orders: tuple[OrderRecord, ...]
    pending_orders: tuple[OrderRecord, ...]
    position_history: tuple[PositionPoint, ...]
    per_asset: tuple[AssetSummary, ...]
    total_transaction_costs: float
    configuration: BacktestConfig

    @property
    def equity_curve(self) -> pd.Series:
        return pd.Series(
            [point.equity for point in self.portfolio_curve],
            index=pd.DatetimeIndex([point.timestamp for point in self.portfolio_curve]),
            name="Equity", dtype="float64",
        )

    @property
    def cash_curve(self) -> pd.Series:
        return pd.Series(
            [point.cash for point in self.portfolio_curve],
            index=pd.DatetimeIndex([point.timestamp for point in self.portfolio_curve]),
            name="Cash", dtype="float64",
        )


@dataclass
class _QueuedOrder:
    record_index: int
    due_timestamp: pd.Timestamp | None
    scale_decision: ScaleInDecision | None
    exit_decision: ExitDecision | None
    entry_atr: float | None


def _asset_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("Asset identifiers must be strings.")
    asset = name.strip().upper()
    if asset == "BTC-USD":
        asset = "BTC"
    if asset not in SUPPORTED_ASSETS:
        raise ValueError(f"Unsupported backtest asset {name!r}.")
    return asset


def _timestamp(value: pd.Timestamp) -> datetime:
    result = value.to_pydatetime()
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("All backtest bar timestamps must be timezone-aware.")
    return result


def _valid_feature(row: pd.Series, column: str) -> float | None:
    value = row.get(column)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


class BacktestEngine:
    """Run supplied validated OHLCV through sequential strategy and accounting."""

    def __init__(
        self,
        *,
        config: BacktestConfig | None = None,
        config_path: str | Path = DEFAULT_BACKTEST_CONFIG,
        feature_engine: FeatureEngine | None = None,
        signal_engine: SignalEngine | None = None,
        risk_engine: RiskSizingEngine | None = None,
        portfolio_engine: PortfolioEngine | None = None,
        exit_engine: ExitEngine | None = None,
        accounting_engine: AccountingEngine | None = None,
        scale_in_engines: Mapping[str, ScaleInEngine] | None = None,
    ):
        loaded_config = load_backtest_config(config_path)
        selected_config = config or loaded_config
        self.config = selected_config if selected_config.initial_capital is not None else replace(
            selected_config, initial_capital=loaded_config.initial_capital
        )
        self.feature_engine = feature_engine or FeatureEngine()
        self.regime_engine = RegimeEngine(feature_config=self.feature_engine.config)
        self.signal_engine = signal_engine or SignalEngine(
            regime_engine=self.regime_engine, feature_config=self.feature_engine.config
        )
        self.risk_engine = risk_engine or RiskSizingEngine()
        self.portfolio_engine = portfolio_engine or PortfolioEngine()
        self.exit_engine = exit_engine or ExitEngine()
        self.accounting_engine = accounting_engine or AccountingEngine()
        self.scale_in_engines = dict(scale_in_engines or {
            asset: ScaleInEngine(asset) for asset in SUPPORTED_ASSETS
        })

    def run(
        self,
        data: Mapping[str, pd.DataFrame],
        *,
        evaluation_start: pd.Timestamp | datetime | None = None,
        evaluation_end: pd.Timestamp | datetime | None = None,
    ) -> BacktestResult:
        if not isinstance(data, Mapping):
            raise TypeError("data must map configured asset identifiers to OHLCV DataFrames.")
        def boundary(value, name):
            if value is None:
                return None
            stamp = pd.Timestamp(value)
            if stamp.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware.")
            return stamp.tz_convert("UTC")
        start_boundary = boundary(evaluation_start, "evaluation_start")
        end_boundary = boundary(evaluation_end, "evaluation_end")
        if start_boundary is not None and end_boundary is not None and start_boundary > end_boundary:
            raise ValueError("evaluation_start must be <= evaluation_end.")
        normalized: dict[str, pd.DataFrame] = {}
        for raw_asset, frame in data.items():
            asset = _asset_name(raw_asset)
            if asset in normalized:
                raise ValueError(f"Duplicate input data for normalized asset {asset}.")
            if not isinstance(frame, pd.DataFrame):
                raise ValueError(f"Data for {asset} must be a DataFrame.")
            if frame.empty:
                continue
            report = DataValidator().validate(frame)
            if not report.is_valid:
                details = "; ".join(issue.message for issue in report.errors)
                raise ValueError(f"Invalid OHLCV data for {asset}: {details}")
            utc_frame = frame.copy()
            utc_frame.index = utc_frame.index.tz_convert("UTC")
            normalized[asset] = utc_frame
        if not normalized:
            return BacktestResult((), (), (), (), (), (), 0.0, self.config)

        features: dict[str, pd.DataFrame] = {}
        signals: dict[str, pd.DataFrame] = {}
        bars_by_asset: dict[str, pd.DataFrame] = {}
        for asset in SUPPORTED_ASSETS:
            if asset not in normalized:
                continue
            bars_by_asset[asset] = normalized[asset]
            features[asset] = self.feature_engine.compute(normalized[asset])
            signal_frame = self.signal_engine.classify_series(features[asset], asset)
            if not signal_frame.index.equals(features[asset].index):
                raise ValueError(f"Signal timestamps are not aligned for {asset}.")
            signals[asset] = signal_frame

        timestamps = sorted(set().union(*(set(frame.index) for frame in bars_by_asset.values())))
        bar_positions = {asset: {ts: index for index, ts in enumerate(frame.index)}
                         for asset, frame in bars_by_asset.items()}
        ledger = CashLedger(float(self.config.initial_capital))
        states = {asset: PositionState() for asset in bars_by_asset}
        latest_prices: dict[str, float] = {}
        entry_atr: dict[str, float | None] = {asset: None for asset in bars_by_asset}
        cycle_starts: dict[str, datetime] = {}
        cycles = {asset: 0 for asset in bars_by_asset}
        fill_counts = {asset: 0 for asset in bars_by_asset}
        traded_notional = {asset: 0.0 for asset in bars_by_asset}
        holding_days: dict[str, list[float]] = {asset: [] for asset in bars_by_asset}
        total_costs = 0.0
        order_records: list[OrderRecord] = []
        trades: list[TradeRecord] = []
        queued: list[_QueuedOrder] = []
        points: list[PortfolioPoint] = []
        positions: list[PositionPoint] = []
        order_counter = 0
        fill_counter = 0
        cfg = self.feature_engine.config
        atr_column = f"atr{cfg.atr_period}"
        vol_column = f"realized_vol_{cfg.realized_vol_period}"
        rsi_column = f"rsi{cfg.rsi_fast_period}"

        for timestamp in timestamps:
            if start_boundary is not None and timestamp < start_boundary:
                continue
            if end_boundary is not None and timestamp > end_boundary:
                continue
            ts_dt = _timestamp(timestamp)
            current_assets = [asset for asset in SUPPORTED_ASSETS
                              if asset in bars_by_asset and timestamp in bars_by_asset[asset].index]

            # Orders are eligible only on that asset's next available bar.
            due = [item for item in queued if item.due_timestamp == timestamp]
            fill_priority = {asset: index for index, asset in enumerate(self.portfolio_engine.config.priority_order)}
            due.sort(key=lambda item: fill_priority[order_records[item.record_index].order.asset])
            for queued_order in due:
                record = order_records[queued_order.record_index]
                order = record.order
                bar = bars_by_asset[order.asset].loc[timestamp]
                raw_open = float(bar["open"])
                slippage_rate = self.config.slippage_bps / 10_000
                # Fill.price remains the observed bar open. Slippage is separately
                # booked as a dollar cost by AccountingEngine, so it is charged once.
                fill_price = raw_open
                commission = order.quantity * fill_price * self.config.commission_bps / 10_000
                slip_cost = order.quantity * raw_open * slippage_rate
                current_position = next((p for p in ledger.positions if p.asset == order.asset), None)
                if order.side == "SELL" and (current_position is None or order.quantity > current_position.quantity + 1e-12):
                    order_records[queued_order.record_index] = replace(
                        record, order=replace(order, status=OrderStatus.REJECTED), status="REJECTED"
                    )
                    queued.remove(queued_order)
                    continue
                if order.side == "BUY" and order.quantity * fill_price + commission + slip_cost > ledger.cash + 1e-10:
                    order_records[queued_order.record_index] = replace(
                        record, order=replace(order, status=OrderStatus.REJECTED), status="REJECTED"
                    )
                    queued.remove(queued_order)
                    continue

                fill_counter += 1
                fill = Fill(
                    fill_id=f"fill-{fill_counter:08d}", order_id=order.order_id,
                    asset=order.asset, side=order.side, quantity=order.quantity,
                    fill_price=fill_price, fill_timestamp=ts_dt,
                    commission=commission, slippage_cost=slip_cost,
                )
                prior_realized = ledger.realized_pnl
                ledger = self.accounting_engine.apply_fill(ledger, order, fill)
                realized_delta = ledger.realized_pnl - prior_realized
                total_costs += commission + slip_cost
                fill_counts[order.asset] += 1
                traded_notional[order.asset] += order.quantity * fill_price
                if order.side == "BUY":
                    if not states[order.asset].cycle_active:
                        entry_atr[order.asset] = queued_order.entry_atr
                        cycles[order.asset] += 1
                        cycle_starts[order.asset] = ts_dt
                    if queued_order.scale_decision is None:
                        raise RuntimeError("BUY fill is missing its scale-in decision.")
                    states[order.asset] = self.scale_in_engines[order.asset].apply_fill(
                        states[order.asset], queued_order.scale_decision, fill_price, ts_dt
                    )
                else:
                    remaining_position = next((p for p in ledger.positions if p.asset == order.asset), None)
                    remaining_quantity = remaining_position.quantity if remaining_position else 0.0
                    if queued_order.exit_decision is None:
                        raise RuntimeError("SELL fill is missing its exit decision.")
                    if should_reset_cycle(queued_order.exit_decision,
                                          position_quantity_after_fill=remaining_quantity):
                        start = cycle_starts.pop(order.asset, states[order.asset].entry_timestamp)
                        if start is not None:
                            holding_days[order.asset].append((ts_dt - start).total_seconds() / 86400)
                        states[order.asset] = self.scale_in_engines[order.asset].reset_cycle(states[order.asset])
                        entry_atr[order.asset] = None
                    else:
                        states[order.asset] = replace(
                            states[order.asset],
                            partial_sell_stage=states[order.asset].partial_sell_stage + 1,
                        )
                trades.append(TradeRecord(
                    order.order_id, order.asset, order.side, record.action, record.reason,
                    record.tier, order.signal_timestamp, order.decision_timestamp,
                    order.order_timestamp, ts_dt, record.reference_price, fill_price,
                    order.quantity, order.quantity * fill_price, commission, slip_cost,
                    realized_delta,
                ))
                order_records[queued_order.record_index] = replace(
                    record, order=replace(order, status=OrderStatus.FILLED), fill=fill, status="FILLED"
                )
                queued.remove(queued_order)

            # Today's close is now observable; carry forward asynchronous asset marks.
            for asset in current_assets:
                latest_prices[asset] = float(bars_by_asset[asset].loc[timestamp, "close"])
            account = self.accounting_engine.snapshot(ledger, ts_dt, latest_prices)
            market_value = account.market_value
            gross = market_value / account.equity if account.equity else 0.0
            points.append(PortfolioPoint(
                ts_dt, account.cash, market_value, account.equity, gross, gross,
                account.realized_pnl, account.unrealized_pnl, total_costs,
            ))
            if not math.isclose(account.equity, account.cash + market_value,
                                rel_tol=1e-10, abs_tol=1e-8):
                raise RuntimeError("Accounting invariant failed: equity != cash + marked holdings.")
            for asset in bars_by_asset:
                position = next((p for p in account.positions if p.asset == asset), None)
                positions.append(PositionPoint(ts_dt, asset, position.quantity if position else 0.0,
                                               position.average_entry_price if position else 0.0,
                                               states[asset]))

            # Exits take precedence over new scale-in proposals for that asset.
            proposals: list[tuple[str, ScaleInDecision, float, SizingDecision]] = []
            exit_proposals: list[tuple[str, ExitDecision, float]] = []
            for asset in current_assets:
                feature_row = features[asset].loc[timestamp]
                position = next((p for p in ledger.positions if p.asset == asset), None)
                signal_row = signals[asset].loc[timestamp]
                if position is not None and states[asset].cycle_active:
                    z = _valid_feature(feature_row, "z_atr")
                    rsi = _valid_feature(feature_row, rsi_column)
                    ema = _valid_feature(feature_row, f"ema{cfg.ema_fast}")
                    decision = self.exit_engine.evaluate(
                        asset=asset, position_quantity=position.quantity,
                        anchor_price=float(states[asset].anchor_price),
                        entry_timestamp=states[asset].entry_timestamp,
                        entry_atr=entry_atr[asset], current_timestamp=ts_dt,
                        current_price=latest_prices[asset], z_atr=z, rsi2=rsi,
                        partial_sell_stage=states[asset].partial_sell_stage, ema20=ema,
                    )
                    if decision.action in {"FULL_EXIT", "PARTIAL_SELL"}:
                        quantity = position.quantity * decision.quantity_fraction
                        if quantity > 0:
                            exit_proposals.append((asset, decision, quantity))
                        continue

                signal_payload = {name: signal_row[name]
                                  for name in SignalResult.__dataclass_fields__}
                for name in ("entry_candidate", "insufficient_data"):
                    signal_payload[name] = bool(signal_payload[name])
                signal = SignalResult(**signal_payload)
                scale = self.scale_in_engines[asset].evaluate(signal, states[asset])
                if scale.action not in {"BUY_T1", "BUY_T2", "BUY_T3"}:
                    continue
                atr = _valid_feature(feature_row, atr_column)
                vol = _valid_feature(feature_row, vol_column)
                if account.equity <= 0 or atr is None or vol is None or atr <= 0 or vol <= 0:
                    continue
                sizing = self.risk_engine.size(
                    scale, equity=account.equity, available_cash=account.cash,
                    reference_price=latest_prices[asset], atr=atr, realized_vol=vol,
                )
                if sizing.final_quantity > 0:
                    proposals.append((asset, scale, atr, sizing))

            if proposals:
                reference_prices = dict(latest_prices)
                for asset, _, _, sizing in proposals:
                    reference_prices[asset] = sizing.reference_price
                snapshot = PortfolioSnapshot(
                    ts_dt, account.equity, account.cash,
                    {p.asset: p.quantity for p in ledger.positions},
                )
                allocated = self.portfolio_engine.evaluate(
                    snapshot,
                    [AllocationProposal(sizing, ts_dt) for _, _, _, sizing in proposals],
                    reference_prices,
                    transaction_cost_rate=(self.config.commission_bps + self.config.slippage_bps) / 10_000,
                )
                allocation_by_asset = {decision.asset: decision for decision in allocated.decisions}
                for asset, scale, atr, sizing in proposals:
                    decision = allocation_by_asset[asset]
                    if decision.approved_quantity <= 0:
                        order_records.append(OrderRecord(
                            None, scale.action,
                            f"portfolio_rejected:{decision.binding_constraint.lower()}",
                            scale.target_tier, decision.reference_price, None, "REJECTED",
                            decision.requested_quantity, 0.0, decision,
                        ))
                        continue
                    order_counter += 1
                    order = create_paper_order(
                        asset, "BUY", decision.approved_quantity,
                        order_id=f"order-{order_counter:08d}",
                        signal_timestamp=ts_dt, decision_timestamp=ts_dt,
                        order_timestamp=ts_dt,
                    )
                    record = OrderRecord(
                        order, scale.action, scale.reason if decision.binding_constraint == "NONE"
                        else f"{scale.reason}; reduced_by_{decision.binding_constraint.lower()}",
                        scale.target_tier, decision.reference_price, None, "PENDING",
                        decision.requested_quantity, decision.approved_quantity, decision,
                    )
                    record_index = len(order_records)
                    order_records.append(record)
                    position = bar_positions[asset][timestamp]
                    frame = bars_by_asset[asset]
                    due_timestamp = frame.index[position + 1] if position + 1 < len(frame) else None
                    queued.append(_QueuedOrder(record_index, due_timestamp, scale, None, atr))

            for asset, decision, quantity in exit_proposals:
                order_counter += 1
                order = create_paper_order(
                    asset, "SELL", quantity, order_id=f"order-{order_counter:08d}",
                    signal_timestamp=ts_dt, decision_timestamp=ts_dt,
                    order_timestamp=ts_dt,
                )
                record = OrderRecord(order, decision.action, decision.reason,
                                     states[asset].last_tier, latest_prices[asset], None, "PENDING",
                                     quantity, quantity)
                record_index = len(order_records)
                order_records.append(record)
                position = bar_positions[asset][timestamp]
                frame = bars_by_asset[asset]
                due_timestamp = frame.index[position + 1] if position + 1 < len(frame) else None
                queued.append(_QueuedOrder(record_index, due_timestamp, None, decision, None))

        pending = tuple(order_records[item.record_index] for item in queued)
        return BacktestResult(
            tuple(points), tuple(trades), tuple(order_records), pending, tuple(positions),
            tuple(AssetSummary(
                asset, cycles[asset], fill_counts[asset],
                sum(holding_days[asset]) / len(holding_days[asset]) if holding_days[asset] else 0.0,
                traded_notional[asset],
            ) for asset in SUPPORTED_ASSETS if asset in bars_by_asset), total_costs, self.config,
        )
