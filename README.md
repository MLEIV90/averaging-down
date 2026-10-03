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

Streamlit serves the app at `http://localhost:8501` by default. Some pages fetch market data from Yahoo Finance; that requires network access. The Dashboard currently downloads its own data instead of using the local data pipeline.

## Data and EOD scripts

From the repository root:

```text
python scripts/update_data.py
python scripts/run_eod.py
```

`update_data.py` downloads daily history for SPY, BTC-USD and GLD and saves it under `data/raw/`. The script may request BTC hourly data for NY-close resampling, subject to yfinance's history limits. `run_eod.py` loads local data where available, falls back to Yahoo Finance, and writes signals and portfolio state under `data/processed/`.

Paths in the current application, scripts, and configuration are generally relative to the current working directory. Run these commands from the repository root. Data and generated outputs are ignored by Git.

## Run the backtest

From the repository root:

```text
python scripts/run_backtest.py
```

The runner loads local daily files from `data/raw/`, and downloads data if any asset is missing. It writes `data/processed/backtest_metrics.json` and `data/processed/equity_curve.csv`, which the Backtest page reads. The current engine is a simplified vectorized weight rule, not a simulation of the EOD scale-in state machine. It does not currently model transaction costs, slippage, cash balances, or individual trades. Treat its output as exploratory, not as a validated strategy result.

## Tests

From the repository root:

```text
python -m pytest
```

The current suite includes a Yahoo Finance download test and therefore requires network access; the remaining tests are local deterministic checks. The network test has not yet been separated or marked independently.

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
