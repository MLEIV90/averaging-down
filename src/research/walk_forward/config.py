"""Walk-forward configuration loading."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.data.config import REPOSITORY_ROOT

from .models import WalkForwardConfig


DEFAULT_WALK_FORWARD_CONFIG = (
    REPOSITORY_ROOT / "config" / "walk_forward.yaml"
)


def load_walk_forward_config(
    path: str | Path = DEFAULT_WALK_FORWARD_CONFIG,
) -> WalkForwardConfig:
    """Load deterministic walk-forward configuration from YAML."""
    config_path = Path(path)

    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path

    try:
        raw = yaml.safe_load(
            config_path.read_text(encoding="utf-8")
        )

        if not isinstance(raw, dict):
            raise ValueError("Configuration root must be a mapping.")

        section = raw["walk_forward"]

        if not isinstance(section, dict):
            raise ValueError(
                "walk_forward configuration must be a mapping."
            )

    except (OSError, yaml.YAMLError, TypeError, KeyError) as exc:
        raise ValueError(
            f"Invalid walk-forward configuration at "
            f"{config_path}: {exc}"
        ) from exc

    return WalkForwardConfig(
        train_days=int(section["train_days"]),
        validation_days=int(section["validation_days"]),
        test_days=int(section["test_days"]),
        step_days=int(section["step_days"]),
        warmup_days=int(section["warmup_days"]),
        embargo_days=int(section["embargo_days"]),
        expanding=bool(section["expanding"]),
        min_windows=int(section["min_windows"]),
    )