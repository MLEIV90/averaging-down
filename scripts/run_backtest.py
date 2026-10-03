import json

from src.backtest.engine import run_backtest
from src.backtest.metrics import calculate_metrics
from src.data.config import REPOSITORY_ROOT, load_assets_config
from src.data.engine import DataEngine
from src.features.engine import FeatureEngine


def run():
    configured_assets, _ = load_assets_config()
    data_engine = DataEngine()
    feature_engine = FeatureEngine()
    data_dict = {}
    output_dir = REPOSITORY_ROOT / "data" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)

    for ticker, config in configured_assets.items():
        if not config.enabled:
            continue
        frame = data_engine.load_or_download(ticker, allow_download=True)
        data_dict[ticker] = feature_engine.compute(frame).rename(columns={"close": "Close"})

    equity_curve = run_backtest(data_dict, feature_engine.config)
    if equity_curve.empty:
        raise RuntimeError("Backtest engine returned an empty equity curve.")

    metrics = calculate_metrics(equity_curve)
    safe_metrics = {key: float(value) for key, value in metrics.items()}
    (output_dir / "backtest_metrics.json").write_text(json.dumps(safe_metrics, indent=2), encoding="utf-8")
    equity_curve.to_csv(output_dir / "equity_curve.csv", header=["Equity"], index_label="Date")
    print("Backtest completed; metrics and equity curve exported.")


if __name__ == "__main__":
    run()
