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

## Feature Engine — 2026-10-03

### Pre-implementation audit

| Feature | Observed implementation | Input and warm-up | Audit result |
|---|---|---|---|
| EMA20/50/200 | EOD/backtest/dashboard used `ewm(span=n, adjust=False)` | Close; defined from first observation | Same EMA formula was repeated in three workflows. Preserve recurrence and centralize. |
| ATR14 | True Range (`high-low`, `abs(high-prev_close)`, `abs(low-prev_close)`) then rolling SMA | OHLC; first TR is `high-low`; available after 14 TR values | Method was unambiguously SMA in code. Dashboard and EOD duplicated it. |
| D_ATR/Z_ATR | `(close - EMA20) / ATR14` | Close, EMA20, ATR14; NaN until ATR warm-up | Volatility helper duplicated the same formula. Use `z_atr`; retain `calculate_d_atr` alias. |
| RSI | Rolling SMA of positive/negative `close.diff()` components; initial NaN delta is replaced by zero via `where(..., 0)` | Close; first complete window occurs after `period` closes | EOD consumes RSI14; config separately has RSI2. No Wilder smoothing was present. Constant series yields NaN, one-sided gains yield 100. |
| Realized volatility | Main indicator: log returns, rolling sample std, fixed `sqrt(252)`, windows 10/20/60. Unused helper: simple returns, default window 20, same factor. | Close; window returns, thus window+1 closes | Conflicting helper identified. EOD used main indicator implementation; preserve it and centralize. |
| Drawdown | Backtest metrics calculate portfolio/equity drawdown only | Equity curve | No asset-price drawdown existed. New `asset_drawdown` is explicitly separate. |
| EMA slope | No existing implementation found | Not applicable | OPEN QUESTION; engine exposes explicit difference/percent methods and current configurable difference convention is provisional. |

### Feature Engine implementation conventions

- `FeatureEngine.compute` accepts the Data Engine's lowercase validated OHLCV, requires UTC-aware, ascending, unique `DatetimeIndex`, and returns OHLCV plus aligned lowercase features. It does not modify timestamps or fill values.
- EMA/ATR/RSI period keys previously present but unused in `config/strategy.yaml` were moved to the dedicated `config/features.yaml`; its old `rsi_period: 2` corresponds to `rsi_fast_period`, while the active EOD RSI14 is configured separately.
- EMA uses the legacy `adjust=False` recurrence. ATR defaults to SMA True Range and offers explicit Wilder RMA for comparison; configured convention remains SMA. RSI uses legacy simple rolling averages, including the initial zero delta. Realized volatility preserves the EOD log-return/sample-standard-deviation formula and configurable annualization (default 252) with windows 10/20/60; the same calculation API retains an explicit simple-return mode for the legacy adapter. Drawdown uses asset close and its cumulative peak. Zero ATR maps to NaN; RSI with both average gain and loss zero remains NaN. No feature is backfilled.
- EOD, Dashboard, regime, and backtest now consume the shared implementation. The backtest portfolio drawdown metric is unchanged and remains distinct. `z_atr` is canonical; the old D_ATR calculation API is a deprecated alias.
- Look-ahead tests perturb only a future OHLC observation and verify earlier EMA, ATR, RSI, realized-volatility, and slope observations are unchanged. Reference tests use small synthetic series with hand-checkable values.
- Software tests establish implementation behavior only; they do not validate financial hypotheses or parameters.

### OPEN QUESTIONS

- Is a fixed 252 annualization appropriate for BTC's 24/7 return calendar, and should the factor differ for other asset classes? The current setting preserves prior behavior and is not endorsed as a financial convention.
- What slope definition, normalization, source EMA, and lookback have a research basis? The configured `ema50[t] - ema50[t-5]` is an implementation placeholder, not a validated signal.
- Is simple rolling-average RSI intended, and how should constant/only-up/only-down windows be represented in signal logic? Engine leaves mathematically undefined constant windows as NaN; signal NaN policy is out of scope.
- Should the explicitly preserved SMA True Range be retained or replaced by Wilder ATR after a research comparison? No silent change was made.
- BTC session/calendar implications recorded in the Data Engine section remain open. No asset-specific feature periods were introduced.

## Regime Engine — 2026-10-03

### Pre-implementation audit

