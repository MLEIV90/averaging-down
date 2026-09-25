import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yaml

st.set_page_config(page_title="Dashboard", layout="wide")
st.title("📊 Market Dashboard")

# Load assets
with open("config/assets.yaml", "r") as f:
    config = yaml.safe_load(f)
assets = [ticker for ticker, details in config['assets'].items() if details.get('enabled', True)]

selected_asset = st.sidebar.selectbox("Select Asset", assets)

# Load data
@st.cache_data
def load_data(ticker):
    df = yf.download(ticker, period="1y", interval="1d")
    return df

df = load_data(selected_asset)

# Calculate Indicators
def calculate_indicators(df):
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    # ATR14
    high_low = df['High'] - df['Low']
    high_close = abs(df['High'] - df['Close'].shift())
    low_close = abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    tr = ranges.max(axis=1)
    df['ATR14'] = tr.rolling(window=14).mean()
    
    # D_ATR
    df['D_ATR'] = (df['Close'] - df['EMA20']) / df['ATR14']
    return df

df = calculate_indicators(df)

# Metrics
col1, col2, col3 = st.columns(3)
last_price = df['Close'].iloc[-1].item()
prev_price = df['Close'].iloc[-2].item()
change = ((last_price - prev_price) / prev_price) * 100
d_atr = df['D_ATR'].iloc[-1].item()

col1.metric("Last Price", f"${last_price:.2f}")
col2.metric("Daily Change", f"{change:.2f}%")
col3.metric("D_ATR", f"{d_atr:.2f}")

# Plotting
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                    vertical_spacing=0.1, subplot_titles=(f'{selected_asset} Price', 'D_ATR'),
                    row_heights=[0.7, 0.3])

# Price chart
fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['EMA20'], name='EMA20', line=dict(color='orange')), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['EMA50'], name='EMA50', line=dict(color='blue')), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['EMA200'], name='EMA200', line=dict(color='red')), row=1, col=1)

# D_ATR chart
fig.add_trace(go.Scatter(x=df.index, y=df['D_ATR'], name='D_ATR', line=dict(color='purple')), row=2, col=1)
fig.add_hline(y=-1.5, line_dash="dash", line_color="green", row=2, col=1)
fig.add_hline(y=-2.5, line_dash="dash", line_color="orange", row=2, col=1)
fig.add_hline(y=-3.5, line_dash="dash", line_color="red", row=2, col=1)

fig.update_layout(height=800, xaxis_rangeslider_visible=False)
st.plotly_chart(fig, use_container_width=True)
