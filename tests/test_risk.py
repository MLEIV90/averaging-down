from src.risk.position_sizing import volatility_multiplier,risk_based_units
def test_volatility_multiplier(): assert volatility_multiplier(.15,.15)==1.0
def test_risk_units(): assert risk_based_units(100,5)==20
