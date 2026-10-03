import json

from src.data.config import REPOSITORY_ROOT, load_assets_config
from src.data.engine import DataEngine
from src.features.engine import FeatureEngine
from src.features.regime import detect_market_regime, is_panic
from src.risk.position_sizing import get_dynamic_allocation
from src.strategy.exits import evaluate_exit
from src.strategy.scale_in import ScaleInEngine


def run():
    configured_assets, _ = load_assets_config()
    assets = [ticker for ticker, config in configured_assets.items() if config.enabled]
    data_engine = DataEngine()
    feature_engine = FeatureEngine()
    signals = []

    state_file = REPOSITORY_ROOT / "data" / "processed" / "portfolio_state.json"
    portfolio_state = {}
    if state_file.exists():
        with state_file.open("r", encoding="utf-8") as file:
            portfolio_state = json.load(file)
    state_file.parent.mkdir(parents=True, exist_ok=True)

    for ticker in assets:
        df = feature_engine.compute(data_engine.load_or_download(ticker, allow_download=True))
        if df.empty:
            continue

        regime = detect_market_regime(df, feature_engine.config)
        panic = is_panic(df, feature_engine.config)
        asset_state = portfolio_state.get(ticker, {})
        current_tier = asset_state.get("Target_Tier", "FLAT")
        last_z = asset_state.get("Last_Z_ATR", 0.0)
        avg_price = asset_state.get("Avg_Buy_Price", 0.0)
        strategy_engine = ScaleInEngine(
            ticker.replace("-USD", ""),
            config_path=REPOSITORY_ROOT / "config" / "strategy.yaml",
            initial_state=current_tier,
            last_z_atr=last_z,
        )

        last_close = float(df["close"].iloc[-1])
        last_d_atr = float(df["z_atr"].iloc[-1])
        last_ema20 = float(df[f"ema{feature_engine.config.ema_fast}"].iloc[-1])
        realized_vol_period = 10 if 10 in feature_engine.config.realized_vol_windows else feature_engine.config.realized_vol_period
        realized_vol = float(df[f"realized_vol_{realized_vol_period}"].iloc[-1])

        action, new_state = strategy_engine.get_action(last_d_atr, regime, panic)
        exit_action, reason = evaluate_exit(
            ticker, last_close, last_ema20, float(df[f"rsi{feature_engine.config.rsi_period}"].iloc[-1]),
            avg_price, float(df[f"atr{feature_engine.config.atr_period}"].iloc[-1]), new_state,
        )
        final_action = action if action != "HOLD" else exit_action
        if final_action == "FULL_RESET":
            new_state = "FLAT"
            strategy_engine.last_z_atr = 0.0
            avg_price = 0.0

        base_pct = 0.10 if "T1" in final_action else (0.15 if "T2" in final_action else (0.20 if "T3" in final_action else 0.0))
        alloc_pct = get_dynamic_allocation(base_pct, 0.15, realized_vol) if base_pct > 0 else 0.0
        signals.append({
            "Ticker": ticker,
            "Close": last_close,
            "Regime": regime,
            "D_ATR": last_d_atr,
            "Action": final_action,
            "Target_Tier": new_state,
            "Suggested_Alloc_Pct": alloc_pct,
            "Reason": reason if final_action != "HOLD" and "BUY" not in final_action else ("TIER_ENTRY" if "BUY" in final_action else "NONE"),
        })
        portfolio_state[ticker] = {
            "Target_Tier": new_state,
            "Last_Z_ATR": float(strategy_engine.last_z_atr),
            "Avg_Buy_Price": last_close if "BUY" in final_action and avg_price == 0 else avg_price,
            "Regime": regime,
            "Close": last_close,
            "Action": final_action,
            "Realized_Vol": realized_vol,
        }

    print(json.dumps(signals, indent=2))
    with (REPOSITORY_ROOT / "data" / "processed" / "latest_signals.json").open("w", encoding="utf-8") as file:
        json.dump(signals, file, indent=2)
    with state_file.open("w", encoding="utf-8") as file:
        json.dump(portfolio_state, file, indent=2)


if __name__ == "__main__":
    run()
