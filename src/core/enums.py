from enum import Enum

class AssetClass(str, Enum):
    EQUITY = "equity"
    COMMODITY = "commodity"
    CRYPTO = "crypto"

class MarketRegime(str, Enum):
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    BEAR = "BEAR"

class CycleState(str, Enum):
    FLAT = "FLAT"
    T1_ACTIVE = "T1_ACTIVE"
    T2_ACTIVE = "T2_ACTIVE"
    T3_ACTIVE = "T3_ACTIVE"
    DE_RISK = "DE_RISK"
    RESET = "RESET"

class ActionType(str, Enum):
    BUY_TIER = "BUY_TIER"
    PARTIAL_DE_RISK = "PARTIAL_DE_RISK"
    FULL_EXIT = "FULL_EXIT"
    HOLD = "HOLD"
