"""Central configuration for quantitative feature periods and conventions."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.data.config import REPOSITORY_ROOT

DEFAULT_FEATURE_CONFIG = REPOSITORY_ROOT / "config" / "features.yaml"


@dataclass(frozen=True)
class FeatureConfig:
    ema_fast: int = 20
    ema_medium: int = 50
    ema_slow: int = 200
    atr_period: int = 14
    atr_method: str = "sma_true_range"
    rsi_fast_period: int = 2
    rsi_period: int = 14
    realized_vol_period: int = 20
    realized_vol_windows: tuple[int, ...] = (10, 20, 60)
    realized_vol_return_method: str = "log"
    annualization: float = 252
    slope_lookback: int = 5
    slope_method: str = "difference"


def load_feature_config(path: str | Path = DEFAULT_FEATURE_CONFIG) -> FeatureConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read feature configuration at {config_path}: {exc}") from exc
    values = raw.get("features", {})
    if not isinstance(values, dict):
        raise ValueError("features.yaml must define a 'features' mapping.")
    if "realized_vol_windows" in values:
        values["realized_vol_windows"] = tuple(values["realized_vol_windows"])
    try:
        config = FeatureConfig(**values)
    except TypeError as exc:
        raise ValueError(f"Invalid feature configuration: {exc}") from exc
    # Validate shared numeric parameters when configuration is loaded.
    for name in ("ema_fast", "ema_medium", "ema_slow", "atr_period", "rsi_fast_period", "rsi_period", "realized_vol_period", "slope_lookback"):
        if isinstance(getattr(config, name), bool) or not isinstance(getattr(config, name), int) or getattr(config, name) <= 0:
            raise ValueError(f"{name} must be a positive integer.")
    if not config.realized_vol_windows or any(isinstance(w, bool) or not isinstance(w, int) or w <= 0 for w in config.realized_vol_windows):
        raise ValueError("realized_vol_windows must contain positive integers.")
    if isinstance(config.annualization, bool) or not isinstance(config.annualization, (int, float)) or config.annualization <= 0:
        raise ValueError("annualization must be positive.")
    if config.atr_method not in {"sma_true_range", "wilder"}:
        raise ValueError("atr_method must be 'sma_true_range' or 'wilder'.")
    if config.realized_vol_return_method not in {"log", "simple"}:
        raise ValueError("realized_vol_return_method must be 'log' or 'simple'.")
    if config.slope_method not in {"difference", "percent"}:
        raise ValueError("slope_method must be 'difference' or 'percent'.")
    return config
