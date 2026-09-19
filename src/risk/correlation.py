import pandas as pd

def calculate_rolling_correlation(df, window=60):
    """Calcula correlación rodante de 60 días entre activos."""
    return df.rolling(window=window).corr()

def get_correlation_penalty(corr_matrix, drawdown_df, threshold=0.65):
    """
    Si la correlación entre activos > threshold durante drawdowns, 
    retorna un factor de reducción.
    """
    # Simplificación: si la correlación media de los activos > threshold, penalizar
    avg_corr = corr_matrix.mean().mean()
    if avg_corr > threshold and drawdown_df.min() < -0.05:
        return 0.8  # Reducir tamaño al 80%
    return 1.0
