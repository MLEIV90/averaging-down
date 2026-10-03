# Quant Strategy Engine — SPY / BTC / GLD

Local EOD quantitative research prototype. The repository contains a Streamlit interface, standalone data and EOD scripts, and a simplified historical backtest. The modules under `src/` are not all connected to these workflows; see `RESEARCH_LOG.md` for the baseline findings and unresolved research decisions.

## Environment

Python 3.10 or newer is recommended. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS/Linux, activate with `source .venv/bin/activate`.

## Run the local UI

From the repository root:

```text
python -m streamlit run app/main.py
```

Streamlit serves the app at `http://localhost:8501` by default. The Dashboard reads normalized, validated local data through `src/data/`. Populate or update the local market store with `python -m scripts.update_data` from the repository root; this operation requires network access.

## Data and EOD scripts

From the repository root:

```text
python -m scripts.update_data
python -m scripts.run_eod
```

`update_data` downloads the enabled assets configured in `config/assets.yaml`, persists provider data under `data/raw/`, and saves normalized validated daily data plus JSON provenance under `data/processed/`. Subsequent calls request only data after the local latest date, with an overlap for BTC aggregation. When a legacy cache has no provenance, the first update rebuilds from the configured start rather than mixing unknown and new source conventions. The BTC hourly request follows the repository's existing 21:00 UTC convention while hourly history is available; older requests fall back to provider daily bars, and metadata records the effective interval. `run_eod` uses the validated local store and downloads through the same Data Engine only when local data is absent. It writes signals and portfolio state under `data/processed/`.

Data and configuration paths used by the Data Engine resolve from the repository location. Data and generated outputs are ignored by Git.

## Run the backtest

From the repository root:

```text
python -m scripts.run_backtest
```

The runner loads validated data from the Data Engine, downloading only if no local source data is available. It writes `data/processed/backtest_metrics.json` and `data/processed/equity_curve.csv`, which the Backtest page reads. The current engine is a simplified vectorized weight rule, not a simulation of the EOD scale-in state machine. It does not currently model transaction costs, slippage, cash balances, or individual trades. Treat its output as exploratory, not as a validated strategy result.

## Tests

From the repository root:

```text
python -m pytest
```

By default, pytest runs deterministic local unit tests. The separately marked Yahoo Finance integration test requires network access and can be run with:

```text
python -m pytest -m integration
```

Normalized data uses lowercase OHLCV float64 columns and a UTC-aware `DatetimeIndex` whose daily midnight value labels the provider session date. The label is not an execution timestamp. Original provider timestamps and fields remain in raw Parquet files. Both raw and normalized datasets have JSON provenance sidecars. No forward-fill is performed. Gaps are reported; weekends are informational for exchange assets, weekday gaps remain ambiguous without an exchange holiday calendar, and any skipped daily bar for a 24/7 asset is a warning. The caller can reject warnings with `DataEngine(allow_warnings=False)`.

## Repository layout

- `src/data/`: download, local storage and OHLCV validation
- `src/features/`: technical indicators, volatility and regime helpers
- `src/strategy/`, `src/risk/`, `src/portfolio/`, `src/execution/`: strategy and portfolio components at varying levels of integration
- `src/backtest/`: vectorized backtest and performance metrics
- `src/core/`: shared enums and data models
- `scripts/`: command-line entry points
- `app/`: Streamlit interface
- `config/`: YAML configuration
- `tests/`: current pytest suite

No live broker orders are generated. Live execution and broker integration are out of scope.
