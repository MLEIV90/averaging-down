import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from src.data.config import load_assets_config
from src.data.engine import DataEngine
from src.features.engine import FeatureEngine
from src.features.config import load_feature_config

st.set_page_config(page_title="Dashboard", layout="wide")
st.title("📊 Market Dashboard")

# Load configured assets and the validated local market-data store.
config, _ = load_assets_config()
assets = [ticker for ticker, details in config.items() if details.enabled]

selected_asset = st.sidebar.selectbox("Select Asset", assets)
feature_config = load_feature_config()

# Load data
@st.cache_data
def load_data(ticker):
    return FeatureEngine().compute(DataEngine().load_or_download(ticker, allow_download=False))

try:
    df = load_data(selected_asset)
except (FileNotFoundError, ValueError, OSError) as exc:
    st.error(f"Validated local data is unavailable for {selected_asset}: {exc}")
    st.info("Run `python -m scripts.update_data` from the repository root to populate the local store.")
    st.stop()

# Metrics
col1, col2, col3 = st.columns(3)
if len(df) < 2:
    st.error("At least two validated observations are required to display the Dashboard.")
    st.stop()
last_price = df['close'].iloc[-1].item()
prev_price = df['close'].iloc[-2].item()
change = ((last_price - prev_price) / prev_price) * 100
z_atr = df['z_atr'].iloc[-1].item()

col1.metric("Last Price", f"${last_price:.2f}")
col2.metric("Daily Change", f"{change:.2f}%")
col3.metric("Z_ATR", f"{z_atr:.2f}")

# Plotting
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                    vertical_spacing=0.1, subplot_titles=(f'{selected_asset} Price', 'D_ATR'),
                    row_heights=[0.7, 0.3])

# Price chart
fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df[f"ema{feature_config.ema_fast}"], name=f"EMA{feature_config.ema_fast}", line=dict(color='orange')), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df[f"ema{feature_config.ema_medium}"], name=f"EMA{feature_config.ema_medium}", line=dict(color='blue')), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df[f"ema{feature_config.ema_slow}"], name=f"EMA{feature_config.ema_slow}", line=dict(color='red')), row=1, col=1)

# D_ATR chart
fig.add_trace(go.Scatter(x=df.index, y=df['z_atr'], name='Z_ATR', line=dict(color='purple')), row=2, col=1)
fig.add_hline(y=-1.5, line_dash="dash", line_color="green", row=2, col=1)
fig.add_hline(y=-2.5, line_dash="dash", line_color="orange", row=2, col=1)
fig.add_hline(y=-3.5, line_dash="dash", line_color="red", row=2, col=1)

fig.update_layout(height=800, xaxis_rangeslider_visible=False)
st.plotly_chart(fig, width='stretch')
