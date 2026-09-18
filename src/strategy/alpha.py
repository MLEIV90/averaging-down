from src.core.models import Decision
def evaluate_alpha(asset,row):
    ts=row.name.to_pydatetime() if hasattr(row.name,"to_pydatetime") else row.name
    return Decision(asset=asset,timestamp=ts,action="HOLD",regime=str(row.get("Regime","NEUTRAL")),reason="Alpha engine not yet validated.")
