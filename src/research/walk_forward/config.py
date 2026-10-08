"""Temporal-only configuration for walk-forward evaluation."""
from dataclasses import dataclass
from pathlib import Path
import yaml
from src.data.config import REPOSITORY_ROOT

DEFAULT_WALK_FORWARD_CONFIG = REPOSITORY_ROOT / "config" / "walk_forward.yaml"

@dataclass(frozen=True)
class WalkForwardConfig:
    mode: str = "expanding"
    train_bars: int = 504
    validation_bars: int = 126
    test_bars: int = 63
    step_bars: int = 63
    embargo_bars: int = 0
    minimum_train_bars: int = 252
    minimum_validation_bars: int = 63
    minimum_test_bars: int = 20
    warmup_bars: int = 252
    reset_state_each_test_window: bool = True
    require_non_overlapping_tests: bool = True
    aggregate_oos: bool = True

    def __post_init__(self):
        if self.mode not in {"expanding", "rolling"}:
            raise ValueError("mode must be 'expanding' or 'rolling'.")
        for name in ("train_bars", "validation_bars", "test_bars", "step_bars",
                     "minimum_train_bars", "minimum_validation_bars", "minimum_test_bars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        for name in ("embargo_bars", "warmup_bars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        if self.minimum_train_bars > self.train_bars:
            raise ValueError("minimum_train_bars cannot exceed train_bars.")
        if self.minimum_validation_bars > self.validation_bars:
            raise ValueError("minimum_validation_bars cannot exceed validation_bars.")
        if self.minimum_test_bars > self.test_bars:
            raise ValueError("minimum_test_bars cannot exceed test_bars.")
        if type(self.reset_state_each_test_window) is not bool or not self.reset_state_each_test_window:
            raise ValueError("Independent OOS windows require reset_state_each_test_window=true.")
        if type(self.require_non_overlapping_tests) is not bool or type(self.aggregate_oos) is not bool:
            raise ValueError("Boolean walk-forward settings must be true or false.")
        if self.require_non_overlapping_tests and self.step_bars < self.test_bars:
            raise ValueError("step_bars must be >= test_bars when non-overlapping tests are required.")

def load_walk_forward_config(path: str | Path = DEFAULT_WALK_FORWARD_CONFIG):
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        section = raw["walk_forward"]
        if not isinstance(section, dict):
            raise ValueError("walk_forward must be a mapping.")
        return WalkForwardConfig(**section)
    except (OSError, yaml.YAMLError, TypeError, KeyError) as exc:
        raise ValueError(f"Invalid walk-forward configuration at {config_path}: {exc}") from exc
