def determine_tier(z_atr, tiers):
    reached="NONE"
    for tier in tiers:
        if z_atr<=tier["z_atr"]: reached=tier["name"]
    return reached
