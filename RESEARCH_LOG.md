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

## Signal Engine — 2026-10-04

### Provisional software hypotheses

- Entry opportunity requires the conjunction `z_atr <= asset threshold` AND `rsi2 <= 10`; thresholds are SPY -1.50, BTC -1.75, and GLD -1.50. `BTC-USD` is the repository symbol mapped to the configured `BTC` threshold.
- Only BULL trend is eligible. NEUTRAL and BEAR remain ineligible; UNKNOWN inputs are not treated as valid states.
- Reversal confirmation requires `close[t] > close[t-1]` and close location `(close-low)/(high-low) >= 0.60`, using only the current and prior bar. A zero range or unavailable inputs is UNKNOWN.
- PANIC blocks otherwise complete entry candidates. An UNKNOWN stress state produces UNKNOWN and never silently becomes NORMAL or enables an entry.
- `realized_vol_20` is reported as context only. It is not a gate, score, volatility state, or sizing input.
- These are provisional software hypotheses and are not evidence of alpha or financially validated parameters.

### Integration and OPEN QUESTIONS

- The engine accepts centralized Feature Engine output and obtains regimes from `RegimeEngine`. It intentionally does not recalculate feature/regime logic.
- `scripts/run_eod.py` continues to output its pre-existing scale-in state-machine actions. Replacing or merging those actions with the new opportunity states would alter EOD output semantics; no combined decision/execution contract has been specified. `src/backtest/engine.py` remains the documented legacy proxy.
- **OPEN QUESTION:** should PANIC block, reduce size, require alternate confirmation, or define a separate strategy? This milestone implements only the requested initial PANIC block.
- **OPEN QUESTION:** is BULL-only eligibility appropriate, or should NEUTRAL be tested as eligible under an explicit research design?
- **OPEN QUESTION:** should realized volatility condition the distribution of Z_ATR extremes by trend/volatility state in a later study? No conditional model or additional volatility regime is implemented here.
- Signal timestamp remains the input bar's session-date label; decision and earliest executable timestamp are still unresolved as recorded in the baseline.

## Position State Machine / Scale-In Engine — 2026-10-04

### Provisional design hypotheses

- T1 requires `SignalResult.signal_state == ENTRY_CANDIDATE`, plus the configured T1 Z_ATR threshold. The engine consumes Signal Engine outputs and does not recalculate indicators or regimes.
- T2 and T3 require their configured Z_ATR thresholds and a value strictly more extreme than the most recently filled tier's Z_ATR. They do not require another reversal confirmation; this is an explicit provisional design hypothesis.
- BULL is the only eligible trend. PANIC blocks new buys. NEUTRAL, BEAR, UNKNOWN, missing Z_ATR, unavailable signal inputs, and unknown stress never cause a purchase.
- Filled tiers progress monotonically T1 → T2 → T3; each signal evaluation proposes at most one tier. A flat cycle at a deep Z_ATR still proposes T1 first.
- `cumulative_weight` is the target cycle exposure. Order increment is target minus already filled weight; the current schedules remain configurable hypotheses, not risk-based sizing or validated parameters.
- A proposal is separate from a fill. Position state changes only through `apply_fill()` using the supplied actual fill price and timezone-aware fill timestamp. The average entry price is weighted by incremental exposure; anchor and entry timestamp remain those of the T1 fill; lowest price tracks known fills only.
- Cycle reset is explicit. PANIC, trend changes, EMA recovery, time, and losses do not automatically reset or close the cycle. `partial_sell_stage` remains zero.
- The old `get_action(d_atr, regime, is_panic)` adapter remains available with its previous mutating, signal-time semantics for legacy EOD and tests. The new PositionState engine is not yet wired into EOD.
- These are software design choices and provisional scale-in hypotheses; implementation tests do not establish financial validity or alpha.

### Integration limitation

- `scripts/run_eod.py` still uses legacy `get_action()`, the existing exit function, separate allocation code, and JSON persistence. It is intentionally unchanged: signal/decision/order/fill status, execution timestamp, price source, and persistence contract have not been defined. The backtest and exit module are also unchanged.

