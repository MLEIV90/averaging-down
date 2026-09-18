def correlation_matrix(returns,window=60):
    return returns.rolling(window).corr()
