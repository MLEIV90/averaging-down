from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from src.core.enums import MarketRegime, CycleState, ActionType

@dataclass
class MarketFeatures:
    asset: str
    timestamp: datetime
    price: float
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    ema200: Optional[float] = None
    atr14: Optional[float] = None
    rsi2: Optional[float] = None
    z_atr: Optional[float] = None
    realized_vol: Optional[float] = None
    drawdown: Optional[float] = None

@dataclass
class Decision:
    asset: str
    timestamp: datetime
    action: str = "HOLD"
    regime: str = "NEUTRAL"
    tier: str = "NONE"
    reason: str = ""
    target_weight: float = 0.0
    risk_budget: float = 0.0
    position_size: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class BarData:
    asset: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass
class CycleStatus:
    asset: str
    state: CycleState = CycleState.FLAT
    entry_price: float = 0.0
    current_tier: int = 0
    units: float = 0.0
    unrealized_pnl: float = 0.0
    peak_price: float = 0.0

@dataclass
class SignalOutput:
    asset: str
    timestamp: datetime
    action: ActionType = ActionType.HOLD
    regime: MarketRegime = MarketRegime.NEUTRAL
    tier: int = 0
    price: float = 0.0
    reason: str = ""
