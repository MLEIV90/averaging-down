from __future__ import annotations

from collections import defaultdict
import math

import numpy as np

from src.backtest.sequential import BacktestResult
from .config import ValidationConfig
from .models import (AssetConcentration, CostDiagnostic, ExposureDiagnostic, Finding,
                     FindingStatus as S, Metric, SampleLabel, SampleSizeDiagnostic,
                     ScaleInDiagnostic, Section, Severity as V)


def _finding(name, status, severity, message, measured=None, expected=None):
    if isinstance(measured, float) and not math.isfinite(measured):
        measured = "NaN" if math.isnan(measured) else ("Infinity" if measured > 0 else "-Infinity")
    return Finding(name, status, severity, message, measured, expected)


def _finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def _safe_sum(values):
    result = sum(values)
    return float(result) if math.isfinite(float(result)) else None


def _cycles(result: BacktestResult):
    position_at = {(p.asset, p.timestamp): p.quantity for p in result.position_history}
    active = defaultdict(list)
    cycles, open_cycles = [], []
    missing = False
    for trade in result.trades:
        asset = trade.asset
        if trade.side == "BUY":
            active[asset].append(trade)
        elif trade.side == "SELL":
            if not active[asset]:
                missing = True
            position = position_at.get((asset, trade.fill_timestamp))
            if position is None:
                missing = True
            elif position == 0:
                if active[asset]:
                    sells = [t for t in result.trades if t.asset == asset and t.side == "SELL"
                             and t.fill_timestamp >= active[asset][0].fill_timestamp
                             and t.fill_timestamp <= trade.fill_timestamp]
                    cycles.append({"asset": asset, "entries": tuple(active[asset]),
                                   "trades": tuple(active[asset]) + tuple(sells),
                                   "pnl": _safe_sum(t.realized_pnl for t in sells
                                                    if _finite(t.realized_pnl))
                                   if all(_finite(t.realized_pnl) for t in sells) else None})
                else:
                    missing = True
                active[asset].clear()
    for asset, entries in active.items():
        if entries:
            open_cycles.append({"asset": asset, "entries": tuple(entries)})
    return cycles, open_cycles, not missing


def cost_diagnostic(result: BacktestResult, cfg: ValidationConfig) -> CostDiagnostic:
    initial_raw = getattr(result.configuration, "initial_capital", None)
    initial = float(initial_raw) if _finite(initial_raw) and initial_raw > 0 else 0.0
    final_raw = result.portfolio_curve[-1].equity if result.portfolio_curve else None
    final = float(final_raw) if _finite(final_raw) else None
    fills = [record.fill for record in result.orders if record.fill is not None]
    valid_costs = [f for f in fills if _finite(getattr(f, "commission", None)) and _finite(getattr(f, "slippage_cost", None))]
    total_cost = _safe_sum(float(f.commission) + float(f.slippage_cost) for f in valid_costs) if len(valid_costs) == len(fills) else None
    addback = final + total_cost if final is not None and total_cost is not None else None
    addback_return = addback / initial - 1 if addback is not None and initial > 0 else None
    after_return = final / initial - 1 if final is not None and initial > 0 else None
    valid_notional = [f for f in fills if _finite(getattr(f, "quantity", None)) and _finite(getattr(f, "fill_price", None))]
    traded = _safe_sum(float(f.quantity) * float(f.fill_price) for f in valid_notional) if len(valid_notional) == len(fills) else None
    fills_exist = bool(traded)
    findings = []
    if total_cost is None:
        findings.append(_finding("actual_fill_costs", S.NOT_EVALUABLE, V.WARNING,
                                 "Invalid Fill cost data prevents an actual-cost total."))
    elif fills_exist and total_cost == 0:
        findings.append(_finding("zero_costs_while_trading", S.WARNING, V.WARNING,
                                 "Trading occurred with zero recorded commissions and slippage; this is the configured cost assumption, not a validated cost estimate.",
                                 total_cost, "> 0"))
    else:
        findings.append(_finding("actual_fill_costs", S.PASS, V.INFO,
                                 "Cost totals are derived from recorded fill commissions and slippage.",
                                 total_cost, "sum of actual Fill costs"))
    if fills_exist and addback is not None:
        findings.append(_finding("mechanical_cost_addback", S.WARNING, V.WARNING,
                                 "Final equity plus recorded costs is a mechanical accounting add-back, not a no-cost strategy counterfactual; recorded costs may also have constrained approved quantities.",
                                 addback, "observed final equity + actual costs"))
    commission_bps = getattr(result.configuration, "commission_bps", None)
    slippage_bps = getattr(result.configuration, "slippage_bps", None)
    return CostDiagnostic(tuple(findings),
                          float(commission_bps) if _finite(commission_bps) else None,
                          float(slippage_bps) if _finite(slippage_bps) else None,
                          total_cost,
                          total_cost / initial if initial > 0 and total_cost is not None else None,
                          total_cost / traded if traded and traded > 0 and total_cost is not None else None,
                          final, after_return, addback, addback_return, total_cost, None)


