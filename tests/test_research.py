from src.research.engine import baseline_configuration_hash, run_research_suite
from src.research.experiments import experiment_id
from src.research.sensitivity import apply
from src.research.config import SENSITIVITY_GRID
from src.research.ablation import overrides
from src.research.models import ResearchMetricDelta
from src.research.experiments import metric_deltas
from src.analytics.models import AnalyticsReport
from src.backtest.sequential import BacktestResult
from src.strategy.signals import SignalConfig
from src.strategy.exits import load_exit_config
from src.risk.sizing_engine import load_risk_sizing_config
from src.strategy.scale_in import load_scale_in_config
import pandas as pd
import pytest

def test_baseline_hash_and_experiment_ids_are_deterministic():
    assert baseline_configuration_hash() == baseline_configuration_hash()
    assert experiment_id('ABLATION','scale_in','disabled','abc') == experiment_id('ABLATION','scale_in','disabled','abc')

def test_sensitivity_changes_one_factor_and_preserves_negative_z_order():
    signal=SignalConfig(); risk=load_risk_sizing_config(); exits=load_exit_config(); tiers=load_scale_in_config()
    before=(signal,risk,exits,tiers)
    parameter,_,values=SENSITIVITY_GRID[0]
    s,r,e,t=apply(parameter,values[0],signal,risk,exits,tiers)
    assert s == signal and r == risk and e == exits
    assert sum(a != b for a,b in zip(before,(s,r,e,t))) == 1
    assert t['SPY'][0].z_atr > t['SPY'][1].z_atr > t['SPY'][2].z_atr

def test_invalid_sensitivity_values_are_rejected():
    with pytest.raises(ValueError):
        apply('exits.partial_recovery.rsi2_threshold',-1,SignalConfig(),load_risk_sizing_config(),load_exit_config(),load_scale_in_config())
    with pytest.raises(ValueError):
        apply('risk.risk_budget_fraction',-0.01,SignalConfig(),load_risk_sizing_config(),load_exit_config(),load_scale_in_config())

def test_each_ablation_override_changes_one_component_only():
    signal=SignalConfig(); risk=load_risk_sizing_config()
    from src.portfolio.engine import load_portfolio_config
    portfolio=load_portfolio_config(); exits=load_exit_config()
    for component in ('regime_filter','rsi2_filter','reversal_confirmation'):
        item=overrides(component,signal,risk,portfolio,exits)
        changed=[name for name in ('signal','risk','portfolio','exits')
                 if item.get(name,{'signal':signal,'risk':risk,'portfolio':portfolio,'exits':exits}[name])
                 != {'signal':signal,'risk':risk,'portfolio':portfolio,'exits':exits}[name]]
        assert changed == ['signal']
    assert overrides('unknown',signal,risk,portfolio,exits) is None

def test_no_timestamp_and_no_combined_parameter_experiment_ids():
    assert experiment_id('SENSITIVITY','rsi.threshold',10,'hash') == experiment_id('SENSITIVITY','rsi.threshold',10,'hash')
    assert '2026' not in experiment_id('SENSITIVITY','rsi.threshold',10,'hash')
    signal=SignalConfig(); risk=load_risk_sizing_config(); exits=load_exit_config(); tiers=load_scale_in_config()
    s,r,e,t=apply('signals.rsi2_entry_threshold',9,signal,risk,exits,tiers)
    assert r == risk and e == exits and t == tiers and s != signal

def test_metric_differences_have_absolute_and_relative_values():
    from dataclasses import dataclass
    @dataclass
    class Trade: filled_trades=0; completed_cycles=0
    @dataclass
    class Exposure: average_gross_exposure=0; maximum_gross_exposure=0
    @dataclass
    class Costs: total=0
    @dataclass
    class Analytics:
        final_equity=100; total_return=0; cagr=0; annualized_volatility=0
        sharpe_ratio=None; sortino_ratio=None; maximum_drawdown=-.2
        trades=Trade(); exposure=Exposure(); costs=Costs()
    @dataclass
    class Validation: scale_in=type('Scale',(),{'multi_entry_cycles':0})()
    class Result: trades=()
    import src.research.engine as engine
    original_a,original_v=engine.run_analytics,engine.run_validation
    try:
        engine.run_analytics=lambda _:Analytics()
        engine.run_validation=lambda _:Validation()
        values=metric_deltas(Result(),Result())
        dd=next(x for x in values if x.metric=='maximum_drawdown')
        assert dd.absolute_difference == 0 and dd.relative_difference == 0
        zero=ResearchMetricDelta('zero',0,1,1,None)
        assert zero.relative_difference is None
    finally:
        engine.run_analytics,engine.run_validation=original_a,original_v

def test_suite_preserves_yaml_and_is_repeatable(monkeypatch,tmp_path):
    import src.research.engine as engine
    monkeypatch.setattr(engine,'ABLATIONS',(('rsi2_filter','test'),))
    monkeypatch.setattr(engine,'SENSITIVITY_GRID',())
    idx=pd.date_range('2020-01-01',periods=45,tz='UTC')
    close=pd.Series([100.0+i*.05 for i in range(len(idx))],index=idx)
    frame=pd.DataFrame({'open':close,'high':close+1,'low':close-1,'close':close,'volume':1000},index=idx)
    raw={p.name:p.read_bytes() for p in (engine.REPOSITORY_ROOT/'config').glob('*.yaml')}
    first=run_research_suite({'SPY':frame},output_path=tmp_path/'one.json',include_sensitivity=False)
    second=run_research_suite({'SPY':frame},output_path=tmp_path/'two.json',include_sensitivity=False)
    assert first.report_json == second.report_json
    assert (tmp_path/'one.json').read_bytes() == (tmp_path/'two.json').read_bytes()
    assert first.ablations[0].validation is not None
    assert isinstance(first.baseline.backtest_result,BacktestResult)
    assert isinstance(first.baseline.analytics,AnalyticsReport)
    assert first.ablations[0].baseline_configuration_hash == first.baseline_configuration_hash
    assert first.ablations[0].experiment_id == second.ablations[0].experiment_id
    assert raw == {p.name:p.read_bytes() for p in (engine.REPOSITORY_ROOT/'config').glob('*.yaml')}
