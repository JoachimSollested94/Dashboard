import time
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import requests
import streamlit as st


# -----------------------------
# Config
# -----------------------------
BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"  # USD-M futures
DEFAULT_REFRESH_SEC = 60
KLINES_LIMIT = 500  # enough for 200D + buffers
FUNDING_LIMIT = 1000  # Binance max is typically 1000

# Score weights (simple, practical)
W_TREND_200 = 4
W_CROSS_50_200 = 2
W_VOL_STRESS = 2
W_FUNDING = 1
W_ATTENTION = 1

# Score thresholds
T_BULL = 4
T_BEAR = -4


# -----------------------------
# Small utilities
# -----------------------------
class BinanceError(RuntimeError):
    pass


def _get(url: str, params: dict, timeout: int = 15, tries: int = 3, backoff: float = 0.8):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code != 200:
                raise BinanceError(f"HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
        except Exception as e:
            last = e
            time.sleep(backoff * (2 ** i))
    raise BinanceError(str(last))


@st.cache_data(ttl=60, show_spinner=False)
def get_top10_symbols_quote_usdt() -> List[str]:
    """
    Practical 'Top 10' proxy using Binance 24h quoteVolume in USDT among USDT pairs.
    This avoids external market-cap APIs and stays within Binance public data.
    """
    data = _get(f"{BINANCE_SPOT}/api/v3/ticker/24hr", params={})
    rows = []
    for it in data:
        sym = it.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        # Exclude leveraged tokens/fiat-ish tickers if any appear
        if any(x in sym for x in ["UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"]):
            continue
        try:
            qv = float(it.get("quoteVolume", "0") or 0.0)
        except Exception:
            qv = 0.0
        if qv > 0:
            rows.append((sym, qv))
    rows.sort(key=lambda x: x[1], reverse=True)
    # Keep first 10 symbols like BTCUSDT, ETHUSDT...
    return [r[0] for r in rows[:10]]


@st.cache_data(ttl=60, show_spinner=False)
def fetch_klines(symbol: str, interval: str = "1d", limit: int = KLINES_LIMIT) -> pd.DataFrame:
    """
    Spot klines for SMA and volatility calculations.
    """
    payload = _get(
        f"{BINANCE_SPOT}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
    )
    if not payload or not isinstance(payload, list):
        raise BinanceError("Empty kline payload")
    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]
    df = pd.DataFrame(payload, columns=cols)
    for c in ["open", "high", "low", "close", "volume", "quote_asset_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df


@st.cache_data(ttl=60, show_spinner=False)
def fetch_funding_rates(symbol: str, limit: int = 200) -> pd.Series:
    """
    USD-M funding rate history (public). symbol should be like BTCUSDT for perpetuals.
    """
    payload = _get(
        f"{BINANCE_FUTURES}/fapi/v1/fundingRate",
        params={"symbol": symbol, "limit": int(min(max(limit, 1), FUNDING_LIMIT))},
    )
    if not isinstance(payload, list) or len(payload) == 0:
        raise BinanceError("No funding data (is it a USD-M perpetual?)")
    df = pd.DataFrame(payload)
    df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df = df.dropna(subset=["fundingRate"]).sort_values("fundingTime")
    return pd.Series(df["fundingRate"].values, index=df["fundingTime"].values, name="fundingRate")


@st.cache_data(ttl=60, show_spinner=False)
def fetch_24h_stats(symbol: str) -> Dict[str, float]:
    payload = _get(f"{BINANCE_SPOT}/api/v3/ticker/24hr", params={"symbol": symbol})
    # Useful fields: lastPrice, priceChangePercent, quoteVolume, volume
    out = {}
    for k in ["lastPrice", "priceChangePercent", "quoteVolume", "volume"]:
        try:
            out[k] = float(payload.get(k, 0) or 0.0)
        except Exception:
            out[k] = float("nan")
    return out


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def realized_vol(log_returns: pd.Series, n: int, annualize: bool = True) -> float:
    r = log_returns.dropna().tail(n)
    if len(r) < max(10, int(n * 0.7)):
        return float("nan")
    vol = float(r.std(ddof=1))
    if annualize:
        vol *= np.sqrt(365.0)  # crypto trades daily
    return vol


def label_ok_warn(condition: bool) -> str:
    return "OK ✅" if condition else "Warning ⚠️"


def pct(x: float) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x*100:.2f}%"


