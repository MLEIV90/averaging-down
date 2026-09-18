import streamlit as st
st.title("⚙️ Settings")
st.checkbox("Enable SPY",True); st.checkbox("Enable BTC",True); st.checkbox("Enable GLD",True)
st.checkbox("Paper trading",False); st.checkbox("Live trading",False,disabled=True)
st.warning("Live trading is disabled in the initial architecture.")