### OPEN QUESTIONS

- Are cumulative tier targets 20/45/70 for SPY, 10/25/40 for BTC, and 15/35/55 for GLD appropriate?
- Should T2/T3 require any reversal confirmation?
- Should there be a minimum wait between tiers?
- Should PANIC only block buys, or change exposure size?
- Should a per-cycle maximum exposure exist separately from configured cumulative weights?
- Is the first T1 fill the right anchor reference?
- Should a time-based rule limit cycle duration?
- What is the definitive signal → order → fill → persisted-position contract, including fill price and timestamps?

## Execution and Accounting Contract — 2026-10-04

### Implemented deterministic software contract

- `Order` and `Fill` are frozen records in `src/execution/orders.py`. Order states are PROPOSED, FILLED, REJECTED, and CANCELLED. Orders carry explicit signal, decision, and order timestamps; fills carry their own timestamp and actual `fill_price`. Accounting checks `signal <= decision <= order <= fill`, matching order/fill identifiers, asset, side, and quantity. All timestamps must be timezone-aware.
- `AccountingEngine.apply_fill()` consumes an externally supplied full fill and returns a new immutable `CashLedger` with cash and per-asset `Position` values. It rejects duplicate fill/order application, negative cash, oversells, invalid inputs, mismatches, and non-PROPOSED orders. It never creates a fill or mutates `PositionState`.
- BUY/SELL cash uses fill quantity × fill price and explicit commission/slippage costs (both default to zero). Average entry is quantity-weighted on buys and remains unchanged on partial sells. Realized P&L is recorded on sells only, net of that sell's costs; unrealized P&L is a separate observation from a current market price. Snapshots revalue positions without changing the ledger.
- Accounting simplification: acquisition costs reduce cash but are not capitalized into average entry price or carried into later realized P&L. Sell costs reduce that sell's realized P&L. No tax, corporate action, FX, short, margin, partial-fill, or portfolio allocation behavior is modeled. Position market value remains unknown (zero in the ledger) until a snapshot receives a current market price.
- `PositionState` remains separate. `ScaleInEngine.evaluate()` only proposes a decision; callers must separately provide the actual fill to `ScaleInEngine.apply_fill()` and `AccountingEngine.apply_fill()`. No automatic coupling or EOD/backtest integration was added.
- These are deterministic implementation conventions, not financial validation.

### OPEN QUESTIONS

- What execution latency and earliest permitted execution convention should be used?
- What fill convention and price source should the eventual backtest use?
- Which commission model and parameter source should be researched?
- Which slippage model and parameter source should be researched?
- How should cycle target weight and risk budget become executable quantity using equity, cash, and portfolio constraints?
- What portfolio cash constraints and reserve rules should apply?
- Should acquisition costs be included in accounting cost basis or tracked separately as in this initial simplified model?

## Risk and Position Sizing Engine — 2026-10-04

### Implemented deterministic layer

- `RiskSizingEngine.size()` accepts a `ScaleInDecision` and explicit `equity`, `available_cash`, `reference_price`, `atr`, and `realized_vol`; it returns a frozen `SizingDecision`. It reads only its configuration and supplied point-in-time inputs. It does not inspect `CashLedger`, consult market data, recalculate volatility, access global state, create `Order`/`Fill`, or mutate `PositionState` or accounting state.
- Asset notional allocation is `equity * incremental_weight`; allocation quantity is that notional divided by the reference price. Reference price is for sizing and may differ from an eventual fill price.
- Risk budget is equity times `risk_budget_fraction`. Stop distance is `stop_atr_multiple * ATR`; unadjusted risk quantity is risk budget divided by stop distance.
- With volatility adjustment enabled, `volatility_factor = clip(target_vol / realized_vol, min_factor, max_factor)`. The factor multiplies the risk budget only. Final quantity is the minimum of allocation quantity, volatility-adjusted risk quantity, and available-cash quantity.
- Binding ties use a deterministic precedence: ALLOCATION, then RISK, then CASH. Quantities stay fractional; no lot-size rounding is applied. Unsupported actions return `NO_SIZING`; non-positive results also return `NO_SIZING`. Invalid numerical inputs raise explicit `ValueError`s.
- Existing `src/risk/position_sizing.py` helpers remain in place for legacy EOD behavior. The new engine is separate and does not change EOD, backtest, order, or accounting flows.

