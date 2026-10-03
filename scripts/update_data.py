import argparse

from src.data.config import load_assets_config
from src.data.engine import DataEngine


def run(start: str | None = None, end: str | None = None) -> None:
    assets, _ = load_assets_config()
    engine = DataEngine()
    for ticker, asset in assets.items():
        if not asset.enabled:
            continue
        frame = engine.update(ticker, start=start, end=end)
        print(f"Updated {ticker}: {len(frame)} validated rows, {frame.index[0]} through {frame.index[-1]}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download or incrementally update configured market data.")
    parser.add_argument("--start", help="Inclusive start date (YYYY-MM-DD); defaults to configured start or incremental next date.")
    parser.add_argument("--end", help="Exclusive end date (YYYY-MM-DD); defaults to current UTC date.")
    args = parser.parse_args()
    run(start=args.start, end=args.end)


if __name__ == "__main__":
    main()
