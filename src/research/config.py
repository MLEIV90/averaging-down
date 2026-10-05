"""Explicit diagnostics loaded from the dedicated research YAML."""
import yaml
from src.data.config import REPOSITORY_ROOT

_raw = yaml.safe_load((REPOSITORY_ROOT / "config" / "research.yaml").read_text(encoding="utf-8"))["research"]
_descriptions = {
    "regime_filter":"Disable trend regime eligibility",
    "rsi2_filter":"Remove the RSI2 entry requirement",
    "reversal_confirmation":"Remove close-location/reversal confirmation",
    "scale_in":"Disable T2/T3 additional entries while retaining T1",
    "volatility_sizing":"Disable volatility adjustment while retaining base sizing",
    "portfolio_constraints":"Disable configured portfolio allocation limits",
    "partial_recovery_exit":"Disable partial recovery exits",
    "time_stop":"Disable time stops",
    "structural_stop":"Disable structural stops",
}
ABLATIONS = tuple((name, _descriptions[name]) for name in _raw["ablations"])
SENSITIVITY_GRID = tuple((row[0], row[1], tuple(row[2])) for row in _raw["sensitivity_grid"])
