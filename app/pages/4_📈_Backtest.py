import streamlit as st
import pandas as pd
import json
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="Backtest Analytics", layout="wide")
st.title("📈 Backtest Analytics")

metrics_path = Path('data/processed/backtest_metrics.json')
equity_path = Path('data/processed/equity_curve.csv')

# 1. Tarjetas de Métricas (KPIs)
if metrics_path.exists():
    with open(metrics_path, 'r') as f:
        metrics = json.load(f)
        
    if metrics and len(metrics) > 0:
        cols = st.columns(len(metrics))
        for i, (k, v) in enumerate(metrics.items()):
            # Formateo porcentual inteligente
            if any(term in k.lower() for term in ['cagr', 'drawdown', 'rate', 'win']):
                val = f"{v:.2%}"
            else:
                val = f"{v:.2f}"
            cols[i].metric(k, val)
    else:
        st.warning("El diccionario de métricas está vacío.")
else:
    st.info("Ejecuta 'python scripts/run_backtest.py' para generar los resultados.")

st.markdown("---")

# 2. Gráfico de Curva de Capital (Equity Curve)
if equity_path.exists():
    equity_df = pd.read_csv(equity_path, index_col='Date', parse_dates=True)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity_df.index, y=equity_df['Equity'],
        mode='lines', name='Strategy Equity',
        line=dict(color='#00F0FF', width=2),
        fill='tozeroy', fillcolor='rgba(0, 240, 255, 0.1)'
    ))
    
    fig.update_layout(
        title="Cumulative Strategy Returns",
        yaxis_title="Capital Múltiple",
        xaxis_title="Fecha",
        height=600,
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=0, r=0, t=40, b=0)
    )
    st.plotly_chart(fig, width='stretch')