### Provisional configuration hypotheses

`config/risk.yaml` now sets `risk_budget_fraction: 0.01`, `stop_atr_multiple: 3.0`, volatility adjustment enabled, factor clipping to [0.50, 1.50], and target volatility of 0.15 for SPY, 0.35 for BTC, and 0.15 for GLD. These are implementation placeholders required to exercise the engine; they have not been optimized or financially validated. `BTC-USD` uses the single `BTC` target.

The volatility factor adjusts risk budget only; it does not also scale allocation quantity. This is an explicit provisional sizing hypothesis, not a validated risk model. ATR is supplied by the caller from the configured Feature Engine; this sizing layer does not choose between ATR methods. Realized volatility is supplied by the caller and is never recalculated here.

### OPEN QUESTIONS

- What risk budget fraction is appropriate for research?
- Should the volatility factor adjust risk budget, allocation, or another independently specified quantity?
- What stop distance represents trade risk, and should it be linked to an actual exit/stop rule?
- Should ATR use the current SMA True Range or Wilder convention for sizing?
- Should risk budget depend on market regime?
- Should target volatility and annualization for BTC use a 252- or 365-day convention?
- Should T1/T2/T3 have distinct sizing rules?
- Should each cycle have an absolute exposure cap?
- How should target weight convert to quantity when other portfolio holdings and constraints are included?
- What minimum quantity and fractional precision apply to actual instruments?

## Exit Engine — 2026-10-05

### Implemented deterministic decision contract

- `ExitEngine.evaluate()` consumes explicit asset, position quantity, cycle anchor and entry timestamp, entry ATR, current timestamp and price, Z_ATR, RSI2, and partial-sell stage. It returns one frozen `ExitDecision` (`HOLD`, `PARTIAL_SELL`, or `FULL_EXIT`) with reason, point-in-time timestamp, reference price, quantity fraction, and diagnostics. It does not query state, market data, cash, orders, or fills, and does not mutate any supplied object.
- Priority is structural stop, time stop, partial recovery, then HOLD. Stop uses `anchor_price - exits.structural_stop.atr_multiple * entry_atr`; it is a signal condition using current price, not an assumed fill at stop price. Missing entry ATR disables only the stop and is reported in `unavailable_inputs`; missing Z_ATR or RSI2 disables only partial recovery. Non-finite inputs are rejected.
- Time stop compares actual elapsed seconds against configured calendar-day duration. Partial recovery requires Z_ATR >= configured threshold, RSI2 strictly above its threshold, and `partial_sell_stage == 0`. The decision reports a fraction; it does not derive absolute quantity.
- `should_reset_cycle()` permits reset only for a FULL_EXIT decision after an externally confirmed fill leaves zero quantity. A partial proposal never resets state. `PositionState.partial_sell_stage` accepts a non-negative completed-stage count; fill handling/increment remains outside this engine.
- Exit configuration is in `config/exits.yaml`, independently from `risk.stop_atr_multiple`.

### Provisional hypotheses

Structural stop multiple 3.0, maximum cycle duration 30 calendar days, partial recovery at Z_ATR >= 1.5 and RSI2 > 90, and one partial sale of 50% are implementation placeholders only. No optimization or financial validation is implied. Missing recovery indicators do not block stop or time checks; missing entry ATR does not block time or recovery checks.

### OPEN QUESTIONS

