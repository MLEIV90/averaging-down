from dataclasses import dataclass
@dataclass
class PositionState:
    cycle_active: bool=False
    last_tier: str="NONE"
    anchor_price: float|None=None
    lowest_price: float|None=None
    position_weight: float=0.0
    partial_sell_stage: int=0
class StateMachine:
    def __init__(self): self.states={}
    def get(self,asset):
        if asset not in self.states: self.states[asset]=PositionState()
        return self.states[asset]
