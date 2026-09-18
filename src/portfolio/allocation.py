def normalize_weights(weights):
    total=sum(max(0,x) for x in weights.values())
    return {k:(max(0,v)/total if total else 0.0) for k,v in weights.items()}
