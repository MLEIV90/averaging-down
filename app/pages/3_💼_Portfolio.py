import streamlit as st
import pandas as pd
import json
from pathlib import Path

st.set_page_config(page_title="Portfolio Management", layout="wide")
st.title("💼 Portfolio Management")

INITIAL_CAPITAL = 1100.0
state_path = Path('data/processed/portfolio_state.json')

if not state_path.exists():
    st.info("No hay estado de portfolio activo. Ejecuta 'python scripts/run_eod.py'.")
    st.stop()

with open(state_path, 'r') as f:
    portfolio_state = json.load(f)

if not portfolio_state:
    st.warning("El estado del portfolio está vacío.")
    st.stop()

df_state = pd.DataFrame.from_dict(portfolio_state, orient='index')

# Inyección segura de columnas esperadas para evitar KeyError
expected_cols = ['Regime', 'Target_Tier', 'Last_Z_ATR', 'Realized_Vol', 'Avg_Buy_Price', 'Action']
for col in expected_cols:
    if col not in df_state.columns:
        df_state[col] = 0.0 if col in ['Last_Z_ATR', 'Realized_Vol', 'Avg_Buy_Price'] else "N/A"

active_positions = df_state[df_state['Target_Tier'] != 'FLAT']

col1, col2, col3 = st.columns(3)
col1.metric("Capital Base de Asignación", f"€{INITIAL_CAPITAL:,.2f}")
col2.metric("Líneas de Activos Abiertas", len(active_positions))
col3.metric("Régimen Dominante", df_state['Regime'].mode()[0] if not df_state.empty else "NEUTRAL")

st.markdown("### 📊 Monitor de Estado de Escala (Scale-in Engine)")

st.dataframe(
    df_state[expected_cols].style.format({
        'Last_Z_ATR': '{:.2f}',
        'Realized_Vol': '{:.2%}',
        'Avg_Buy_Price': '${:.2f}'
    }, na_rep="-"),
    use_container_width=True
)