- Should the stop stay fixed from T1 using entry ATR, use another volatility reference, or update over the cycle?
- Should a trailing stop or portfolio drawdown stop exist?
- How should stop execution be modeled under overnight gaps?
- Should the time limit use calendar days or trading days, and should it depend on regime?
- Should there be one partial recovery or multiple stages? Is 50% reasonable?
- Is RSI2 > 90 too extreme, and is Z_ATR >= 1.5 too late?
- Should PANIC modify exits, and should a BEAR regime force a reduction?
- Should the configured exit stop ATR multiple differ from risk sizing's stop multiple? They are independent by design in this milestone.

The exit engine is not integrated into EOD, backtesting, order creation, fills, or accounting. Its tests establish deterministic software behavior only, not strategy validity.

## Portfolio Allocation Engine — 2026-10-05

### Implemented deterministic contract

- `PortfolioEngine.evaluate(snapshot, proposals, reference_prices)` consumes an immutable `PortfolioSnapshot`, timestamped `AllocationProposal` wrappers around `SizingDecision`, and supplied prices. It returns immutable per-asset requested/approved quantities and notionals, current/resulting exposure, reduction, constraint attribution, proposal timestamp, and diagnostics. Proposals later than the snapshot are rejected. `BTC-USD` is normalized to `BTC`, consistent with RiskSizingEngine; duplicate alias proposals are rejected.
- Positive proposals are buys only and retain the sizing layer's requested quantity subject to portfolio limits. Configured constraints cap approved quantity; attribution is `NONE`, a single constraint name, `MULTIPLE_CONSTRAINTS`, or `ZERO_EQUITY`. Existing quantities count toward asset and gross exposure. The engine does not change `SizingDecision`, query market data, or create orders, fills, or accounting entries.
- Competing proposals follow `priority_order` in `config/portfolio.yaml`, and returned decisions use the same order. This is an explicit, configurable capacity-allocation rule, not an expected-return or risk ranking. The current BTC, GLD, SPY order is a provisional operational precedence used only to assign limited capacity deterministically; it is not inherited from a quantitative study.
- The snapshot must represent the full supported long-only portfolio: equity equals available cash plus supported holdings valued at supplied prices. This implementation assumes `available_cash` is the full cash balance. At zero equity, only an empty portfolio is accepted and positive proposals are approved at zero.

### Provisional configuration and limitations

The initial limits preserve legacy repository defaults: 70% maximum gross exposure from `CapitalDeploymentEngine`, 30% minimum cash reserve, and SPY 35% / BTC 10% / GLD 25% concentration caps from the legacy allocation helper. These values were not independently researched, optimized, or financially validated. Given a fully reconciled portfolio, the 70% gross and 30% cash reserve limits leave the same incremental capacity and can bind simultaneously. There is no lot-size rounding, transaction-cost allowance, sell/rebalance proposal, leverage, risk contribution, portfolio volatility, covariance, or execution model. The engine is not integrated into EOD, backtest, UI, or accounting.

### OPEN QUESTIONS

- Is a 70% gross exposure limit appropriate, or should gross exposure be capped at 100%?
- Should the cash reserve remain static at 30% or vary with volatility/regime?
- Should BTC receive distinct portfolio treatment, and are the existing concentration limits appropriate?
- Should allocation priority remain configurable; what research basis should determine it beyond deterministic capacity allocation?
- Should concentration use market value, risk contribution, or another measure?
- Should a portfolio volatility/covariance limit be added?
- Should portfolio-level risk budget replace or complement per-asset RiskSizingEngine limits?
- Should reserved/unmodeled balances be represented explicitly instead of requiring equity to reconcile to supported holdings plus available cash?
- How should price movement between sizing reference and execution/fill affect approved notional and cash reserve?

Tests establish deterministic implementation behavior only, not financial validity.

## Sequential Backtest Engine — 2026-10-05

### Implemented event and time contract

