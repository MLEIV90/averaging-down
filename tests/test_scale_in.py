from src.strategy.scale_in import ScaleInEngine

def test_scale_in_state_machine():
    # SPY: T1 <= -1.5, T2 <= -2.25, T3 <= -3.0
    engine = ScaleInEngine("SPY", config_path="config/strategy.yaml")
    
    # Test reaching T1
    action, state = engine.get_action(d_atr=-1.6, regime='NEUTRAL', is_panic=False)
    assert state == 'T1_ACTIVE'
    assert action == 'BUY_T1'
    
    # Try to reach T2
    action, state = engine.get_action(d_atr=-2.3, regime='NEUTRAL', is_panic=False)
    assert state == 'T2_ACTIVE'
    assert action == 'BUY_T2'
    
    # Now T3
    action, state = engine.get_action(d_atr=-3.1, regime='NEUTRAL', is_panic=False)
    assert state == 'T3_ACTIVE'
    assert action == 'BUY_T3'
