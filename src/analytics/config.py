from dataclasses import dataclass
from pathlib import Path

import yaml

from src.data.config import REPOSITORY_ROOT

DEFAULT_ANALYTICS_CONFIG = REPOSITORY_ROOT / "config" / "analytics.yaml"


@dataclass(frozen=True)
class AnalyticsConfig:
    annualization: int = 252
    risk_free_rate: float = 0.0
    minimum_observations: int = 2

    def __post_init__(self):
        if isinstance(self.annualization, bool) or not isinstance(self.annualization, int) or self.annualization <= 0:
            raise ValueError("annualization must be a positive integer.")
        if isinstance(self.minimum_observations, bool) or not isinstance(self.minimum_observations, int) or self.minimum_observations < 2:
            raise ValueError("minimum_observations must be an integer >= 2.")
        if isinstance(self.risk_free_rate, bool) or not isinstance(self.risk_free_rate, (int, float)) or not float("-inf") < self.risk_free_rate < float("inf"):
            raise ValueError("risk_free_rate must be finite.")


def load_analytics_config(path: str | Path = DEFAULT_ANALYTICS_CONFIG) -> AnalyticsConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        values = yaml.safe_load(config_path.read_text(encoding="utf-8"))["analytics"]
        return AnalyticsConfig(**values)
    except (OSError, yaml.YAMLError, TypeError, KeyError) as exc:
        raise ValueError(f"Invalid analytics configuration at {config_path}: {exc}") from exc
