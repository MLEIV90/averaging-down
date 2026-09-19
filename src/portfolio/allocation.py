def get_allocation_caps():
    """
    Retorna los hard caps de asignación configurados.
    """
    return {
        "SPY": 0.35,
        "GLD": 0.25,
        "BTC-USD": 0.10,
        "CASH": 0.30
    }

def validate_allocation(current_allocation):
    """
    Valida si la asignación actual respeta los límites.
    """
    caps = get_allocation_caps()
    for asset, weight in current_allocation.items():
        if weight > caps.get(asset, 0):
            return False
    return True