- `src/backtest.engine.run_backtest()` now calls `BacktestEngine` in `src/backtest/sequential.py`. Raw normalized OHLCV is validated before the Feature Engine runs. The pipeline calls the existing Signal, Scale-In, Risk Sizing, Portfolio, Exit, Order/Fill, and Accounting components. The legacy EMA-weight vector proxy is moved to `src/backtest/legacy_engine.py` and renamed `run_legacy_backtest()` with a deprecation warning.
- For each asset, current-bar OHLCV/features/signals/exit conditions are observed at its UTC session-date label. A resulting order is timestamped at that decision label and can fill only at the next available bar's open for that asset. BTC uses its own timestamps and missing sessions do not get synthesized. Session-date labels do not encode the actual exchange open/close wall time.
- Asynchronous assets are merged on the union of their observed timestamps. Current bars update marks at close; positions are marked using the latest supplied close per asset. Pending orders fill before the current close observation. At end-of-data, the last order remains unfilled and is reported pending. Daily OHLC does not establish intraday ordering.
- An active-position exit proposal takes precedence over a new scale-in proposal for the same asset on that observation. The engines allow one tier and one exit proposal per observation. Strategy state changes only after AccountingEngine applies the corresponding Fill. A full cycle resets only after its confirmed sell leaves zero quantity; a partial fill advances the partial stage once.
- Commission and slippage are configured in `config/backtest.yaml` as basis points. Defaults are zero for diagnostic comparisons; no calibrated cost estimates are claimed. Fill price records the observed next-bar open and AccountingEngine deducts commission plus a separate dollar slippage cost exactly once. Next-open gap risk is retained: an order sized at the close may be rejected if its next-open notional plus fees exceeds cash, and an execution gap can move actual exposure beyond a cap approved at the decision reference price.
- To preserve the cash reserve after estimated transaction costs, the backtest passes its combined configured cost rate to `PortfolioEngine.evaluate()`; PortfolioEngine applies that estimate to available buy capacity. This is an optional backward-compatible input and does not change its default zero-cost behavior. Actual open-gap amounts are checked before fill and may still reject an order.
- AccountingEngine is the source of cash, marked positions, equity, and P&L. The event result includes portfolio curve (cash, marked value, equity, gross/net exposure, realized/unrealized P&L and costs), position state history, order/trade records, pending orders, and per-asset cycle/fill/holding/notional summaries. Advanced performance analytics remain deferred.

### Limitations and OPEN QUESTIONS

- Initial capital continues to come from `config/portfolio.yaml`; strategy, sizing, portfolio, feature, regime, and exit settings remain owned by their existing configurations. The legacy engine is not used by the public runner.
- **OPEN QUESTION:** What exchange-time mapping should convert UTC session-date labels to actual SPY/GLD open timestamps, and how should holidays and half sessions affect next-bar execution?
- **OPEN QUESTION:** Is a flat basis-point commission/slippage model sufficient, and what empirically supported asset-specific cost model should replace the zero defaults?
- **OPEN QUESTION:** Should fees be capitalized into average entry cost or remain cash costs under AccountingEngine's current simplification?
- **OPEN QUESTION:** How should a gap that pushes filled exposure beyond a portfolio cap be represented or mitigated without using future open information at decision time?
- **OPEN QUESTION:** Should rejected next-open buys be canceled as implemented, resized at the open, or handled by a different explicit execution rule?
- **OPEN QUESTION:** Should a partially filled/reduced scale-in advance the configured tier, given PositionState's tier model records completed tier actions rather than actual quantity?
- **OPEN QUESTION:** The position state stores tier weight, not quantity. Should a future state model explicitly reconcile shares and target weights after risk sizing and portfolio reductions?
- Resolved in M11: standalone performance and optional benchmark analytics use the conventions recorded in the Performance and Research Analytics section below.

Backtest implementation validity does not imply strategy profitability or financial validity.

## Performance and Research Analytics — 2026-10-05

### Implemented reporting contract