def num(x: float, decimals: int = 4) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.{decimals}f}"


@dataclass
class IndicatorCard:
    title: str
    status: str
    metrics: List[Tuple[str, str]]
    verdict_lines: List[str]


def compute_indicators(symbol: str) -> Tuple[List[IndicatorCard], Dict]:
    kl = fetch_klines(symbol, "1d", KLINES_LIMIT)
    close = kl["close"]
    last_price = float(close.iloc[-1])

    sma50 = float(sma(close, 50).iloc[-1])
    sma200 = float(sma(close, 200).iloc[-1])

    # log returns
    lr = np.log(close).diff()

    vol30 = realized_vol(lr, 30, annualize=True)
    vol180 = realized_vol(lr, 180, annualize=True)

    # funding (try)
    funding_series = None
    funding_last = float("nan")
    funding_label = "—"
    funding_status = "Neutral"
    funding_verdict = ["Funding data not available for this symbol's USD-M perpetual."]
    try:
        funding_series = fetch_funding_rates(symbol, limit=200)
        funding_last = float(funding_series.iloc[-1])
        # datadriven thresholds: 5th/95th percentiles over last 180 obs (or available)
        base = funding_series.tail(180)
        lo = float(base.quantile(0.05))
        hi = float(base.quantile(0.95))
        if funding_last >= hi:
            funding_status = "Extreme Positive"
            funding_label = "Warning ⚠️"
            funding_verdict = [
                "Funding is extremely positive → market is likely crowded long.",
                "Risk of long liquidations/flush increases → consider trimming/hedging."
            ]
        elif funding_last <= lo:
            funding_status = "Extreme Negative"
            funding_label = "OK ✅"
            funding_verdict = [
                "Funding is extremely negative → market is likely crowded short / panic.",
                "Historically can coincide with better risk-reward entries (still confirm with trend)."
            ]
        else:
            funding_status = "Neutral"
            funding_label = "OK ✅"
            funding_verdict = [
                "Funding is neutral → leverage pressure is not extreme.",
                "Use trend + volatility signals as primary regime filter."
            ]
    except Exception as e:
        funding_label = "—"
        funding_status = "Unavailable"
        funding_verdict = [f"Funding unavailable: {str(e)}"]

    # Attention proxy from Binance only: 24h quoteVolume and priceChangePercent
    stats = fetch_24h_stats(symbol)
    price_change_24h = stats.get("priceChangePercent", float("nan"))
    quote_vol_24h = stats.get("quoteVolume", float("nan"))

    # Build the 5 cards

    # A) 200D SMA regime
    above_200 = last_price > sma200 if not np.isnan(sma200) else False
    card_a = IndicatorCard(
        title="A) 200D SMA (Regimefilter)",
        status=label_ok_warn(above_200),
        metrics=[
            ("Pris", f"${num(last_price, 2)}"),
            ("SMA200", f"${num(sma200, 2)}"),
        ],
        verdict_lines=(
            ["Pris er over 200D → strukturel bull-bias; du kan være mere offensiv."]
            if above_200 else
            ["Pris er under 200D → strukturel bear-bias; vær defensiv (lavere eksponering)."]
        )
    )

    # B) 50D vs 200D cross
    cross_bull = (sma50 > sma200) if (not np.isnan(sma50) and not np.isnan(sma200)) else False
    card_b = IndicatorCard(
        title="B) 50D vs 200D (Strukturskift)",
        status=label_ok_warn(cross_bull),
        metrics=[
            ("SMA50", f"${num(sma50, 2)}"),
            ("SMA200", f"${num(sma200, 2)}"),
        ],
        verdict_lines=(
            ["SMA50 > SMA200 → momentumstruktur er positiv (bullish bekræftelse)."]
            if cross_bull else
            ["SMA50 < SMA200 → momentumstruktur er svag (bearish/transition)."]
        )
    )

    # C) Vol stress
    vol_stress = (vol30 > vol180 * 1.25) if (not np.isnan(vol30) and not np.isnan(vol180)) else False
    card_c = IndicatorCard(
        title="C) Volatilitet (30D vs 180D)",
        status=label_ok_warn(not vol_stress),
        metrics=[
            ("Vol30 (ann.)", pct(vol30)),
            ("Vol180 (ann.)", pct(vol180)),
        ],
        verdict_lines=(
            [
                "Stress-regime: kort volatilitet er markant højere end lang volatilitet.",
                "Typisk dårligere risk-reward → undgå at øge aggressivt før det stabiliserer."
            ] if vol_stress else
            [
                "Ingen stress-signal: volatilitet er relativt stabil.",
                "Bedre betingelser for trend-positionering, hvis trendfiltre også er positive."
            ]
        )
    )

    # D) Funding
    card_d = IndicatorCard(
        title="D) Funding (Leverage/sentiment)",
        status=funding_label if funding_label != "—" else "—",
        metrics=[
            ("Seneste funding", pct(funding_last) if not np.isnan(funding_last) else "—"),
            ("Status", funding_status),
        ],
        verdict_lines=funding_verdict
    )

    # E) Attention proxy (Binance-only)
    # Simple: if quote vol is high AND price change is high → late-euphoria risk; if both low/negative → exhaustion
    attention_hot = (not np.isnan(price_change_24h) and price_change_24h > 6.0) and (not np.isnan(quote_vol_24h) and quote_vol_24h > 0)
    attention_cold = (not np.isnan(price_change_24h) and price_change_24h < -6.0)

    att_status = "OK ✅"
    att_verdict = [
        "Proxy: 24h prisændring + 24h volumen (kun Binance).",
        "Brug som sekundært ‘temperatur’-signal (ikke alene)."
    ]
    if attention_hot:
        att_status = "Warning ⚠️"
        att_verdict = [
            "Opmærksomhed/flow ser varm ud (stor 24h move).",
            "Øget risiko for mean reversion → trim/strammere risk management."
        ]
    elif attention_cold:
        att_status = "OK ✅"
        att_verdict = [
            "Opmærksomhed/flow ser kold ud (større 24h fald).",
            "Kan forbedre entry-ratio, men bekræft med trend/vol først."
        ]

    card_e = IndicatorCard(
        title="E) Attention (Binance-proxy)",
        status=att_status,
        metrics=[
            ("24h %", f"{num(price_change_24h, 2)}%"),
            ("24h quoteVol", num(quote_vol_24h, 0)),
        ],
        verdict_lines=att_verdict
    )

    # Final regime score
    score = 0
    reasons = []

    # 200D
    if above_200:
        score += W_TREND_200
        reasons.append("Pris > 200D SMA (+4)")
    else:
        score -= W_TREND_200
        reasons.append("Pris < 200D SMA (-4)")

    # 50/200
    if cross_bull:
        score += W_CROSS_50_200
        reasons.append("SMA50 > SMA200 (+2)")
    else:
        score -= W_CROSS_50_200
        reasons.append("SMA50 < SMA200 (-2)")

    # Vol stress
    if vol_stress:
        score -= W_VOL_STRESS
        reasons.append("Vol-stress (30D >> 180D) (-2)")
    else:
        score += W_VOL_STRESS
        reasons.append("Vol stabil (+2)")

    # Funding
    if funding_status == "Extreme Positive":
        score -= W_FUNDING
        reasons.append("Funding ekstrem positiv (-1)")
    elif funding_status == "Extreme Negative":
        score += W_FUNDING
        reasons.append("Funding ekstrem negativ (+1)")
    elif funding_status in ["Neutral"]:
        reasons.append("Funding neutral (0)")
    else:
        reasons.append("Funding utilgængelig (0)")

    # Attention proxy
    if attention_hot:
        score -= W_ATTENTION
        reasons.append("Attention varm (-1)")
    elif attention_cold:
        score += W_ATTENTION
        reasons.append("Attention kold (+1)")
    else:
        reasons.append("Attention neutral (0)")

    if score >= T_BULL:
        regime = "BULL 📈"
    elif score <= T_BEAR:
        regime = "BEAR 📉"
    else:
        regime = "TRANSITION ⚖️"

    out = {
        "symbol": symbol,
        "last_price": last_price,
        "sma50": sma50,
        "sma200": sma200,
        "vol30": vol30,
        "vol180": vol180,
        "funding_last": funding_last,
        "funding_status": funding_status,
        "score": score,
        "regime": regime,
        "reasons": reasons,
        "klines": kl,
    }
    return [card_a, card_b, card_c, card_d, card_e], out


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Crypto Regime Dashboard (Binance)", layout="wide")
st.title("Crypto Regime Dashboard (Binance public data)")

