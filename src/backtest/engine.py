import pandas as pd
from src.strategy.scale_in import ScaleInEngine
from src.strategy.exits import evaluate_exit

def run_backtest(data_dict):
    """
    Simulación histórica.
    data_dict: dict de {ticker: df}
    """
    # Simplificación: backtest secuencial
    equity = pd.Series(1.0, index=data_dict['SPY'].index)
    
    # Lógica de simulación barra a barra...
    # (En una implementación real aquí iría el motor de simulación)
    
    return equity
