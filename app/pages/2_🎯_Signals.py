import streamlit as st
import pandas as pd
import json

st.title("🎯 Signals")

try:
    with open('data/processed/latest_signals.json', 'r') as f:
        signals = json.load(f)
    df = pd.DataFrame(signals)
    
    # Display table
    st.dataframe(df)
    
except Exception as e:
    st.error(f"Error loading signals: {e}")
