from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "config" / "assets.yaml"


class InvalidDataConfiguration(ValueError):
    pass


@dataclass(frozen=True)
class AssetDataConfig:
    ticker: str
    market_timezone: str
    asset_class: str
    enabled: bool = True
    interval: str = "1d"
    source_interval: str = "1d"
    resample_cutoff_utc: str | None = None
    adjusted: bool = False
    default_start: str | None = None


def load_assets_config(path: str | Path = DEFAULT_CONFIG_PATH) -> tuple[dict[str, AssetDataConfig], dict[str, Any]]:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = REPOSITORY_ROOT / config_path
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise InvalidDataConfiguration(f"Cannot read asset configuration at {config_path}: {exc}") from exc
    raw_assets = raw.get("assets")
    if not isinstance(raw_assets, dict):
        raise InvalidDataConfiguration("assets.yaml must define an 'assets' mapping.")
    defaults = raw.get("data_defaults", {}) or {}
    result: dict[str, AssetDataConfig] = {}
    for ticker, item in raw_assets.items():
        if not isinstance(item, dict):
            raise InvalidDataConfiguration(f"Configuration for {ticker!r} must be a mapping.")
        source_interval = str(item.get("source_interval", "1d"))
        cutoff = item.get("daily_close_utc")
        if cutoff is None and item.get("resampling_cutoff") == "16:00 EST":
            cutoff = "21:00"
        result[ticker] = AssetDataConfig(
            ticker=ticker,
            market_timezone=str(item.get("timezone", "UTC")),
            asset_class=str(item.get("asset_class", "unknown")),
            enabled=bool(item.get("enabled", True)),
            interval=str(item.get("interval", "1d")),
            source_interval=source_interval,
            resample_cutoff_utc=str(cutoff) if cutoff else None,
            adjusted=bool(item.get("adjusted", defaults.get("adjusted", False))),
            default_start=item.get("start", defaults.get("start")),
        )
    return result, defaults


def get_asset_config(ticker: str, path: str | Path = DEFAULT_CONFIG_PATH) -> AssetDataConfig:
    assets, _ = load_assets_config(path)
    try:
        return assets[ticker]
    except KeyError as exc:
        raise InvalidDataConfiguration(f"Asset {ticker!r} is not configured in assets.yaml.") from exc