def scale_in_diagnostic(result: BacktestResult, cfg: ValidationConfig) -> ScaleInDiagnostic:
    cycles, open_cycles, identifiable = _cycles(result)
    if not result.trades or any(t.side == "BUY" and t.tier is None for t in result.trades):
        finding = _finding("scale_in_cycle_attribution", S.NOT_EVALUABLE, V.WARNING,
                           "No filled entry records with tiers are available to establish scale-in cycle attribution.")
        return ScaleInDiagnostic(S.NOT_EVALUABLE, (finding,), None, len(cycles), None, None,
                                 None, None, None, None, None, len(open_cycles), None)
    if not identifiable:
        finding = _finding("scale_in_cycle_attribution", S.NOT_EVALUABLE, V.WARNING,
                           "Position history cannot identify all completed cycles from the available records.")
        return ScaleInDiagnostic(S.NOT_EVALUABLE, (finding,), None, len(cycles), None, None,
                                 None, None, None, None, None, len(open_cycles), None)
    entries = [len(c["entries"]) for c in cycles]
    multi = [c for c in cycles if len(c["entries"]) > 1]
    single = [c for c in cycles if len(c["entries"]) == 1]
    open_scale_fills = sum(max(0, len(c["entries"]) - 1) for c in open_cycles)
    scale_fills = sum(max(0, n - 1) for n in entries) + open_scale_fills
    multi_notional = _safe_sum(t.notional for c in multi for t in c["trades"]
                               if _finite(t.notional)) if all(_finite(t.notional)
                               for c in multi for t in c["trades"]) else None
    single_pnl = sum(c["pnl"] for c in single)
    multi_pnl = sum(c["pnl"] for c in multi)
    if not all(_finite(value) for value in (multi_notional, single_pnl, multi_pnl)):
        finding = _finding("scale_in_cycle_attribution", S.NOT_EVALUABLE, V.WARNING,
                           "Non-finite cycle notional or realized P&L prevents scale-in attribution.")
        return ScaleInDiagnostic(S.NOT_EVALUABLE, (finding,), scale_fills, len(cycles), len(multi),
                                 len(multi) / len(cycles) * 100 if cycles else None,
                                 sum(entries) / len(entries) if entries else None,
                                 max(entries) if entries else None, None, None, None, len(open_cycles), None)
    finding = _finding("scale_in_cycle_attribution", S.PASS, V.INFO,
                       "Entry fills and completed cycles are grouped by asset and confirmed flat position state; this is descriptive attribution, not a no-scale-in counterfactual.",
                       len(cycles), "completed cycles identifiable")
    return ScaleInDiagnostic(S.PASS, (finding,), scale_fills, len(cycles), len(multi),
                             len(multi) / len(cycles) * 100 if cycles else None,
                             sum(entries) / len(entries) if entries else None,
                             max(entries) if entries else None, multi_notional,
                             multi_pnl, single_pnl, len(open_cycles), None)


