import streamlit as st
import requests
import pandas as pd
import numpy as np

BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

st.set_page_config(page_title="Crypto Regime Dashboard", layout="wide")

# ----------------------------
# DATA FUNCTIONS
# ----------------------------

def get_top10():
    data = requests.get(f"{BINANCE_SPOT}/api/v3/ticker/24hr").json()
    pairs = []
    for d in data:
        if d["symbol"].endswith("USDT"):
            pairs.append((d["symbol"], float(d["quoteVolume"])))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in pairs[:10]]


def get_klines(symbol):
    data = requests.get(
        f"{BINANCE_SPOT}/api/v3/klines",
        params={"symbol": symbol, "interval": "1d", "limit": 400},
    ).json()

    df = pd.DataFrame(data)
    df["close"] = pd.to_numeric(df[4])
    return df


def get_funding(symbol):
    try:
        data = requests.get(
            f"{BINANCE_FUTURES}/fapi/v1/fundingRate",
            params={"symbol": symbol, "limit": 50},
        ).json()
        return float(data[-1]["fundingRate"])
    except:
        return None


# ----------------------------
# REGIME CALCULATION
# ----------------------------

def calculate_regime(symbol):
    df = get_klines(symbol)
    close = df["close"]

    price = close.iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]

    log_returns = np.log(close).diff()
    vol30 = log_returns.tail(30).std() * np.sqrt(365)
    vol180 = log_returns.tail(180).std() * np.sqrt(365)

    funding = get_funding(symbol)

    score = 0

    # 200D trend
    if price > sma200:
        score += 4
    else:
        score -= 4

    # 50/200 cross
    if sma50 > sma200:
        score += 2
    else:
        score -= 2

    # Vol regime
    if vol30 < vol180:
        score += 2
    else:
        score -= 2

    # Funding
    if funding is not None:
        if funding < 0:
            score += 1
        else:
            score -= 1

    if score >= 4:
        label = "BULL 📈"
    elif score <= -4:
        label = "BEAR 📉"
    else:
        label = "TRANSITION ⚖️"

    return price, sma50, sma200, vol30, vol180, funding, label, score


# ----------------------------
# UI
# ----------------------------

st.title("Crypto Regime Dashboard (Binance Public Data)")

symbols = get_top10()
symbol = st.selectbox("Choose asset", symbols)

price, sma50, sma200, vol30, vol180, funding, label, score = calculate_regime(symbol)

st.header(f"Final Regime: {label}")
st.write("Regime Score:", score)

st.subheader("Indicators")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Price", f"${price:,.2f}")
    st.metric("SMA50", f"${sma50:,.2f}")
    st.metric("SMA200", f"${sma200:,.2f}")

with col2:
    st.metric("Volatility 30D (ann.)", f"{vol30:.2f}")
    st.metric("Volatility 180D (ann.)", f"{vol180:.2f}")

with col3:
    st.metric("Funding Rate", funding if funding else "Unavailable")

st.caption("Uses Binance public API only.")
