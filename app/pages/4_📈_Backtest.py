import streamlit as st
import pandas as pd
import json
import plotly.graph_objects as go

st.title("📈 Backtest")

try:
    with open('data/processed/backtest_results.json', 'r') as f:
        metrics = json.load(f)
    
    # Display metrics
    cols = st.columns(len(metrics))
    for i, (k, v) in enumerate(metrics.items()):
        cols[i].metric(k, f"{v:.2%}" if isinstance(v, float) else f"{v:.2f}")

except Exception as e:
    st.error(f"Error loading backtest results: {e}")