with st.sidebar:
    st.header("Settings")
    refresh = st.number_input("Auto-refresh (seconds)", min_value=15, max_value=600, value=DEFAULT_REFRESH_SEC, step=5)
    st.caption("Data: Binance public endpoints (spot klines + USD-M funding).")
    st.divider()

    # Top 10 list (Binance volume proxy)
    try:
        top10 = get_top10_symbols_quote_usdt()
    except Exception as e:
        st.error(f"Could not load top10 list: {e}")
        top10 = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "TRXUSDT", "AVAXUSDT", "TONUSDT"]

    symbol = st.selectbox("Choose asset (Top 10 by Binance USDT volume)", top10, index=min(1, len(top10)-1))
    st.caption("Tip: If funding is unavailable for a symbol, it may not have a USD-M perpetual on Binance futures.")

# Auto-refresh
st_autorefresh = st.experimental_rerun  # alias for clarity
# Implement a simple timer-driven rerun without extra dependencies
if "last_rerun" not in st.session_state:
    st.session_state["last_rerun"] = time.time()

now = time.time()
if now - st.session_state["last_rerun"] > refresh:
    st.session_state["last_rerun"] = now
    st.experimental_rerun()

# Main computation
try:
    cards, out = compute_indicators(symbol)
except Exception as e:
    st.error(f"Data error for {symbol}: {e}")
    st.stop()

