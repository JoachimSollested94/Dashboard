import streamlit as st
import requests
import pandas as pd
import numpy as np

BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

st.set_page_config(page_title="Crypto Regime Dashboard", layout="wide")

SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None

def get_klines(symbol):
    data = safe_get(
        f"{BINANCE_SPOT}/api/v3/klines",
        params={"symbol": symbol, "interval": "1d", "limit": 400},
    )
    if not isinstance(data, list):
        return None
    df = pd.DataFrame(data)
    df["close"] = pd.to_numeric(df[4], errors="coerce")
    df = df.dropna()
    return df

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


st.title("Crypto Regime Dashboard (Binance Public Data)")

symbol = st.selectbox("Choose asset", SYMBOLS)

result = calculate_regime(symbol)

if result is None:
    st.error("Binance temporarily unavailable.")
else:
    price, sma50, sma200, vol30, vol180, label, score = result

    st.header(f"Final Regime: {label}")
    st.write("Score:", score)

    st.metric("Price", f"${price:,.2f}")
    st.metric("SMA50", f"${sma50:,.2f}")
    st.metric("SMA200", f"${sma200:,.2f}")
    st.metric("Vol30", f"{vol30:.2f}")
    st.metric("Vol180", f"{vol180:.2f}")
