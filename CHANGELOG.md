# Changelog

Notable repository changes are recorded here.

## [Unreleased]

### Added

- Added a deterministic, standalone ExitEngine with structural stop, time stop, partial recovery, explicit HOLD decisions, and cycle-reset contract.
- Project development and quantitative integrity rules in `AGENTS.md`.
- Initial repository baseline, limitations, and open research questions in `RESEARCH_LOG.md`.
- Central data acquisition, validation, normalization, Parquet storage, and JSON provenance through `src/data/`.
- Deterministic Data Engine unit tests and a separately marked Yahoo Finance integration test.
- Shared deterministic Feature Engine, configurable feature conventions, expected-value and look-ahead tests.

### Changed

- Expanded setup and run instructions to cover the actual UI, data, EOD, backtest, and test entry points.
- Declared Plotly as a direct dependency because Streamlit pages import it directly.
- Refactored data update, EOD, backtest, and Dashboard data access to consume the shared Data Engine.
- Normalized daily data now uses lowercase OHLCV fields and a UTC-aware session-date index; provider raw data remains separately stored.
- Pytest runs deterministic tests by default and excludes tests marked `integration`.
- Dashboard, EOD, regime, and backtest now consume centralized lowercase features; `D_ATR` remains a deprecated compatibility alias for `z_atr`.
- Added `config/features.yaml` with explicit periods, ATR/RSI methods, realized-volatility windows and annualization, and slope settings.
- Removed unused EMA/ATR/RSI period keys from `config/strategy.yaml`; feature periods now have one configuration source.
- Added a structured Regime Engine with separate trend/stress states, causal series/latest APIs, explicit UNKNOWN handling, and configurable existing PANIC thresholds.
- Added a configurable deterministic Signal Engine with point-in-time opportunity components and explicit UNKNOWN/PANIC handling.
- Added validated fill-derived `PositionState` and a deterministic scale-in proposal/fill API using the existing configurable tier targets.
- EOD now consumes RegimeEngine and records Stress_Regime while preserving its existing strategy consumers and thresholds.
- Added provisional per-asset Z_ATR + RSI2 extreme conditions, close-location reversal confirmation, BULL eligibility, PANIC blocking, and realized_vol_20 context output in the independent Signal Engine.
- Replaced the `PositionState` stub with an immutable position-cycle state and strict tier configuration checks; retained the mutating `get_action()` as a legacy compatibility adapter.
- Added immutable Order and Fill records plus deterministic long-only cash, position, P&L, and account snapshot accounting. Costs default to zero; no broker or automatic fill path is connected.
- Added a deterministic risk and position sizing layer that converts scale-in weight proposals into provisional quantities under separate allocation, risk, volatility, and cash limits; it remains independent from orders, fills, accounting, and portfolio integration.
- Added provisional, independent exit parameters in `config/exits.yaml`; partial-sell stages can record completed fills in immutable `PositionState`.

### Known baseline limitations

- The vectorized backtest is not the EOD state-machine strategy and does not model costs or portfolio accounting.
- Some UI pages are placeholders, and not all `src/` modules are connected to a runtime workflow.
- Yahoo Finance provider data and coverage can change; downloaded datasets are cached locally and are not versioned in Git.
- Weekday gaps in exchange-traded data remain ambiguous without a holiday calendar.