# Final panel
st.subheader("Final Regime")
col1, col2 = st.columns([1, 2])
with col1:
    st.metric("Regime", out["regime"], delta=f"Score: {out['score']}")
with col2:
    st.write("**Drivers (rules):**")
    st.write("• " + "\n• ".join(out["reasons"]))

st.divider()

# Indicator cards
st.subheader("Indicators")
c1, c2, c3, c4, c5 = st.columns(5)
cols = [c1, c2, c3, c4, c5]
for col, card in zip(cols, cards):
    with col:
        st.markdown(f"### {card.title}")
        st.markdown(f"**Status:** {card.status}")
        for k, v in card.metrics:
            st.write(f"- **{k}:** {v}")
        st.markdown("**Slutvurdering:**")
        for line in card.verdict_lines:
            st.write(f"- {line}")

st.divider()

# Simple chart table (keep practical)
st.subheader("Recent daily close + SMAs (last 120 days)")
kl = out["klines"].copy()
kl["SMA50"] = sma(kl["close"], 50)
kl["SMA200"] = sma(kl["close"], 200)
view = kl[["close_time", "close", "SMA50", "SMA200"]].tail(120).rename(columns={"close_time": "date"})
view["date"] = view["date"].dt.date
st.line_chart(view.set_index("date"))

st.caption("Daily use (30 sec): 1) Check Regime label. 2) If BEAR: reduce risk; if BULL: allow exposure; if TRANSITION: scale in slowly. 3) Watch Funding + Vol for squeeze/flush risk.")
