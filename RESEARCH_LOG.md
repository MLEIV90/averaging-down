# Research log

This log records research assumptions and decisions. No strategy parameter is considered validated merely because it appears in code or configuration.

## Repository baseline — 2026-10-02

### Observed implementation

- The EOD script uses EMA20/50/200, ATR14, RSI14, realized volatility, a regime helper, scale-in rules, exit checks, and volatility-adjusted allocation.
- The configured strategy includes provisional scale-in thresholds, but `ScaleInEngine` uses only tier names and `z_atr`; configured cumulative weights are not used by that engine.
- The backtest computes vectorized weights from EMA20/EMA200 and fixed price offsets. It does not call the EOD signal, scale-in, risk, or portfolio engines.
- The Streamlit Dashboard separately downloads data and calculates EMA/ATR features. Other pages read generated JSON/CSV files or show placeholders.
- The downloader, validator, and loader exist, but validation is not called by the current data-to-feature workflows.
- `risk.yaml` and `portfolio.yaml` are not read by the principal EOD/backtest scripts. Several risk, portfolio, execution, Monte Carlo, and attribution modules are standalone or placeholders.
- Local raw data and processed outputs may exist on a developer machine, but `.gitignore` excludes them; they are not reliable inputs for another checkout.

### Research integrity limitations

- The backtest shifts weights by one bar before applying returns, which avoids same-bar use of its close-derived weights for that return. However, its signal/execution timestamps are implicit, and its rules are not the configured scale-in strategy.
- The backtest does not include transaction costs, slippage, cash/position accounting, or trade records. Its reported performance should be treated as exploratory.
- The EOD pipeline uses the latest bar to generate a signal, but no execution model is connected to it.
- Repository data and configuration paths are generally relative to the current working directory, so entry points assume execution from the repository root.
- `scripts/update_data.py` imports `src` before adding the repository root to `sys.path`; invocation from some environments or working directories may fail.
- `tests/test_data.py::test_download_structure` calls Yahoo Finance and is not a deterministic offline unit test.

### OPEN QUESTIONS — quantitative research decisions

- What is the exact timing contract for EOD feature calculation, signal timestamp, decision timestamp, and earliest permitted execution?
- What are the validated regime slope definition and lookback, and how should missing/warm-up feature values be handled?
- What precise PANIC definition should be researched and tested?
- Which scale-in thresholds, per-asset target volatilities, allocation caps, cycle exposure limits, reserve, and risk budgets are approved research parameters rather than provisional examples?
- What stop, partial de-risking, time stop, cycle reset, and tier-locking rules should govern state transitions?
- Which transaction cost and slippage models and parameter sources should be used?
- What accounting convention, benchmarks, date ranges, and validation protocol should the backtest use?
- How should survivorship and asset-history differences be handled for this three-asset universe?

No new quantitative hypotheses or parameter values were adopted in this milestone.

## Data Engine — 2026-10-03

### Technical decisions

- Yahoo Finance via `yfinance` remains the only provider. Requests specify `auto_adjust` explicitly; the default remains `false`, matching the previous downloader behavior. Raw provider data and normalized OHLCV are stored separately as Parquet, with JSON provenance sidecars for both.
- Normalized data uses lowercase `open`, `high`, `low`, `close`, `volume`, float64 values, and a unique ascending UTC-aware `DatetimeIndex`. For daily bars, the displayed provider date is retained as a session-date label at 00:00 UTC. This label is not an instant when a decision or trade can occur. Naive intraday source timestamps are localized using configured market timezone; aware intraday instants are converted to UTC.
- Validation rejects empty/malformed datasets, missing or non-finite OHLCV, naive timestamps, unsorted or duplicate timestamps, duplicate complete rows, incoherent OHLC, non-positive prices, and negative volume. No invalid rows are dropped, no prices are filled, and only the explicit incremental overlap rule permits provider-revised timestamps to replace older values.
- Gap reports distinguish weekend closures for configured exchange assets, unexpected missing daily observations for 24/7 assets, weekday calendar ambiguity, and requested leading/trailing bounds. Warnings are allowed by default and can be rejected by constructing `DataEngine(allow_warnings=False)`; informational issues do not block loading.
- Incremental updates use the last stored observation. If local legacy Parquet lacks provenance, it is labeled as unknown; an explicit update rebuilds history from the configured start instead of silently mixing it with newly downloaded data. BTC data that fell back to provider daily bars remains on that convention for subsequent updates rather than switching silently to hourly aggregates.
- The Dashboard now reads local validated data through the Data Engine and never downloads directly. The update script is the explicit data refresh entry point. EOD and backtest load through the same engine.

### Limitations and OPEN QUESTIONS

- **OPEN QUESTION:** exact BTC daily-bar temporal contract, including whether the current fixed 21:00 UTC aggregation should move with New York daylight saving time. The existing fixed cutoff was preserved and made configurable; it is not validated as the correct research convention.
- **OPEN QUESTION:** adjusted versus unadjusted data treatment for research and corporate-action handling. The default remains explicitly unadjusted to match existing `auto_adjust=False`; this is not a claim that it is correct for total-return backtests or trading.
- No exchange holiday library was added. Weekday gaps are warnings with an ambiguous classification, not a definitive market-data error or a verified calendar closure.
- Yahoo Finance hourly coverage is limited; the existing fallback to daily data is retained and recorded in provenance. Historical data returned by Yahoo Finance may be revised. No immutable dataset snapshot/versioning is implemented.
- Legacy local files have unknown provenance. A local-only load can normalize and label that uncertainty; an update triggers a full configured-range rebuild to avoid mixing unknown history with new data.
- No strategy, feature, risk, portfolio, or backtest rule was changed in this milestone.
