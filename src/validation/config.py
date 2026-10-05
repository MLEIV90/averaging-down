from dataclasses import dataclass
from pathlib import Path
import math

import yaml

from src.data.config import REPOSITORY_ROOT

DEFAULT_VALIDATION_CONFIG = REPOSITORY_ROOT / "config" / "validation.yaml"


@dataclass(frozen=True)
class ValidationConfig:
    absolute_tolerance: float = 1e-8
    relative_tolerance: float = 1e-10
    insufficient_cycles: int = 5
    limited_cycles: int = 20
    insufficient_fills: int = 10
    concentration_warning_share: float = 0.8
    extreme_gross_to_initial_capital: float = 1.0

    def __post_init__(self):
        for name in ("absolute_tolerance", "relative_tolerance", "concentration_warning_share",
                     "extreme_gross_to_initial_capital"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative.")
        if self.concentration_warning_share > 1:
            raise ValueError("concentration_warning_share cannot exceed 1.")
        for name in ("insufficient_cycles", "limited_cycles", "insufficient_fills"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        if self.limited_cycles < self.insufficient_cycles:
            raise ValueError("limited_cycles must be >= insufficient_cycles.")


def load_validation_config(path: str | Path = DEFAULT_VALIDATION_CONFIG) -> ValidationConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return ValidationConfig(**raw["validation"])
    except (OSError, yaml.YAMLError, TypeError, KeyError) as exc:
        raise ValueError(f"Invalid validation configuration at {config_path}: {exc}") from exc
