"""Stable IDs and metric comparisons, with no ranking or optimization."""
import hashlib
import json

METRICS = ("final_equity", "total_return", "cagr", "annualized_volatility",
           "sharpe_ratio", "sortino_ratio", "maximum_drawdown",
           "filled_trades", "completed_cycles", "multi_entry_cycles",
           "total_transaction_costs", "average_gross_exposure",
           "maximum_gross_exposure", "turnover_notional")

def experiment_id(kind, component, value, baseline_hash):
    raw = json.dumps([kind, component, value, baseline_hash], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]

def metric_deltas(base, run):
    from .engine import extract_metrics
    left, right = extract_metrics(base), extract_metrics(run)
    output = []
    for key in METRICS:
        a, b = left.get(key), right.get(key)
        absolute = None if a is None or b is None else float(b) - float(a)
        relative = None if absolute is None or float(a) == 0 else absolute / abs(float(a))
        from .models import ResearchMetricDelta
        output.append(ResearchMetricDelta(key, a, b, absolute, relative))
    return tuple(output)
