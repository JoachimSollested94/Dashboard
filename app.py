import streamlit as st
import requests
import pandas as pd
import numpy as np
import time

st.set_page_config(page_title="Crypto Regime Dashboard", layout="wide")

COINS = {
    "Bitcoin": "bitcoin",
    "Ethereum": "ethereum",
    "Solana": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple"
}

# -----------------------------
# RETRY + SAFE FETCH
# -----------------------------

def fetch_with_retry(url, params=None, retries=3):
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
        except:
            pass
        time.sleep(1)
    return None

# -----------------------------
# CACHED DATA FETCH
# -----------------------------

@st.cache_data(ttl=300)
def get_market_data(coin_id):
    data = fetch_with_retry(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
        params={"vs_currency": "usd", "days": "365"}
    )

    if not data or "prices" not in data:
        return None

    df = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna()

    return df

# -----------------------------
# REGIME CALCULATION
# -----------------------------

def calculate_regime(df):
    close = df["price"]

    df["SMA50"] = close.rolling(50).mean()
    df["SMA200"] = close.rolling(200).mean()

    log_returns = np.log(close).diff()
    vol30 = log_returns.tail(30).std() * np.sqrt(365)
    vol180 = log_returns.tail(180).std() * np.sqrt(365)

    price = close.iloc[-1]
    sma50 = df["SMA50"].iloc[-1]
    sma200 = df["SMA200"].iloc[-1]

    score = 0

    if price > sma200:
        score += 4
    else:
        score -= 4

    if sma50 > sma200:
        score += 2
    else:
        score -= 2

    if vol30 < vol180:
        score += 2
    else:
        score -= 2

    if score >= 4:
        label = "BULL 📈"
        explanation = "Price is above long-term trend and volatility is stable."
        color = "green"
    elif score <= -4:
        label = "BEAR 📉"
        explanation = "Price is below long-term trend and volatility is elevated."
        color = "red"
    else:
        label = "TRANSITION ⚖️"
        explanation = "Market is between regimes. Trend not fully confirmed."
        color = "orange"

    return df, price, sma50, sma200, vol30, vol180, label, explanation, color, score

# -----------------------------
# UI
# -----------------------------

st.title("📊 Crypto Regime Dashboard")

coin_name = st.selectbox("Choose asset", list(COINS.keys()))
coin_id = COINS[coin_name]

df = get_market_data(coin_id)

if df is None or len(df) < 200:
    st.error("Data temporarily unavailable. Try again in a few minutes.")
else:
    df, price, sma50, sma200, vol30, vol180, label, explanation, color, score = calculate_regime(df)

    st.markdown(f"## Regime: <span style='color:{color}'>{label}</span>", unsafe_allow_html=True)
    st.write(explanation)
    st.write(f"Regime Score: {score}")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Current Price", f"${price:,.2f}")
        st.metric("SMA 50", f"${sma50:,.2f}")
        st.metric("SMA 200", f"${sma200:,.2f}")

    with col2:
        st.metric("Volatility 30D (ann.)", f"{vol30:.2f}")
        st.metric("Volatility 180D (ann.)", f"{vol180:.2f}")

    st.subheader("Price with Trend Indicators")

    chart_df = df[["price", "SMA50", "SMA200"]]
    st.line_chart(chart_df)

    st.caption("Data source: CoinGecko public API. Cached for 5 minutes to avoid rate limits.")
