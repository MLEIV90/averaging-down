# Changelog

Notable repository changes are recorded here.

## [Unreleased]

### Added

- Project development and quantitative integrity rules in `AGENTS.md`.
- Initial repository baseline, limitations, and open research questions in `RESEARCH_LOG.md`.
- Central data acquisition, validation, normalization, Parquet storage, and JSON provenance through `src/data/`.
- Deterministic Data Engine unit tests and a separately marked Yahoo Finance integration test.

### Changed

- Expanded setup and run instructions to cover the actual UI, data, EOD, backtest, and test entry points.
- Declared Plotly as a direct dependency because Streamlit pages import it directly.
- Refactored data update, EOD, backtest, and Dashboard data access to consume the shared Data Engine.
- Normalized daily data now uses lowercase OHLCV fields and a UTC-aware session-date index; provider raw data remains separately stored.
- Pytest runs deterministic tests by default and excludes tests marked `integration`.

### Known baseline limitations

- The vectorized backtest is not the EOD state-machine strategy and does not model costs or portfolio accounting.
- Some UI pages are placeholders, and not all `src/` modules are connected to a runtime workflow.
- Yahoo Finance provider data and coverage can change; downloaded datasets are cached locally and are not versioned in Git.
- Weekday gaps in exchange-traded data remain ambiguous without a holiday calendar.