- `src.analytics.run_analytics(BacktestResult)` is a standalone immutable reporting layer. It consumes the sequential portfolio curve, actual fills in order records, SELL realized P&L, position history, per-asset summaries, and actual recorded costs. It does not change or invoke the strategy/backtest engine, fetch data, optimize parameters, or require Streamlit. `scripts.run_backtest --analytics` writes the report to `data/processed/backtest_summary.json`; sequential raw curve, order, position, and trade outputs remain separate.
- Analytics configuration is limited to reporting conventions in `config/analytics.yaml`: 252 observations/year, zero annual risk-free rate, and two minimum return observations for risk ratios. Each portfolio point is treated as one session regardless of elapsed calendar days. Total return uses configured initial capital; CAGR uses the first and last equity observations over `n - 1` intervals at configured annualization. Zero initial capital leaves capital-relative metrics undefined.
- Period returns are close-to-close fractional equity changes. Annualized volatility and Sharpe use sample standard deviation (`ddof=1`); Sharpe is mean daily excess return divided by sample daily standard deviation, annualized by square-root observations/year. Downside deviation is the annualized root mean square of negative daily excess returns; Sortino uses daily mean excess return divided by daily downside RMS and square-root annualization. Risk-free rate is annual, divided by annualization, and defaults to zero. Insufficient observations, zero volatility/downside deviation, and returns following a zero-equity observation produce explicit `None` values; a post-zero return is `None` in the return series.
- Drawdown is equity divided by its running high-water mark minus one. Recovery occurs on equality with or an exceedance of the prior peak. Maximum drawdown duration is the observation interval count from the last occurrence of the peak preceding the maximum trough through recovery, or through the final observation if unrecovered. Average drawdown remains signed; Ulcer Index is the root mean square of signed fractional drawdowns. No drawdown has duration zero and undefined start/trough/recovery timestamps.
- A fill is counted from an actual `Fill` record. A completed trade is one asset position cycle: realized SELL fill P&L, including partial sales, is aggregated until position history confirms quantity zero. Open cycles are excluded from win/loss and profit-factor statistics. Profit factor is positive completed-cycle P&L divided by absolute negative completed-cycle P&L; it is undefined when gross loss is zero. Zero P&L cycles are neither wins nor losses. Holding time uses entry timestamp to confirmed closing SELL timestamp when present.
- Exposure ratios, cash, and invested observation percentages use the actual portfolio curve. Transaction costs are summed from recorded Fill commission and slippage. Per-asset cycles/holding times use engine summaries, fill costs and notionals use actual fills, realized P&L uses SELL records, and contribution is asset realized P&L divided by total SELL realized P&L (undefined when denominator is zero). Approximate return contribution is realized P&L divided by initial capital. Per-asset exposure is quantity times recorded average entry price; it is a cost-basis proxy because per-asset marked market values are not retained in position history.
- Optional benchmark input is supplied by the caller as equity values aligned exactly with strategy observations. No market data is downloaded. The Backtest page only renders report values and curves; calculations remain in `src.analytics`.

### Research integrity and OPEN QUESTIONS

- These metrics describe historical backtest behavior only and do not establish future profitability. No parameter optimization is performed; no external future information is used; undefined metrics are represented explicitly; analytics do not alter strategy behavior.
- **OPEN QUESTION:** Should BTC observations use 365 sessions/year while exchange-traded assets use 252, or should reports continue to use one shared observation convention for the combined portfolio?
- **OPEN QUESTION:** Should risk-free rates remain zero for comparative research, or should a dated, point-in-time series be introduced in a future milestone?
- **OPEN QUESTION:** Should a benchmark be normalized from caller-supplied prices using a separately specified dividends/cash convention?
- **OPEN QUESTION:** Should per-asset exposure attribution require marked per-asset values in the sequential result instead of the documented average-entry cost-basis proxy?
- **OPEN QUESTION:** Should future reports provide complete cycle-level net-of-all-costs P&L? Recorded SELL realized P&L includes exit fill costs, while BUY costs reduce cash/equity but are not assigned to that cycle's realized P&L.

Analytics implementation and deterministic unit tests do not validate a strategy or imply future profitability.

## Scientific Validation and Research Integrity — 2026-10-05

### M12 validation contract