def exposure_diagnostic(result: BacktestResult, cfg: ValidationConfig,
                        scale: ScaleInDiagnostic) -> ExposureDiagnostic:
    initial_raw = getattr(result.configuration, "initial_capital", None)
    initial = float(initial_raw) if _finite(initial_raw) and initial_raw > 0 else 0.0
    fills_by_asset = defaultdict(list)
    pnl_by_asset = defaultdict(float)
    for record in result.orders:
        fill = record.fill
        if fill is not None:
            fills_by_asset[fill.asset].append(fill)
    for trade in result.trades:
        if trade.side == "SELL":
            pnl_by_asset[trade.asset] += trade.realized_pnl if _finite(trade.realized_pnl) else math.nan
    exposure_by_asset = defaultdict(list)
    for pos in result.position_history:
        exposure_by_asset[pos.asset].append(pos.quantity * pos.average_entry_price
                                            if _finite(pos.quantity) and _finite(pos.average_entry_price) else math.nan)
    assets = sorted(set(fills_by_asset) | set(pnl_by_asset) | set(exposure_by_asset))
    notional_by_asset = {asset: _safe_sum(f.quantity * f.fill_price for f in fills_by_asset[asset])
                         for asset in assets}
    pnl_abs_total = sum(abs(value) for value in pnl_by_asset.values() if _finite(value))
    pnl_net_total = sum(value for value in pnl_by_asset.values() if _finite(value))
    fill_total = sum(len(v) for v in fills_by_asset.values())
    notional_total = sum(v for v in notional_by_asset.values() if v is not None)
    avg_exposure = {asset: sum(exposure_by_asset[asset]) / len(exposure_by_asset[asset])
                    if exposure_by_asset[asset] and all(_finite(x) for x in exposure_by_asset[asset]) else None
                    for asset in assets}
    exposure_total = sum(v for v in avg_exposure.values() if v is not None)
    asset_rows = tuple(AssetConcentration(
        asset, pnl_by_asset[asset] if _finite(pnl_by_asset[asset]) else None,
        pnl_by_asset[asset] / pnl_net_total if pnl_net_total and _finite(pnl_by_asset[asset]) else None,
        abs(pnl_by_asset[asset]) / pnl_abs_total if pnl_abs_total and _finite(pnl_by_asset[asset]) else None,
        len(fills_by_asset[asset]), len(fills_by_asset[asset]) / fill_total if fill_total else None,
        notional_by_asset[asset],
        notional_by_asset[asset] / notional_total if notional_total and notional_by_asset[asset] is not None else None,
        avg_exposure[asset], avg_exposure[asset] / exposure_total if exposure_total and avg_exposure[asset] is not None else None,
    ) for asset in assets)
    max_pnl = max((row.realized_pnl_abs_share for row in asset_rows if row.realized_pnl_abs_share is not None), default=None)
    max_fill = max((row.fill_share for row in asset_rows if row.fill_share is not None), default=None)
    max_notional = max((row.traded_notional_share for row in asset_rows if row.traded_notional_share is not None), default=None)
    max_exposure = max((row.exposure_share for row in asset_rows if row.exposure_share is not None), default=None)
    findings = []
    for name, share, label in (("realized_pnl_concentration", max_pnl, "realized P&L"),
                               ("fill_concentration", max_fill, "fills"),
                               ("traded_notional_concentration", max_notional, "traded notional"),
                               ("average_exposure_concentration", max_exposure, "cost-basis exposure")):
        status = S.WARNING if share is not None and share >= cfg.concentration_warning_share else S.PASS
        findings.append(_finding(name, status, V.WARNING if status == S.WARNING else V.INFO,
                                 f"One asset represents {share:.1%} of absolute {label}; investigate dependence, without treating concentration as intrinsically adverse."
                                 if status == S.WARNING else f"No single-asset {label} concentration crossed the configured descriptive threshold.",
                                 share, cfg.concentration_warning_share))
    completed = scale.completed_cycles or 0
    if completed <= cfg.insufficient_cycles:
        findings.append(_finding("few_completed_cycles", S.WARNING, V.WARNING,
                                 "Results rely on very few completed cycles; this is a descriptive sample-size warning, not a significance test.",
                                 completed, f"> {cfg.insufficient_cycles}"))
    gross_to_initial = [p.gross_exposure * p.equity / initial for p in result.portfolio_curve
                        if initial > 0 and _finite(p.gross_exposure) and _finite(p.equity)]
    max_gross_to_initial = max(gross_to_initial, default=None)
    if max_gross_to_initial is not None and max_gross_to_initial > cfg.extreme_gross_to_initial_capital:
        findings.append(_finding("gross_exposure_relative_to_initial_capital", S.WARNING, V.WARNING,
                                 "Peak gross marked exposure exceeds the configured descriptive multiple of initial capital.",
                                 max_gross_to_initial, cfg.extreme_gross_to_initial_capital))
    else:
        findings.append(_finding("gross_exposure_relative_to_initial_capital", S.PASS, V.INFO,
                                 "Peak gross marked exposure did not exceed the configured descriptive multiple of initial capital.",
                                 max_gross_to_initial, cfg.extreme_gross_to_initial_capital))
    total = len(result.portfolio_curve)
    invested = sum(_finite(p.market_value) and p.market_value != 0 for p in result.portfolio_curve)
    good = all(_finite(getattr(p, name, None)) for p in result.portfolio_curve
               for name in ("gross_exposure", "net_exposure", "market_value"))
    gross = [p.gross_exposure for p in result.portfolio_curve if _finite(p.gross_exposure)]
    net = [p.net_exposure for p in result.portfolio_curve if _finite(p.net_exposure)]
    return ExposureDiagnostic(tuple(findings), float(np.mean(gross)) if gross and good else None,
                              max(gross) if gross and good else None,
                              float(np.mean(net)) if net and good else None,
                              max(net) if net and good else None,
                              invested / total * 100 if total and good else None, asset_rows,
                              max_pnl, max_fill, max_notional, max_exposure)


