import numpy as np
def portfolio_volatility(weights,covariance):
    w=np.asarray(weights,float); cov=np.asarray(covariance,float)
    return float(np.sqrt(w@cov@w))
