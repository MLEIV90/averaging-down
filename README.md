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
python -m scripts.run_backtest --analytics --validation
```

The runner loads validated local data through the Data Engine, downloading only if local data is absent. `src/backtest.engine.run_backtest()` is the canonical sequential event-driven pipeline. It writes portfolio/equity/cash curves, position history, orders, fills/trades, and a summary under `data/processed/`. The former vectorized EMA-weight proxy is retained only in `src/backtest/legacy_engine.py` as `run_legacy_backtest()` and is deprecated.

`--analytics` writes the structured M11 report to `backtest_summary.json`; `--validation` writes M12 structural research-integrity findings separately to `backtest_validation.json`. Both operate on the same sequential `BacktestResult`. Validation can also be called directly with `src.validation.run_validation()` and accepts only caller-supplied benchmark curves; it does not download data. A passing report checks implementation consistency and does not establish predictive power or profitability.

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
- `src/features/`: deterministic feature calculations, feature configuration and regime helpers
- `src/strategy/`, `src/risk/`, `src/portfolio/`, `src/execution/`: strategy and portfolio components at varying levels of integration
- `src/backtest/`: vectorized backtest and performance metrics
- `src/core/`: shared enums and data models
- `scripts/`: command-line entry points
- `app/`: Streamlit interface
- `config/`: YAML configuration
- `tests/`: current pytest suite

No live broker orders are generated. Live execution and broker integration are out of scope.

## Feature Engine

The Data Engine's validated, lowercase OHLCV DataFrame (UTC-aware, ascending,
unique `DatetimeIndex`) is the input contract. `FeatureEngine.compute()` in
`src/features/engine.py` returns a copy containing the same OHLCV columns and
aligned lowercase features. It does not download, repair, fill, or relabel data.
The Dashboard, EOD script, regime helper, and vectorized backtest consume this
shared implementation. Feature periods and conventions live in
`config/features.yaml`.

Current software conventions (tested for implementation correctness, not
financially validated):

| Feature | Current formula | Initial availability |
|---|---|---|
| `ema20`, `ema50`, `ema200` | `close.ewm(span=n, adjust=False)`; first close seeds the recurrence | First observation |
| `atr14` | True Range max of `high-low`, `abs(high-prev_close)`, `abs(low-prev_close)`; rolling SMA (`sma_true_range`) | At observation `period - 1`; first True Range is `high-low` |
| `z_atr` | `(close - ema20) / atr14`; zero ATR maps to NaN | When EMA and ATR are available |
| `rsi2`, `rsi14` | Rolling simple averages of positive and negative close changes; first NaN change is treated as zero, matching legacy code | After `period` closes |
| `realized_vol_10/20/60` | Sample standard deviation (`ddof=1`) of log close returns times `sqrt(annualization)`; default factor 252 | After `window` returns (`window + 1` closes) |
| `asset_drawdown` | `close / close.cummax() - 1` | First observation |
| `ema50_slope` | EMA50 difference over configured positional lookback; currently 5 | After lookback observations of EMA |

Warm-up values remain NaN where the formula does not yet have enough data;
there is no backfill. A constant RSI window has zero gains and losses, so its
undefined value remains NaN; zero ATR also yields NaN for `z_atr`. The feature
engine keeps asset-price drawdown separate from portfolio equity drawdown in
`src/backtest/metrics.py`. `D_ATR` is retained as a deprecated function alias
for `z_atr`; core output uses lowercase `z_atr`.

The prior active EOD implementation used log returns, sample standard deviation,
windows 10/20/60, and fixed factor 252. An unused helper separately used simple
returns and a 20-observation window; it now calls the same centralized
calculation API with the explicit `simple` return method to retain compatibility.
The existing ATR calculation is simple moving average True Range, not Wilder
ATR. Wilder remains an explicitly selectable implementation but is not the
current configured convention.

Open research decisions are recorded in `RESEARCH_LOG.md`: whether annualizing
crypto volatility with 252 is appropriate; the financial interpretation of
EMA slope and its lookback; RSI behavior for constant/one-sided moves; whether
SMA True Range should be replaced after research; and the BTC session calendar.
No thresholds, entry/exit rules, or strategy hypothesis were changed in this
milestone.

## Regime Engine

`RegimeEngine` in `src/features/regime.py` consumes the Feature Engine output
and provides `classify_series()` and `classify_latest()`. The historical API
returns an aligned DataFrame; the latest API returns a `RegimeResult` with
timestamp, separate `trend_regime` and `stress_regime`, supporting features,
reason, unavailable inputs, and an insufficient-data flag. It does not return
a confidence score. `UNKNOWN` means required inputs are missing or not yet
available; it is distinct from a valid `NEUTRAL` trend and `NORMAL` stress.

Trend rules preserve the prior inequalities: **BULL** iff `close > ema_slow`
and `ema_fast >= ema_medium`; **BEAR** iff `close < ema_slow` and
`ema_medium < ema_slow`; otherwise **NEUTRAL**. Any required missing/NaN trend
feature yields **UNKNOWN**. EMA slope is exposed as a supporting feature but
does not gate BULL.

Stress is classified independently as **PANIC**, **NORMAL**, or **UNKNOWN**.
The provisional PANIC rule preserves the existing conditions: the configured
realized volatility is strictly greater than its trailing rolling quantile, or
the signed close change is strictly less than negative `panic_atr_multiple`
times ATR. The default quantile includes the current observation, matching the
previous latest-bar `tail(252).quantile(0.90)` behavior. Parameters are in
`config/regime.yaml` (10-period volatility, 252-observation lookback, 0.90
quantile, 3.0 ATR multiple). If a component is unavailable, a confirmed PANIC from
the other component is still reported; otherwise stress is `UNKNOWN` until
both components can be evaluated. This differs semantically from the former
boolean helper's implicit false on NaN and avoids treating unavailable stress
data as proven NORMAL.

Trend and stress can coexist, including **BULL + PANIC** and **BEAR + PANIC**.
The EOD adapter preserves the previous `Regime` trend field and adds
`Stress_Regime`; scale-in, exits, sizing, thresholds, and allocation rules were
not redesigned. These classifications are software implementations of
provisional rules, not financially validated regimes.

## Signal Engine

`SignalEngine` in `src/strategy/signals.py` consumes `FeatureEngine` output and
derives trend/stress states through `RegimeEngine`; it does not recalculate
indicators, change regime rules, or size positions. Its `classify_series()` and
`classify_latest()` APIs expose separate Z_ATR/RSI2 extremes, reversal
confirmation, trend eligibility, stress blocking, realized-volatility context,
deterministic reason codes, and unavailable inputs. Thresholds and gates live
in `config/signals.yaml`.

The provisional hypotheses are a per-asset Z_ATR threshold AND RSI2 <= 10,
BULL-only regime eligibility, rising close plus close location >= 0.60 for
reversal confirmation, and PANIC blocking. `BTC-USD` maps to the configured
`BTC` threshold. `realized_vol_20` is exposed but does not gate signals. An
UNKNOWN trend, stress state, or required input produces UNKNOWN and cannot
enable an entry. These rules are not evidence of alpha or financial validation.

The new engine remains independent of `scripts/run_eod.py`: that entry point
still emits legacy scale-in actions, and replacing or combining them would
change EOD output semantics before strategy integration is specified. The
legacy backtest remains untouched.

## Position State and Scale-In Engine

`ScaleInEngine.evaluate(signal, state)` consumes a `SignalResult` and validated
`PositionState`, then returns an immutable `ScaleInDecision`. It proposes at
most one tier and does not change the position. `apply_fill(state, decision,
fill_price, fill_timestamp)` validates the decision against the configured
tier and returns a new state based on that actual fill. The signal bar close is
not used as an assumed fill price. `reset_cycle(state)` is an explicit reset;
trend changes, PANIC, and time do not reset a position.

`PositionState` stores completed cycle fills, including the first-fill anchor,
lowest fill, cumulative target weight, weighted average entry, actual entry
timestamp, last filled Z_ATR, and an unused partial-sell stage fixed at zero.
Tier schedules in `config/strategy.yaml` are validated and remain provisional.
`BTC-USD` uses the single `BTC` configuration. No exits, sizing adjustment,
execution, or backtest integration is implemented here.

The old mutating `ScaleInEngine.get_action(d_atr, regime, is_panic)` remains for
`scripts/run_eod.py` and legacy callers. It preserves its legacy signal-time
state semantics; new position logic should use `evaluate()` and `apply_fill()`.

## Execution and Accounting Models

`src/execution/orders.py` defines immutable `Order` and `Fill` records. `AccountingEngine.apply_fill()` in `src/execution/accounting.py` consumes an explicit full fill and returns a new `CashLedger`; it never creates fills or modifies the strategy's `PositionState`. The required chronology is signal timestamp ≤ decision timestamp ≤ order timestamp ≤ fill timestamp, all timezone-aware. Accounting uses only `Fill.fill_price`.

BUY/SELL cash, long-only quantities, weighted average entry, realized P&L on sells, and observed-price unrealized P&L are represented independently. Commission and slippage fields default to zero. There is no broker routing, sizing, partial fills, margin, or EOD/backtest integration. Accounting simplifications and OPEN QUESTIONS, including execution timing, fill convention, cost models, and target-weight-to-quantity conversion, are recorded in `RESEARCH_LOG.md`.

## Risk and Position Sizing

`RiskSizingEngine` in `src/risk/sizing_engine.py` accepts an immutable `ScaleInDecision` plus explicit equity, available cash, reference price, ATR, and realized volatility, and returns an immutable `SizingDecision`. It proposes fractional quantity only; it does not read accounting state, create orders/fills, mutate strategy state, or integrate portfolio constraints. `reference_price` is a sizing input and may differ from the eventual fill price.

Configuration lives in `config/risk.yaml`. Provisional formulas are allocation quantity = equity × incremental weight / reference price; stop distance = ATR × stop ATR multiple; risk quantity = risk budget / stop distance; volatility-adjusted risk budget = risk budget × clipped target-vol / realized-vol factor; final quantity = the minimum of allocation, volatility-adjusted risk, and available-cash quantities. Equal minima bind in deterministic order: ALLOCATION, RISK, CASH. Values remain fractional and are not rounded to instrument lot sizes. These parameter values and conventions are research hypotheses, not financially validated sizing rules; see `RESEARCH_LOG.md`.

## Portfolio Allocation Engine

`PortfolioEngine` in `src/portfolio/engine.py` accepts an immutable
`PortfolioSnapshot`, timestamped `AllocationProposal` values wrapping
`SizingDecision`, and explicit point-in-time reference prices. It returns
immutable per-asset allocation decisions and does not alter risk sizing,
accounting, position state, orders, or fills. Each proposal timestamp must be no
later than the portfolio snapshot. The supplied prices must match each sizing
proposal's reference price.

Portfolio constraints live in `config/portfolio.yaml`. Provisional defaults
retain legacy assumptions: 70% maximum gross exposure, 30% minimum cash reserve,
and per-asset limits of SPY 35%, BTC 10%, GLD 25%. The configured capacity order
BTC, GLD, SPY deterministically allocates finite capacity and is not a financial
ranking. Existing positions count toward the limits. Snapshot equity must equal
available cash plus supported holdings valued at the supplied prices. Unsupported
assets, leverage, sells, and portfolio volatility or covariance limits are not
modeled.

This engine is standalone and is not connected to EOD, the legacy backtest,
Dashboard, order creation, fills, or accounting. Values and software behavior
are provisional research infrastructure, not validated portfolio guidance.

## Sequential Backtest Engine

`BacktestEngine` in `src/backtest/sequential.py` is the canonical backtest used
by `scripts/run_backtest.py`. It accepts raw normalized OHLCV, validates it
before feature calculation, then calls the shared Feature, Signal, Scale-In,
Risk Sizing, Portfolio, Exit, Order/Fill, and Accounting engines in sequence.
Accounting is the source of cash, holdings, realized/unrealized P&L, and equity.
The immutable result includes portfolio and position histories, orders,
completed trades, pending end-of-data orders, and per-asset summaries. No
advanced performance analytics are calculated in this milestone. The Backtest
page reads these sequential outputs; it does not implement quantitative rules.

The execution convention is **next available bar open**. Features, regime,
signals, exits, and sizing use data through the current bar; orders are created
at that observation and can fill only at the next available bar for that asset.
Signal timestamps use the repository's UTC session-date labels. They are not
intraday exchange timestamps. SPY/GLD and BTC therefore follow their own
available-bar calendars; no shared calendar is imposed. A last-bar order stays
pending and receives no fabricated fill.

`config/backtest.yaml` owns commission and slippage settings, both in basis
points. Defaults are zero to support diagnostic comparisons and are not
calibrated cost estimates. Fill price is the observed next-bar open; commission
and the dollar slippage charge are applied once through AccountingEngine. The
estimated combined cost rate is supplied to PortfolioEngine when reserving cash;
actual next-open amounts are checked again before a buy fill.
Stops are evaluated from the current bar and filled at the next available open,
so overnight gaps can produce materially different outcomes from the stop
threshold. Portfolio caps are evaluated at the decision reference price and can
also drift after an execution gap. Daily bars do not identify intraday ordering.

**Backtest implementation validity does not imply strategy profitability or financial validity.**

## Walk-forward / out-of-sample research

M14 provides fixed-strategy chronological evaluation through
src.research.walk_forward.run_walk_forward(data). It accepts caller-supplied,
validated OHLCV frames and does not load or download market data. Temporal
settings only live in config/walk_forward.yaml; strategy thresholds are read
unchanged from production configuration.

Each manifest separates TRAIN, VALIDATION, an optional embargo, and TEST
boundaries by explicit observed-bar timestamps. Train and validation are
historical contexts only: M14 has no parameter fitting or selection, and only
TEST is scored. Expanding and rolling windows are supported. Independent test
windows instantiate a fresh canonical backtest, so cash, positions, strategy
cycles and queued orders reset. A signal observed at bar t remains eligible
for execution at the next available bar's open. Orders still pending at the
test end are reported and are not filled beyond that boundary.

Bars before test_start are passed as feature warm-up context. BacktestEngine
computes features on them but scores no equity points and processes no orders
until the configured test boundary. Warm-up context is not OOS coverage.

M11 Analytics and M12 Validation are run for each test result. Aggregate OOS
equity starts at 1.0 and chains within-window equity ratios across
non-overlapping test windows. Reset-window opening marks do not create
artificial zero returns. M11 computes aggregate return, drawdown, volatility,
Sharpe and Sortino over the chained path; window Sharpe/CAGR are never
averaged. Gaps count omitted bars in the supplied union timestamp timeline.
If test windows overlap, duplicate observations are reported and aggregate
performance metrics are withheld.

The report includes SHA-256 hashes for production configuration and supplied
data, window-level analytics and validation findings, coverage, gaps, pending
orders, and deterministic run hash. Caller-supplied data provenance beyond
the verified content fingerprint is not inferred.

M14 does not establish profitability or prove absence of overfitting. It
provides a temporal OOS evaluation framework. Parameters remain fixed rather
than fitted inside training windows; performance depends on historical data
and execution assumptions. Daily bars and next-open execution do not remove
market microstructure uncertainty. Few trades can make window results noisy;
BTC has different temporal and volatility characteristics from SPY and GLD.
Annualization conventions remain provisional. Exchange holidays and missing
market sessions cannot be diagnosed definitively without market calendars.
