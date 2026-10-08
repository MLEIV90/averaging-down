from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import run_backtest
from src.backtest.sequential import BacktestConfig, BacktestResult, PortfolioPoint
from src.research.walk_forward import WalkForwardConfig, build_windows, run_walk_forward
from src.research.walk_forward.aggregation import aggregate_oos
from src.research.walk_forward.models import WalkForwardWindowResult
from src.research.walk_forward.splits import ordered_timeline


def wf_config(**changes):
    values=dict(mode="expanding",train_bars=10,validation_bars=5,test_bars=5,step_bars=5,
                embargo_bars=0,minimum_train_bars=5,minimum_validation_bars=2,
                minimum_test_bars=2,warmup_bars=4)
    values.update(changes)
    return WalkForwardConfig(**values)

def bars(count=40, *, start="2020-01-01"):
    index=pd.date_range(start,periods=count,freq="D",tz="UTC")
    close=100 + np.arange(count,dtype=float)*0.1
    return pd.DataFrame({"open":close,"high":close+1,"low":close-1,"close":close,"volume":1000.0},index=index)

def test_expanding_boundaries_step_and_deterministic_manifest():
    timeline=ordered_timeline({"SPY":bars()})
    first=build_windows(timeline,wf_config(),"cfg")
    second=build_windows(timeline,wf_config(),"cfg")
    assert first == second
    assert first[0].train_start == timeline[0].to_pydatetime()
    assert first[0].train_end < first[0].validation_start <= first[0].validation_end < first[0].test_start
    assert first[1].train_start == first[0].train_start
    assert first[1].train_bars > first[0].train_bars
    assert first[1].test_start == timeline[20].to_pydatetime()
    with pytest.raises(ValueError,match="boundaries"):
        replace(first[0],test_start=first[0].validation_end)

def test_rolling_window_has_fixed_train_length():
    windows=build_windows(ordered_timeline({"SPY":bars()}),wf_config(mode="rolling"),"cfg")
    assert all(w.train_bars == 10 for w in windows)
    assert windows[1].train_start > windows[0].train_start

def test_embargo_zero_positive_and_overlap_configuration():
    timeline=ordered_timeline({"SPY":bars()})
    no_embargo=build_windows(timeline,wf_config(),"cfg")[0]
    assert no_embargo.embargo_start is None
    positive=build_windows(timeline,wf_config(embargo_bars=2),"cfg")[0]
    assert positive.validation_end < positive.embargo_start <= positive.embargo_end < positive.test_start
    with pytest.raises(ValueError,match="step_bars"):
        wf_config(test_bars=6,step_bars=5)

def test_minimum_data_and_invalid_configuration_rejected():
    with pytest.raises(ValueError,match="Insufficient"):
        build_windows(ordered_timeline({"SPY":bars(16)}),wf_config(),"cfg")
    with pytest.raises(ValueError,match="reset_state"):
        wf_config(reset_state_each_test_window=False)
    with pytest.raises(ValueError,match="embargo_bars"):
        wf_config(embargo_bars=-1)

def test_timezone_validation_and_utc_normalization():
    utc=bars(30)
    shifted=utc.copy()
    shifted.index=shifted.index.tz_convert("America/New_York")
    assert len(ordered_timeline({"SPY":shifted})) == len(utc)
    naive=utc.copy(); naive.index=naive.index.tz_localize(None)
    with pytest.raises(ValueError,match="timezone-aware"):
        ordered_timeline({"SPY":naive})

def test_warmup_context_is_not_scored_and_windows_reset_accounting(tmp_path):
    result=run_walk_forward({"SPY":bars()},config=wf_config(),
                            report_path=tmp_path/"walk_forward.json")
    assert len(result.windows) > 1
    assert all(row.analytics.trades.filled_trades == 0 for row in result.windows)
    assert result.aggregate_oos.windows_with_zero_trades == result.window_count
    for row in result.windows:
        points=row.test_backtest.portfolio_curve
        assert points[0].timestamp == row.window.test_start
        assert all(p.timestamp >= row.window.test_start for p in points)
        assert all(t.signal_timestamp >= row.window.test_start for t in row.test_backtest.trades)
        assert points[0].cash == row.test_backtest.configuration.initial_capital
        assert row.window.warmup_start < row.window.test_start
        assert row.pending_orders == row.test_backtest.pending_orders
        assert row.validation is not None
    assert result.report_json == (tmp_path/"walk_forward.json").read_text(encoding="utf-8").strip()

def test_backtest_evaluation_bounds_preserve_warmup_and_reject_naive_bounds():
    frame=bars(35)
    result=run_backtest({"SPY":frame},evaluation_start=frame.index[20],evaluation_end=frame.index[25])
    assert [p.timestamp for p in result.portfolio_curve] == list(frame.index[20:26].to_pydatetime())
    with pytest.raises(ValueError,match="timezone-aware"):
        run_backtest({"SPY":frame},evaluation_start=frame.index[20].tz_localize(None))

def test_future_bars_do_not_change_prior_oos_results():
    frame=bars(35)
    future_changed=frame.copy()
    future_changed.iloc[26:,future_changed.columns.get_loc("close")] *= 4
    future_changed.iloc[26:,future_changed.columns.get_loc("high")] *= 4
    future_changed.iloc[26:,future_changed.columns.get_loc("low")] *= 4
    future_changed.iloc[26:,future_changed.columns.get_loc("open")] *= 4
    kwargs={"evaluation_start":frame.index[20],"evaluation_end":frame.index[25]}
    left=run_backtest({"SPY":frame},**kwargs)
    right=run_backtest({"SPY":future_changed},**kwargs)
    assert left == right

