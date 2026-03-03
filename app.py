import streamlit as st
import requests
import pandas as pd
import numpy as np

st.set_page_config(page_title="Crypto Regime Dashboard", layout="wide")

# CoinGecko coin IDs
COINS = {
    "Bitcoin": "bitcoin",
    "Ethereum": "ethereum",
    "Solana": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple"
}

# -------------------------
# SAFE API CALL
# -------------------------

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None

# -------------------------
# FETCH HISTORICAL DATA
# -------------------------

def get_market_data(coin_id):
    data = safe_get(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
        params={"vs_currency": "usd", "days": "365"}
    )

    if not data or "prices" not in data:
        return None

    prices = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
    prices["price"] = pd.to_numeric(prices["price"], errors="coerce")
    prices = prices.dropna()

    return prices

# -------------------------
# REGIME CALCULATION
# -------------------------

def calculate_regime(coin_id):
    df = get_market_data(coin_id)
    if df is None or len(df) < 200:
        return None

    close = df["price"]

    price = close.iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]

    log_returns = np.log(close).diff()
    vol30 = log_returns.tail(30).std() * np.sqrt(365)
    vol180 = log_returns.tail(180).std() * np.sqrt(365)

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
    elif score <= -4:
        label = "BEAR 📉"
    else:
        label = "TRANSITION ⚖️"

    return price, sma50, sma200, vol30, vol180, label, score

# -------------------------
# UI
# -------------------------

st.title("Crypto Regime Dashboard (CoinGecko Data)")

coin_name = st.selectbox("Choose asset", list(COINS.keys()))
coin_id = COINS[coin_name]

result = calculate_regime(coin_id)

if result is None:
    st.error("Could not fetch data. Try again in a few seconds.")
else:
    price, sma50, sma200, vol30, vol180, label, score = result

    st.header(f"Final Regime: {label}")
    st.write("Regime Score:", score)

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Price (USD)", f"${price:,.2f}")
        st.metric("SMA50", f"${sma50:,.2f}")
        st.metric("SMA200", f"${sma200:,.2f}")

    with col2:
        st.metric("Volatility 30D", f"{vol30:.2f}")
        st.metric("Volatility 180D", f"{vol180:.2f}")

    st.caption("Uses CoinGecko public API.")
