from src.strategy.scale_in import determine_tier
TIERS=[{"name":"T1","z_atr":-1.5},{"name":"T2","z_atr":-2.25},{"name":"T3","z_atr":-3.0}]
def test_no_tier(): assert determine_tier(-1.0,TIERS)=="NONE"
def test_t1(): assert determine_tier(-1.6,TIERS)=="T1"
def test_t3(): assert determine_tier(-3.5,TIERS)=="T3"