- `src.validation.run_validation(BacktestResult)` consumes only existing sequential result records and reporting configurations. It does not invoke or alter Signal, Regime, ScaleIn, sizing, portfolio constraints, exits, accounting, or execution. The immutable `ValidationReport` separates integrity, temporal checks, determinism, benchmark comparison, costs, scale-in, exposure, sample size, degeneracy, and overall status. `python -m scripts.run_backtest --validation` writes `data/processed/backtest_validation.json`; this remains separate from raw sequential outputs and M11 analytics.
- Critical integrity failures include non-finite/negative portfolio values, equity not equaling cash plus market value within configured tolerance, transaction-cost reconciliation failures, duplicate order/fill IDs, invalid fill/order/TradeRecord links, infeasible sequential cash or SELL quantities, non-chronological/duplicate timestamps, and final position quantities inconsistent with fills. Cumulative curve costs are matched to actual Fill costs through each observation. The validator does not repair a result.
- Temporal checks verify aware ordered signal/decision/order/fill timestamps, fills strictly later than signal and decision, an explicit `next_bar_open` configuration, unfilled pending orders, and that position snapshots do not include fills from later timestamps. `BacktestResult` does not retain the source OHLC bars, so exact next available bar/open-price matching is `NOT_EVALUABLE`. These structural checks are evidence against specified violations, not a mathematical proof of no look-ahead.
- Repeated validation of the same immutable result is compared through canonical JSON and a SHA-256 digest. `run_backtest_twice()` is an optional helper for a caller-supplied backtest function; it uses no randomization and does not download data itself.
- A caller may supply a benchmark equity Series or sequence. It must have the same number of observations; a Series index or explicit timestamps must match strategy timestamps exactly; values must be finite and non-negative and the starting value positive for returns. No market-data provider is called. Relative return, CAGR, maximum drawdown, volatility, Sharpe, and common-starting-capital final values are descriptive in-sample comparisons, not alpha claims.
- Costs use actual recorded Fill commission and slippage and are reconciled both to `BacktestResult.total_transaction_costs` and cumulative portfolio-curve costs. The report includes configured basis-point settings, cost/capital and cost/notional, observed final equity/return, and an explicitly mechanical final-equity cost add-back. That add-back is not a no-cost strategy counterfactual because the configured cost estimate can affect allocation capacity and accepted quantities. No second strategy run is performed.
- **Accounting interpretation clarification:** `AccountingEngine` subtracts SELL fill costs from realized SELL P&L. BUY fill costs reduce cash/equity and appear in total recorded transaction costs, but are not assigned back into subsequent realized cycle P&L. Therefore cycle-level realized SELL P&L and profit-factor attribution are not fully net of every cost paid during entry; the separate cost report is needed to interpret total equity.
- Scale-in diagnostics count filled BUY entries by tier and group them by asset until position history confirms zero quantity. Additional entry fills are counted as scale-in fills; completed cycles report entry count, multi-entry share, traded notional, and realized SELL P&L. Partial SELL outcomes remain within their cycle. Open cycles are reported separately. Existing records support realized cycle attribution, but not a counterfactual without scale-in. No thresholds or tier rules are changed.
- Portfolio gross/net exposure and invested time use the portfolio curve. Asset realized P&L and fills/notional use actual sequential records. Per-asset exposure uses quantity times average entry price, a documented cost-basis proxy because final per-asset market marks are not retained in `position_history`. Concentration thresholds and sample-size warning thresholds are configurable reporting heuristics, not financial judgments or formal significance/power tests. Dominant concentration is a prompt for review, not an automatic rejection.
- Degeneracy checks flag no fills, buy-only samples, zero costs while trading, unchanged equity despite fills, zero volatility with varying exposure, concentrated P&L, repeated fill fingerprints, per-asset summary contradictions, extreme gross marked exposure relative to initial capital, and final open positions whose aggregate unrealized P&L is zero. A zero unrealized amount may be legitimate at unchanged marks; it is a review warning. Per-asset open-position unrealized P&L cannot be independently recomputed without per-asset final marks.
- Overall `FAIL` is reserved for integrity failures, impossible temporal ordering, or nondeterministic repeated validation. Otherwise warnings or not-evaluable requested checks produce `PASS_WITH_WARNINGS`; a clean set of fully evaluable checks can produce `PASS`. The report's interpretation is about internal consistency only.