| Existing behavior | Exact observed rule | NaN/warm-up and transition behavior |
|---|---|---|
| Trend `BULL` | `close > ema_slow AND ema_fast >= ema_medium` (default EMA200/20/50) | EWM values start at the first close, so trend can classify from the first complete feature row. Comparisons against NaN are false. |
| Trend `BEAR` | `close < ema_slow AND ema_medium < ema_slow` | Both inequalities are strict. |
| Trend `NEUTRAL` | Remainder of observations | Equality at close/slow, failed BULL/BEAR criteria, or NaN comparisons all returned NEUTRAL in the old helper. No UNKNOWN state or historical series existed. |
| PANIC volatility | `realized_vol_10 > tail(252).quantile(0.90)` | The current observation is included in the quantile. With warm-up NaN the comparison is false; the remaining shock condition can still trigger. |
| PANIC shock | `close[t] - close[t-1] < -3 * ATR14[t]` | This is a signed one-bar price change in price units, not a peak-to-trough drawdown or percentage return. Strict boundary. |
| Redundant code | `daily_dd` and `panic_dd` were computed, but never contributed to the returned boolean. Comments alternated between absolute daily return and drawdown interpretations. | Removing this unused calculation does not alter PANIC output. The actual shock rule above is preserved. |

The old `is_panic` was a single bool and returned false for unavailable comparisons. It did not say whether both inputs were evaluated. The old trend helper classified each supplied frame's last row only; it had no transitions, memory, or point-in-time series API. There was no confidence/strength measure.

### Regime Engine decisions

- `RegimeEngine.classify_series` evaluates each row from that row and earlier observations; `classify_latest` is derived from its final row. `RegimeResult` contains timestamp, trend regime, stress regime, supporting feature values, reason, unavailable feature names, and an insufficient-data flag. No confidence score was invented.
- Trend is **BULL / NEUTRAL / BEAR / UNKNOWN**. The audited BULL/BEAR inequalities and default EMA periods remain unchanged. Missing or NaN required trend features produce UNKNOWN, not NEUTRAL. EMA slope is available in supporting features but does not gate BULL.
- Stress is independent: **PANIC / NORMAL / UNKNOWN**. PANIC occurs if either audited volatility or ATR shock condition is true. A positive known component is sufficient for PANIC even if the other is unavailable. Otherwise NORMAL requires both components to be evaluable; unavailable inputs yield UNKNOWN. This makes the missing-data state explicit rather than treating comparisons with NaN as proof of no stress.
- PANIC parameters are centralized in `config/regime.yaml`: volatility period 10, trailing lookback 252, quantile 0.90, ATR multiplier 3.0. The rolling quantile uses `min_periods=1` and includes the current observation, matching the prior latest calculation's available-history behavior. Thresholds are provisional, not optimized or financially validated.
- EOD now reads `RegimeResult`; its legacy `Regime` field remains the trend regime, `Stress_Regime` is additionally recorded, and the existing scale-in adapter receives trend plus the same boolean PANIC predicate (UNKNOWN maps to false there, matching the legacy helper's behavior). Scale-in, exits, sizing, allocation, and backtest rules were not redesigned.
- The current backtest still uses its pre-existing `close > ema_slow` weight gate. That proxy is not the composite Regime Engine classifier. The new point-in-time `classify_series` API is available for a later backtest integration decision; substituting it now would change backtest behavior and is deferred.
- The compatibility functions `detect_market_regime` and `is_panic` delegate to RegimeEngine. The first can now return UNKNOWN where missing inputs previously fell through to NEUTRAL; the second still returns a bool and maps UNKNOWN to false.
- Deterministic tests cover strict/inclusive boundaries, BULL/NEUTRAL/BEAR transitions, NaN and missing features, insufficient warm-up, high-volatility-only PANIC, shock-only PANIC, both/neither, BULL+PANIC, BEAR+PANIC, series/latest agreement, and future perturbation invariance.
- Implementation tests validate software behavior, not the financial meaning of a regime.

### OPEN QUESTIONS

- Should BULL require positive EMA slope, and which slope definition/lookback/source is supported by research? Current slope remains provisional and non-gating.
- Should `ema_fast >= ema_medium` remain part of BULL? How should exact threshold equalities be interpreted financially, beyond preserving the current strict/inclusive comparisons?
- Should PANIC remain orthogonal to trend? Is the statistical definition based on trailing volatility quantiles, a price shock, or both; should the current observation be part of its reference quantile; and how should shock versus persistent volatility be distinguished?
- Does `close[t] - close[t-1] < -3 * ATR[t]` represent the intended shock, given ambiguity between daily return, drawdown, and ATR/price? This implementation preserves the observed absolute-price rule and marks it provisional.
- What rolling history and calendar should apply to BTC's 24/7 bars? Current thresholds preserve repository behavior and are not an asset-calendar study.
- How should the existing backtest-only `close > ema_slow` proxy map to the composite trend/stress result without changing the backtest hypothesis or accounting model?