def sample_size_diagnostic(result: BacktestResult, scale: ScaleInDiagnostic,
                           cfg: ValidationConfig) -> SampleSizeDiagnostic:
    cycles, _, _ = _cycles(result)
    fill_count = sum(record.fill is not None for record in result.orders)
    if len(cycles) <= cfg.insufficient_cycles or fill_count < cfg.insufficient_fills:
        label = SampleLabel.INSUFFICIENT_SAMPLE
    elif len(cycles) <= cfg.limited_cycles:
        label = SampleLabel.LIMITED_SAMPLE
    else:
        label = SampleLabel.ADEQUATE_FOR_DESCRIPTIVE_ANALYSIS
    status = S.WARNING if label != SampleLabel.ADEQUATE_FOR_DESCRIPTIVE_ANALYSIS else S.PASS
    finding = _finding("descriptive_sample_size", status, V.WARNING if status == S.WARNING else V.INFO,
                       f"Sample classified {label.value}; this is a configurable descriptive warning, not a statistical power or significance test.",
                       len(cycles), label.value)
    winners = sum(c["pnl"] > 0 for c in cycles if _finite(c["pnl"]))
    losers = sum(c["pnl"] < 0 for c in cycles if _finite(c["pnl"]))
    return SampleSizeDiagnostic((finding,), label, len(result.portfolio_curve), fill_count,
                                len(cycles), winners, losers, scale.multi_entry_cycles)