### Research limitations and OPEN QUESTIONS

- **Passing M12 does not establish that the strategy has predictive power, positive expected return, statistical significance, or live-trading viability.** Passing software invariants is distinct from accounting correctness, causal validity, and economic usefulness.
- Sample labels (`INSUFFICIENT_SAMPLE`, `LIMITED_SAMPLE`, and `ADEQUATE_FOR_DESCRIPTIVE_ANALYSIS`) are configurable descriptive thresholds only. They are not formal power or significance tests and do not imply adequacy for investment conclusions.
- **OPEN QUESTION:** Should a future BacktestResult retain per-asset close marks and source-bar provenance so final unrealized P&L and next-bar-open prices can be checked independently?
- **OPEN QUESTION:** Should future result records include an explicit cycle ID and fill-level entry/exit linkage rather than inferring cycles from asset, fill sequence, tiers, and confirmed flat history?
- **OPEN QUESTION:** A no-scale-in counterfactual would require an explicitly authorized alternative backtest run and a controlled execution/portfolio comparison; it is intentionally not fabricated in M12.
- **OPEN QUESTION:** What benchmark instrument, dividend treatment, and common observation convention are appropriate for SPY/BTC/GLD comparative research?
- **OPEN QUESTION:** Are the configurable 5/20-cycle sample warning bands and 80% concentration review share suitable descriptive prompts, or should researchers select alternatives before interpreting future reports?
- **OPEN QUESTION:** The mechanical cost add-back is exact only for direct recorded cost deductions on the observed path; accepted quantity and trade-level attribution can depend on configured cost assumptions. Should a separately specified sensitivity experiment be authorized in a future milestone?

Validation software tests do not constitute a validation of strategy profitability or predictive performance.
# M13 — Ablation & sensitivity analysis (diagnostic only)

M13 is a diagnostic research layer, not an optimization framework. The baseline is one run of the current production backtest using the existing config YAML files; its configuration hash is SHA-256 over the ordered filenames and exact file bytes. The same in-memory baseline configuration is used as the reference for every experiment.

Each ablation changes one conceptual component. Supported ablations remove trend-regime eligibility (panic blocking remains), RSI2 entry gating, reversal confirmation, T2/T3 entries, volatility sizing, portfolio allocation limits, partial recovery exits, time stops, or structural stops. Existing production engine implementations perform all decisions.

Sensitivity uses the explicit values in config/research.yaml; each run changes one parameter from baseline. Negative Z_ATR perturbations preserve their direction and every scale-in threshold variant is checked against the unchanged adjacent tier values. The currently configured SPY volatility target is the only target-volatility factor included. Values are not selected based on results.

Configuration overrides are constructed in memory. The suite snapshots production YAML bytes before execution and checks them again after it. Experiment IDs hash experiment type, component/parameter, value and baseline configuration hash. Machine-readable JSON is deterministic and contains no generated timestamp. Analytics and M12 Validation are reused for each backtest result; failed validation yields INVALID.

Limitations: results describe only caller-provided data and current engine architecture. Portfolio constraint ablation removes exposure, reserve and per-asset caps while retaining deterministic allocation mechanics. The no-scale-in counterfactual retains T1. Existing validation checks are software/research-integrity diagnostics, not proof of economic validity. Some validation checks can be NOT_EVALUABLE on the present BacktestResult schema. Observed sensitivity does not imply causal economic significance. This milestone makes no profitability or statistical-significance claim.

OPEN QUESTION: approve additional target-volatility parameters, more assets/market data, or different perturbation values only as explicit future research decisions; this implementation does not select or recommend them.
