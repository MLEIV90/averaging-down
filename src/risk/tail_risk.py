def historical_var(returns,alpha=0.05): return returns.quantile(alpha)
def historical_es(returns,alpha=0.05):
    var=historical_var(returns,alpha); tail=returns[returns<=var]; return tail.mean()
