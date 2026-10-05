import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(page_title="Sequential Backtest", layout="wide")
st.title("Sequential Backtest")

summary_path = Path("data/processed/backtest_summary.json")
equity_path = Path("data/processed/equity_curve.csv")
cash_path = Path("data/processed/cash_curve.csv")

if not summary_path.exists() or not equity_path.exists():
    st.info("Run `python -m scripts.run_backtest` to create sequential backtest results.")
    st.stop()

summary = json.loads(summary_path.read_text(encoding="utf-8"))
columns = st.columns(5)
columns[0].metric("Initial equity", f"{summary['initial_equity']:.2f}")
columns[1].metric("Final equity", f"{summary['final_equity']:.2f}")
columns[2].metric("Filled trades", str(summary["filled_trade_count"]))
columns[3].metric("Pending orders", str(summary["pending_order_count"]))
columns[4].metric("Transaction costs", f"{summary['total_transaction_costs']:.2f}")

equity = pd.read_csv(equity_path, index_col="Date", parse_dates=True)
fig = go.Figure()
fig.add_trace(go.Scatter(x=equity.index, y=equity["Equity"], mode="lines", name="Equity"))
if cash_path.exists():
    cash = pd.read_csv(cash_path, index_col="Date", parse_dates=True)
    fig.add_trace(go.Scatter(x=cash.index, y=cash["Cash"], mode="lines", name="Cash"))
fig.update_layout(title="Sequential portfolio history", yaxis_title="Portfolio value",
                  xaxis_title="UTC session-date label", height=500, hovermode="x unified")
st.plotly_chart(fig, width="stretch")

st.caption(
    "Next available bar open execution. Backtest implementation validity does not imply "
    "strategy profitability or financial validity."
)
