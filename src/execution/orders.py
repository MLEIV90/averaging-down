from dataclasses import dataclass
@dataclass
class Order:
    asset: str
    side: str
    quantity: float
    order_type: str="PAPER"
def create_paper_order(asset,side,quantity): return Order(asset,side,quantity)
