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
