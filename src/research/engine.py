"""Standalone deterministic research orchestration over the production engines."""
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Mapping


from src.backtest.sequential import BacktestEngine
from src.analytics import run_analytics
from src.strategy.signals import SignalEngine, load_signal_config
from src.strategy.scale_in import ScaleInEngine, load_scale_in_config
from src.risk.sizing_engine import RiskSizingEngine, load_risk_sizing_config
from src.portfolio.engine import PortfolioEngine, load_portfolio_config
from src.strategy.exits import ExitEngine, load_exit_config
from src.features.engine import FeatureEngine
from src.features.config import load_feature_config
from src.features.regime import RegimeEngine
from src.validation import run_validation
from src.data.config import REPOSITORY_ROOT
from .config import ABLATIONS, SENSITIVITY_GRID
from .models import ResearchExperimentResult, AblationResult, SensitivityResult, ResearchSuiteResult
from .experiments import experiment_id, metric_deltas
from .ablation import overrides as ablation_overrides
from .sensitivity import apply as apply_sensitivity

CONFIG_FILES = ("assets.yaml","features.yaml","regime.yaml","signals.yaml","strategy.yaml",
                "risk.yaml","exits.yaml","portfolio.yaml","backtest.yaml","analytics.yaml","validation.yaml")

def _jsonable(x):
    if isinstance(x, Enum): return x.value
    if isinstance(x, (datetime,date)): return x.isoformat()
    if is_dataclass(x): return {f.name:_jsonable(getattr(x,f.name)) for f in fields(x)}
    if isinstance(x, Mapping): return {str(k):_jsonable(v) for k,v in sorted(x.items(),key=lambda kv:str(kv[0]))}
    if isinstance(x, (tuple,list)): return [_jsonable(v) for v in x]
    return x

def _canonical(x):
    return json.dumps(_jsonable(x), sort_keys=True, separators=(",",":"), allow_nan=False)

def baseline_configuration_hash(root=REPOSITORY_ROOT):
    h=hashlib.sha256()
    for name in CONFIG_FILES:
        path=Path(root)/"config"/name
        raw=path.read_bytes()
        h.update(name.encode()); h.update(b"\0"); h.update(raw); h.update(b"\0")
    return h.hexdigest()

def _configs():
    signal=load_signal_config(); risk=load_risk_sizing_config(); portfolio=load_portfolio_config()
    exits=load_exit_config(); tiers=load_scale_in_config()
    return signal,risk,portfolio,exits,tiers

def _run(data, signal, risk, portfolio, exits, tiers, *, disable_additional_entries=False,
         regime_filter_enabled=True):
    feature=FeatureEngine(load_feature_config())
    regime=RegimeEngine(feature_config=feature.config)
    signals=SignalEngine(signal, regime_engine=regime, feature_config=feature.config)
    scale={a:ScaleInEngine(a, tiers=tiers[a], disable_additional_entries=disable_additional_entries,
                           regime_filter_enabled=regime_filter_enabled) for a in ("SPY","BTC","GLD")}
    return BacktestEngine(feature_engine=feature, signal_engine=signals, risk_engine=RiskSizingEngine(config=risk),
                          portfolio_engine=PortfolioEngine(config=portfolio), exit_engine=ExitEngine(config=exits),
                          scale_in_engines=scale).run(data)

def extract_metrics(result):
    analytics=run_analytics(result)
    validation=run_validation(result)
    multi=validation.scale_in.multi_entry_cycles
    return {
        "final_equity":analytics.final_equity,"total_return":analytics.total_return,"cagr":analytics.cagr,
        "annualized_volatility":analytics.annualized_volatility,"sharpe_ratio":analytics.sharpe_ratio,
        "sortino_ratio":analytics.sortino_ratio,"maximum_drawdown":analytics.maximum_drawdown,
        "filled_trades":analytics.trades.filled_trades,"completed_cycles":analytics.trades.completed_cycles,
        "multi_entry_cycles":multi,"total_transaction_costs":analytics.costs.total,
        "average_gross_exposure":analytics.exposure.average_gross_exposure,
        "maximum_gross_exposure":analytics.exposure.maximum_gross_exposure,
        "turnover_notional":sum(t.notional for t in result.trades),
    }

def _validation_status(report):
    return report.overall_status.value

