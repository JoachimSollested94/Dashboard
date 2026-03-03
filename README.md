# Crypto Regime Dashboard (Binance public data)

A small Streamlit dashboard that pulls **live public** data from Binance (no API key) and computes 5 practical regime indicators:

A) Price vs 200D SMA  
B) 50D vs 200D structure  
C) 30D vs 180D realized volatility stress  
D) Funding rate (USD-M futures) with percentile-based extremes  
E) "Attention" proxy using Binance 24h price change + quoteVolume

It outputs a final **BULL / BEAR / TRANSITION** regime label with a weighted score and rule reasons.

## Architecture (10 lines)
1. Streamlit UI with dropdown for a Top-10 list derived from Binance 24h USDT quoteVolume.  
2. Spot daily klines pulled from `/api/v3/klines` (1d) for SMA and volatility.  
3. Funding history pulled from USD-M futures `/fapi/v1/fundingRate` (public).  
4. 24h stats pulled from `/api/v3/ticker/24hr` for attention proxy.  
5. SMA50/SMA200 computed on daily closes.  
6. Realized volatility computed from daily log returns for 30D and 180D (annualized).  
7. Funding extremes defined via rolling percentiles (5%/95%) over last ~180 funding observations.  
8. Each indicator generates a simple OK/Warning label plus a short verdict.  
9. A weighted score maps to BULL/BEAR/TRANSITION.  
10. Caching + retries/backoff reduces API load and improves robustness.

## Run locally
### 1) Install
```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

### 2) Start
```bash
streamlit run app.py
```

## Notes
- "Top 10" here means **top by Binance USDT quote volume**, not market cap.
- Some symbols may not have a USD-M perpetual; funding will show as unavailable.