def degeneracy_diagnostic(result: BacktestResult, cfg: ValidationConfig,
                          scale: ScaleInDiagnostic, exposure: ExposureDiagnostic) -> Section:
    findings = []
    fills = [r.fill for r in result.orders if r.fill is not None]
    buy_count = sum(f.side == "BUY" for f in fills)
    sell_count = sum(f.side == "SELL" for f in fills)
    if not fills:
        findings.append(_finding("no_trades", S.WARNING, V.WARNING, "No actual fills were recorded."))
    else:
        findings.append(_finding("no_trades", S.PASS, V.INFO, "Actual fills are present.", len(fills), "> 0"))
    if buy_count and not sell_count:
        findings.append(_finding("buys_without_exits", S.WARNING, V.WARNING,
                                 "Only BUY fills are recorded; no completed exit behavior can be assessed."))
    else:
        findings.append(_finding("buys_without_exits", S.PASS, V.INFO, "SELL fills are present or no BUY-only condition applies."))
    if result.portfolio_curve and result.trades and len({p.equity for p in result.portfolio_curve}) == 1:
        findings.append(_finding("unchanged_equity_with_fills", S.WARNING, V.WARNING,
                                 "Equity never changed despite recorded fills; inspect marks, cash, and accounting.",
                                 len(result.trades), "equity changes or no fills"))
    else:
        findings.append(_finding("unchanged_equity_with_fills", S.PASS, V.INFO,
                                 "No unchanged-equity-with-fills condition was observed."))
    gross_values = {p.gross_exposure for p in result.portfolio_curve if _finite(p.gross_exposure)}
    equities = [p.equity for p in result.portfolio_curve]
    if len(equities) >= 3 and all(_finite(value) and value > 0 for value in equities):
        daily = np.diff(np.asarray(equities, dtype=float)) / np.asarray(equities[:-1], dtype=float)
        volatility = float(np.std(daily, ddof=1) * math.sqrt(252)) if len(daily) > 1 else None
    else:
        volatility = None
    if volatility == 0 and len(gross_values) > 1:
        findings.append(_finding("zero_volatility_varying_exposure", S.WARNING, V.WARNING,
                                 "Equity volatility is zero while recorded gross exposure varies."))
    else:
        findings.append(_finding("zero_volatility_varying_exposure", S.PASS, V.INFO,
                                 "No zero-volatility and varying-exposure contradiction was observed."))
    cycles, _, _ = _cycles(result)
    if cycles and all(_finite(c["pnl"]) for c in cycles):
        pnl_abs = [abs(c["pnl"]) for c in cycles]
        total_abs = sum(pnl_abs)
        max_cycle_share = max(pnl_abs) / total_abs if total_abs else None
    else:
        max_cycle_share = None
    if max_cycle_share is not None and max_cycle_share >= cfg.concentration_warning_share:
        findings.append(_finding("pnl_concentrated_in_one_cycle", S.WARNING, V.WARNING,
                                 "One completed cycle represents a dominant share of absolute cycle P&L; interpret descriptive performance cautiously.",
                                 max_cycle_share, cfg.concentration_warning_share))
    else:
        findings.append(_finding("pnl_concentrated_in_one_cycle", S.PASS, V.INFO,
                                 "No single completed cycle crossed the configured descriptive concentration threshold.",
                                 max_cycle_share, cfg.concentration_warning_share))
    fingerprints = [(f.asset, f.side, f.quantity, f.fill_price, f.fill_timestamp)
                    for r in result.orders if r.fill is not None for f in (r.fill,)]
    duplicate_fills = len(fingerprints) - len(set(fingerprints))
    findings.append(_finding("identical_fill_fingerprints", S.WARNING if duplicate_fills else S.PASS,
                             V.WARNING if duplicate_fills else V.INFO,
                             "Repeated identical fill fingerprints found; review for duplicate events (identical fills may still be legitimate)."
                             if duplicate_fills else "No repeated identical fill fingerprints found.", duplicate_fills, 0))
    summaries = {s.asset: s for s in result.per_asset}
    summary_errors = []
    cycles_by_asset, open_cycles, _ = _cycles(result)
    for asset, summary in summaries.items():
        actual_fills = sum(1 for r in result.orders if r.fill is not None and r.fill.asset == asset)
        actual_cycles = sum(1 for c in cycles_by_asset if c["asset"] == asset) + sum(
            1 for c in open_cycles if c["asset"] == asset)
        if summary.fills != actual_fills or summary.cycles != actual_cycles:
            summary_errors.append(asset)
    findings.append(_finding("per_asset_summary_consistency", S.WARNING if summary_errors else S.PASS,
                             V.WARNING if summary_errors else V.INFO,
                             "Per-asset summary fill counts disagree with actual fills." if summary_errors
                             else "Per-asset summary fill counts match actual fills.", len(summary_errors), 0))
    open_positions = [p for p in result.position_history if result.portfolio_curve and
                      p.timestamp == result.portfolio_curve[-1].timestamp and p.quantity > 0]
    if open_positions:
        aggregate_unrealized = result.portfolio_curve[-1].unrealized_pnl
        if _finite(aggregate_unrealized) and abs(aggregate_unrealized) <= cfg.absolute_tolerance:
            findings.append(_finding("open_position_without_unrealized_contribution", S.WARNING, V.WARNING,
                                     "Final open positions have zero aggregate unrealized P&L; this may be valid at unchanged marks but merits review.",
                                     aggregate_unrealized, "inspect final per-asset marks"))
        findings.append(_finding("unrealized_contribution_for_open_positions", S.NOT_EVALUABLE, V.WARNING,
                                 "Final positions remain open. Per-asset closing marks are not included in position_history, so their unrealized P&L cannot be independently reconciled from this result.",
                                 len(open_positions), "requires per-asset final marks"))
    else:
        findings.append(_finding("unrealized_contribution_for_open_positions", S.PASS, V.INFO,
                                 "No final open positions require an unrealized P&L reconciliation."))
    return Section(_status(findings), tuple(findings), (
        Metric("open_position_assets", len(open_positions), "assets"),
        Metric("maximum_cycle_absolute_pnl_share", max_cycle_share, "fraction"),
    ))


def _status(findings):
    if any(f.status == S.FAIL for f in findings):
        return S.FAIL
    if any(f.status == S.WARNING for f in findings):
        return S.WARNING
    if findings and all(f.status == S.NOT_EVALUABLE for f in findings):
        return S.NOT_EVALUABLE
    if any(f.status == S.NOT_EVALUABLE for f in findings):
        return S.WARNING
    return S.PASS