def _make_result(kind, component, parameter, value, base_value, baseline_hash, config_hash,
                 baseline, current_result, description, result_type=ResearchExperimentResult):
    analytics=run_analytics(current_result)
    validation=run_validation(current_result)
    status="INVALID" if _validation_status(validation)=="FAIL" else "COMPLETED"
    return result_type(experiment_id(kind,component,value,baseline_hash),kind,component,parameter,value,
                       base_value,baseline_hash,config_hash,status,description,analytics,validation,
                       metric_deltas(baseline,current_result))

def run_ablation_suite(data, *, output_path=None):
    return run_research_suite(data, output_path=output_path, include_sensitivity=False)

def run_sensitivity_suite(data, *, output_path=None):
    return run_research_suite(data, output_path=output_path, include_ablations=False)

def run_research_suite(data, *, output_path=None, include_ablations=True, include_sensitivity=True):
    """Run one exact baseline and isolated variants against caller-supplied OHLCV data."""
    if not isinstance(data, Mapping): raise TypeError("data must map assets to validated OHLCV frames.")
    before={n:(REPOSITORY_ROOT/"config"/n).read_bytes() for n in CONFIG_FILES}
    base_hash=baseline_configuration_hash()
    signal,risk,portfolio,exits,tiers=_configs()
    baseline_bt=_run(data,signal,risk,portfolio,exits,tiers)
    baseline_analytics=run_analytics(baseline_bt); baseline_validation=run_validation(baseline_bt)
    baseline=ResearchExperimentResult("baseline-"+base_hash[:24],"BASELINE","production",None,None,None,
        base_hash,base_hash,"INVALID" if _validation_status(baseline_validation)=="FAIL" else "COMPLETED",
        "Exact production YAML configuration",baseline_analytics,
        baseline_validation,(),baseline_bt)
    ablations=[]; sensitivities=[]
    if include_ablations:
        for component,description in ABLATIONS:
            overrides=ablation_overrides(component,signal,risk,portfolio,exits)
            s,r,p,e=signal,risk,portfolio,exits
            disabled=False; regime_on=True
            if overrides:
                s=overrides.get("signal",s); r=overrides.get("risk",r)
                p=overrides.get("portfolio",p); e=overrides.get("exits",e)
                disabled=overrides.get("disable_additional_entries",False)
                regime_on=overrides.get("regime_filter_enabled",True)
                bt=_run(data,s,r,p,e,tiers,disable_additional_entries=disabled,regime_filter_enabled=regime_on)
                cfg_hash=hashlib.sha256((base_hash+_canonical([component,"disabled"])).encode()).hexdigest()
                ablations.append(_make_result("ABLATION",component,None,"disabled","enabled",base_hash,
                                              cfg_hash,baseline_bt,bt,description,AblationResult))
            else:
                ablations.append(AblationResult(experiment_id("ABLATION",component,"unsupported",base_hash),
                    "ABLATION",component,None,"unsupported",None,base_hash,base_hash,"NOT_SUPPORTED",
                    description,None,None,()))
    if include_sensitivity:
        for parameter,baseline_value,values in SENSITIVITY_GRID:
            for value in values:
                s,r,e,t=apply_sensitivity(parameter,value,signal,risk,exits,tiers)
                bt=_run(data,s,r,portfolio,e,t)
                cfg_hash=hashlib.sha256((base_hash+_canonical([parameter,value])).encode()).hexdigest()
                sensitivities.append(_make_result("SENSITIVITY",parameter,parameter,value,baseline_value,
                    base_hash,cfg_hash,baseline_bt,bt,f"One-factor perturbation of {parameter}",SensitivityResult))
    if any((REPOSITORY_ROOT/"config"/n).read_bytes()!=raw for n,raw in before.items()):
        raise RuntimeError("Production YAML changed during research execution.")
    payload={"baseline":baseline,"ablations":tuple(ablations),"sensitivities":tuple(sensitivities)}
    report=json.dumps(_jsonable(payload),sort_keys=True,indent=2,allow_nan=False)
    suite=ResearchSuiteResult(base_hash,baseline,tuple(ablations),tuple(sensitivities),report)
    report_path = Path(output_path) if output_path is not None else REPOSITORY_ROOT/"data"/"processed"/"research_suite.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report+"\n",encoding="utf-8")
    return suite
