from dataclasses import dataclass
@dataclass
class CapitalState:
    total_capital: float
    cash: float
    invested: float
class CapitalDeploymentEngine:
    def __init__(self,min_cash_reserve=0.30,max_deployment=0.70):
        self.min_cash_reserve=min_cash_reserve; self.max_deployment=max_deployment
    def maximum_deployable(self,total_capital):
        return total_capital*self.max_deployment