def test_aggregation_chains_window_returns_and_reports_gaps_and_duplicates():
    timeline=ordered_timeline({"SPY":bars(30)})
    config=wf_config(train_bars=5,validation_bars=3,test_bars=3,step_bars=5,
                     minimum_train_bars=3,minimum_validation_bars=2,minimum_test_bars=2,
                     warmup_bars=3,require_non_overlapping_tests=False)
    windows=build_windows(timeline,config,"cfg")
    def window_result(window, equity_values):
        points=tuple(PortfolioPoint(window.test_start + pd.Timedelta(days=i),100,0,value,0,0,0,0,0)
                     for i,value in enumerate(equity_values))
        bt=BacktestResult(points,(),(),(),(),(),0,BacktestConfig(initial_capital=100))
        return WalkForwardWindowResult(window,"COMPLETED",bt,None,None)
    rows=[window_result(w,[100,110,121]) for w in windows[:2]]
    aggregate=aggregate_oos(rows,timeline)
    assert aggregate.analytics.total_return == pytest.approx(1.21*1.21-1)
    assert aggregate.unique_oos_observations == 6
    assert aggregate.gaps[0].missing_input_bars == 2
    overlapping=build_windows(timeline,wf_config(train_bars=5,validation_bars=3,test_bars=5,
        step_bars=3,minimum_train_bars=3,minimum_validation_bars=2,minimum_test_bars=2,
        warmup_bars=3,require_non_overlapping_tests=False),"cfg")
    dup=aggregate_oos([window_result(w,[100]*5) for w in overlapping[:2]],timeline)
    assert dup.duplicate_oos_observations > 0 and dup.analytics is None

def test_dataset_fingerprint_and_full_run_are_deterministic(tmp_path):
    from src.research.walk_forward.engine import _configuration_snapshot
    before=_configuration_snapshot()
    frame=bars(35)
    first=run_walk_forward({"SPY":frame},config=wf_config(),report_path=tmp_path/"first.json")
    second=run_walk_forward({"SPY":frame.copy()},config=wf_config(),report_path=tmp_path/"second.json")
    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert first.deterministic_run_hash == second.deterministic_run_hash
    assert first.report_json == second.report_json
    assert first.configuration_consistent
    assert first.invalid_windows == ()
    assert before == _configuration_snapshot()
    changed=frame.copy()
    changed.iloc[0,changed.columns.get_loc("close")] += 1
    from src.research.walk_forward.engine import dataset_fingerprint
    assert dataset_fingerprint({"SPY":frame}) != dataset_fingerprint({"SPY":changed})

def test_configuration_mutation_is_detected_without_dropping_windows(monkeypatch,tmp_path):
    from src.research.walk_forward import engine
    original=engine._configuration_snapshot()
    calls=[]
    def snapshots():
        calls.append(1)
        if len(calls)==1:
            return original
        return {name:value+b" changed" for name,value in original.items()}
    monkeypatch.setattr(engine,"_configuration_snapshot",snapshots)
    result=engine.run_walk_forward({"SPY":bars(20)},config=wf_config(),report_path=tmp_path/"mutated.json")
    assert not result.configuration_consistent
    assert result.window_count == 1
    assert result.invalid_windows == ("wf-0001",)
    assert any("configuration hash/bytes changed" in e for e in result.windows[0].errors)

def test_pending_orders_are_reported_not_filled_outside_window(monkeypatch,tmp_path):
    from src.execution.orders import Order, OrderStatus
    from src.backtest.sequential import OrderRecord
    from datetime import datetime, timezone
    from src.research.walk_forward import engine
    from src.validation.models import OverallStatus
    signal_time=datetime(2020,1,1,tzinfo=timezone.utc)
    order=Order("id","SPY","BUY",1,"MARKET",signal_time,signal_time,signal_time,OrderStatus.PROPOSED)
    pending=OrderRecord(order,"BUY_T1","boundary", "T1",100,None,"PENDING",1,1)
    fake=BacktestResult((),(),(pending,),(pending,),(),(),0,BacktestConfig(initial_capital=100))
    seen=[]
    def fake_backtest(data,**kwargs):
        seen.append(kwargs)
        return fake
    monkeypatch.setattr(engine,"run_backtest",fake_backtest)
    original_validation=engine.run_validation
    monkeypatch.setattr(engine,"run_validation",lambda result: replace(
        original_validation(result),overall_status=OverallStatus.FAIL))
    frame=bars(35)
    result=engine.run_walk_forward({"SPY":frame},config=wf_config(),report_path=tmp_path/"pending.json")
    assert all(row.pending_orders == (pending,) for row in result.windows)
    assert all(row.test_backtest.trades == () for row in result.windows)
    assert all(row.status == "INVALID" and row.validation.overall_status == OverallStatus.FAIL
               for row in result.windows)
    assert all(any("overall FAIL" in error for error in row.errors) for row in result.windows)
    assert len(seen) == result.window_count
    assert all(call["evaluation_end"] <= row.window.test_end for call,row in zip(seen,result.windows))
