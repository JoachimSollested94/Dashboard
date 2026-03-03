import streamlit as st
import requests
import pandas as pd
import numpy as np

BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

st.set_page_config(page_title="Crypto Regime Dashboard", layout="wide")


# ----------------------------
# SAFE API CALL
# ----------------------------

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None


# ----------------------------
# TOP 10 (by volume)
# ----------------------------

def get_top10():
    data = safe_get(f"{BINANCE_SPOT}/api/v3/ticker/24hr")
    if not isinstance(data, list):
        return ["BTCUSDT", "ETHUSDT"]

    pairs = []
    for d in data:
        if isinstance(d, dict) and d.get("symbol", "").endswith("USDT"):
            try:
                pairs.append((d["symbol"], float(d["quoteVolume"])))
            except:
                pass

    pairs.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in pairs[:10]]


# ----------------------------
# KLINES
# ----------------------------

def get_klines(symbol):
    data = safe_get(
        f"{BINANCE_SPOT}/api/v3/klines",
        params={"symbol": symbol, "interval": "1d", "limit": 400},
    )

    if not isinstance(data, list):
        return None

    df = pd.DataFrame(data)
    if df.empty:
        return None

    df["close"] = pd.to_numeric(df[4], errors="coerce")
    df = df.dropna()

    return df


# ----------------------------
# FUNDING
# ----------------------------

def get_funding(symbol):
    data = safe_get(
        f"{BINANCE_FUTURES}/fapi/v1/fundingRate",
        params={"symbol": symbol, "limit": 20},
    )

    if not isinstance(data, list) or len(data) == 0:
        return None

    try:
        return float(data[-1]["fundingRate"])
    except:
        return None


# ----------------------------
# REGIME CALCULATION
# ----------------------------

def calculate_regime(symbol):
    df = get_klines(symbol)

    if df is None:
        return None

    close = df["close"]

    price = close.iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]

    log_returns = np.log(close).diff()
    vol30 = log_returns.tail(30).std() * np.sqrt(365)
    vol180 = log_returns.tail(180).std() * np.sqrt(365)

    funding = get_funding(symbol)

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

result = calculate_regime(symbol)

if result is None:
    st.error("Could not fetch data from Binance. Try again in a few seconds.")
else:
    price, sma50, sma200, vol30, vol180, funding, label, score = result

    st.header(f"Final Regime: {label}")
    st.write("Regime Score:", score)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Price", f"${price:,.2f}")
        st.metric("SMA50", f"${sma50:,.2f}")
        st.metric("SMA200", f"${sma200:,.2f}")

    with col2:
        st.metric("Volatility 30D", f"{vol30:.2f}")
        st.metric("Volatility 180D", f"{vol180:.2f}")

    with col3:
        st.metric("Funding Rate", funding if funding else "Unavailable")

    st.caption("Uses Binance public API only.")
