"""Walk-forward orchestration over the canonical sequential backtest."""
from dataclasses import fields, is_dataclass, replace
from datetime import date, datetime
from enum import Enum
import hashlib
from pathlib import Path
from typing import Mapping

import pandas as pd

from src.backtest.engine import run_backtest
from src.analytics import run_analytics
from src.data.config import REPOSITORY_ROOT
from src.research.engine import CONFIG_FILES, baseline_configuration_hash
from src.validation import canonical_json, run_validation
from .aggregation import aggregate_oos
from .config import DEFAULT_WALK_FORWARD_CONFIG, WalkForwardConfig, load_walk_forward_config
from .models import WalkForwardRunResult, WalkForwardWindowResult
from .splits import build_windows, ordered_timeline

DEFAULT_REPORT_PATH = REPOSITORY_ROOT / "data" / "processed" / "walk_forward.json"

def _normalize_data(data):
    if not isinstance(data, Mapping):
        raise TypeError("data must map asset identifiers to OHLCV DataFrames.")
    result = {}
    for asset, frame in sorted(data.items(), key=lambda pair: str(pair[0])):
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{asset} data must be a pandas DataFrame.")
        normalized_asset = str(asset).strip().upper()
        normalized_asset = "BTC" if normalized_asset == "BTC-USD" else normalized_asset
        if normalized_asset in result:
            raise ValueError(f"Duplicate input for normalized asset {normalized_asset}.")
        if frame.empty:
            continue
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise ValueError(f"{asset} timestamps must be timezone-aware DatetimeIndex values.")
        normalized = frame.copy()
        normalized.index = normalized.index.tz_convert("UTC")
        if normalized.index.has_duplicates:
            raise ValueError(f"{asset} timestamps are duplicated after UTC normalization.")
        if not normalized.index.is_monotonic_increasing:
            raise ValueError(f"{asset} timestamps must be chronological.")
        result[normalized_asset] = normalized
    return result

def dataset_fingerprint(data):
    digest = hashlib.sha256()
    for asset, frame in sorted(data.items()):
        digest.update(asset.encode("utf-8")); digest.update(b"\0")
        digest.update(canonical_json({"columns": list(frame.columns),
                                     "dtypes": [str(dtype) for dtype in frame.dtypes],
                                     "index": [stamp.isoformat() for stamp in frame.index]}).encode("utf-8"))
        values = pd.util.hash_pandas_object(frame, index=False, categorize=True).to_numpy().tobytes()
        digest.update(values); digest.update(b"\0")
    return digest.hexdigest()

def _findings(validation):
    warnings, errors = [], []
    for field in fields(validation):
        section = getattr(validation, field.name)
        findings = getattr(section, "findings", ())
        for item in findings:
            status = getattr(item.status, "value", item.status)
            message = f"{field.name}.{item.check_name}: {item.message}"
            if status == "FAIL" or getattr(item.severity, "value", item.severity) in {"ERROR", "CRITICAL"}:
                errors.append(message)
            elif status in {"WARNING", "NOT_EVALUABLE"}:
                warnings.append(message)
    return tuple(warnings), tuple(errors)

def _jsonable(value):
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value

def _configuration_snapshot():
    return {name: (REPOSITORY_ROOT / "config" / name).read_bytes() for name in CONFIG_FILES}

def _run_hash_payload(config_hash, temporal_config, data_hash, windows, aggregate, consistent):
    return {
        "configuration_hash": config_hash, "dataset_fingerprint": data_hash,
        "walk_forward_config": temporal_config,
        "windows": windows, "aggregate_oos": aggregate,
        "configuration_consistent": consistent,
    }

def run_walk_forward(data, *, config: WalkForwardConfig | None = None,
                     config_path: str | Path = DEFAULT_WALK_FORWARD_CONFIG,
                     report_path: str | Path | None = None):
    """Evaluate fixed production strategy independently on every chronological test window."""
    settings = config or load_walk_forward_config(config_path)
    normalized = _normalize_data(data)
    timeline = ordered_timeline(normalized)
    expected_config_hash = baseline_configuration_hash()
    production_bytes = _configuration_snapshot()
    windows = build_windows(timeline, settings, expected_config_hash)
    rows = []

    for window in windows:
        errors = []
        if baseline_configuration_hash() != expected_config_hash:
            errors.append("Production configuration changed before this window.")
        lower = pd.Timestamp(window.warmup_start)
        upper = pd.Timestamp(window.test_end)
        context = {asset: frame.loc[(frame.index >= lower) & (frame.index <= upper)].copy()
                   for asset, frame in normalized.items()}
        result = run_backtest(context, evaluation_start=pd.Timestamp(window.test_start),
                              evaluation_end=pd.Timestamp(window.test_end))
        analytics = run_analytics(result)
        validation = run_validation(result)
        warnings, validation_errors = _findings(validation)
        errors.extend(validation_errors)
        if not result.portfolio_curve:
            errors.append("Backtest produced no OOS observations.")
        if baseline_configuration_hash() != expected_config_hash:
            errors.append("Production configuration changed during this window.")
        overall = getattr(validation.overall_status, "value", validation.overall_status)
        if overall == "FAIL":
            errors.append("M12 Validation reported overall FAIL.")
        status = "INVALID" if errors or overall == "FAIL" else (
            "NOT_EVALUABLE" if overall == "NOT_EVALUABLE" or not result.portfolio_curve else "COMPLETED")
        rows.append(WalkForwardWindowResult(
            window, status, result, analytics, validation, warnings, tuple(errors),
            pending_orders=result.pending_orders,
        ))

    final_snapshot = _configuration_snapshot()
    configuration_consistent = (
        production_bytes == final_snapshot and
        all(row.window.configuration_hash == expected_config_hash for row in rows)
    )
    if not configuration_consistent:
        rows = [replace(row, status="INVALID",
                        errors=row.errors + ("Production configuration hash/bytes changed during the run.",))
                for row in rows]

    aggregate = aggregate_oos(rows, timeline, calculate=settings.aggregate_oos)
    first_oos = min((row.window.test_start for row in rows), default=None)
    last_oos = max((row.window.test_end for row in rows), default=None)
    invalid = tuple(row.window.window_id for row in rows if row.status == "INVALID")
    data_hash = dataset_fingerprint(normalized)
    payload = _run_hash_payload(expected_config_hash, settings, data_hash, tuple(rows),
                                aggregate, configuration_consistent)
    run_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    result = WalkForwardRunResult(
        tuple(rows), aggregate, expected_config_hash, settings, data_hash,
        timeline[0].to_pydatetime(), timeline[-1].to_pydatetime(),
        first_oos, last_oos, invalid, len(rows), sum(row.status == "COMPLETED" for row in rows),
        aggregate.total_oos_observations, aggregate.duplicate_oos_observations,
        configuration_consistent, run_hash, "",
    )
    result = replace(result, report_json=canonical_json(result))
    target = Path(report_path) if report_path is not None else DEFAULT_REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.report_json + "\n", encoding="utf-8")
    return result
