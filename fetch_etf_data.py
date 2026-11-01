#!/usr/bin/env python3
"""Fetch latest prices and compute performance/risk metrics for an ETF watchlist.

Data source: Yahoo Finance public chart API (no key required).
Usage: fetch_etf_data.py [TICKER ...]   (defaults to watchlist.txt next to this file)
Prints a JSON document to stdout.
"""
import json
import math
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

WATCHLIST = Path(__file__).with_name("watchlist.txt")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=10y&interval=1d&events=div"
TRADING_DAYS = 252


def load_tickers(argv):
    if argv:
        return [t.strip().upper() for a in argv for t in a.split(",") if t.strip()]
    lines = WATCHLIST.read_text().splitlines()
    return [l.split("#")[0].strip().upper() for l in lines if l.split("#")[0].strip()]


def fetch(ticker):
    req = urllib.request.Request(URL.format(t=ticker), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["chart"]["result"][0]


def pct(a, b):
    return None if a is None or b in (None, 0) else round((a / b - 1) * 100, 2)


def sma(xs, n):
    return round(sum(xs[-n:]) / n, 2) if len(xs) >= n else None


def rsi(xs, n=14):
    if len(xs) <= n:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = xs[i] - xs[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / n, losses / n
    for i in range(n + 1, len(xs)):
        d = xs[i] - xs[i - 1]
        avg_g = (avg_g * (n - 1) + max(d, 0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0)) / n
    return 100.0 if avg_l == 0 else round(100 - 100 / (1 + avg_g / avg_l), 1)


def volatility(xs):
    rets = [xs[i] / xs[i - 1] - 1 for i in range(1, len(xs))]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var) * math.sqrt(TRADING_DAYS) * 100, 2)


def max_drawdown(xs):
    peak, mdd = xs[0], 0.0
    for x in xs:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    return round(mdd * 100, 2)


def cagr(xs, ts, years):
    target = ts[-1] - years * 365.25 * 86400
    if ts[0] > target + 7 * 86400:  # not enough history
        return None
    i = next(i for i, t in enumerate(ts) if t >= target)
    actual = (ts[-1] - ts[i]) / (365.25 * 86400)
    return round(((xs[-1] / xs[i]) ** (1 / actual) - 1) * 100, 2)


def analyze(ticker):
    res = fetch(ticker)
    meta = res["meta"]
    q = res["indicators"]
    # adjclose includes dividends -> total return; fall back to close
    adj = (q.get("adjclose") or [{}])[0].get("adjclose") or q["quote"][0]["close"]
    close = q["quote"][0]["close"]
    rows = [(t, c, a) for t, c, a in zip(res["timestamp"], close, adj) if c is not None and a is not None]
    ts = [t for t, _, _ in rows]
    close = [c for _, c, _ in rows]
    adj = [a for _, _, a in rows]
    price = meta.get("regularMarketPrice") or close[-1]

    def back(xs, days):
        return xs[-1 - days] if len(xs) > days else None

    divs = (res.get("events") or {}).get("dividends", {})
    year_ago = datetime.now(timezone.utc).timestamp() - 365 * 86400
    ttm_div = sum(d["amount"] for d in divs.values() if d["date"] >= year_ago)
    last_year = close[-TRADING_DAYS:]

    return {
        "ticker": ticker,
        "name": meta.get("longName") or meta.get("shortName"),
        "price": round(price, 2),
        "as_of": datetime.fromtimestamp(meta["regularMarketTime"], timezone.utc).isoformat(),
        "day_change_pct": meta.get("regularMarketChangePercent") and round(meta["regularMarketChangePercent"], 2),
        "52w_high": round(max(last_year), 2),
        "52w_low": round(min(last_year), 2),
        "pct_below_52w_high": pct(price, max(last_year)),
        "total_return_pct": {
            "1m": pct(adj[-1], back(adj, 21)),
            "3m": pct(adj[-1], back(adj, 63)),
            "6m": pct(adj[-1], back(adj, 126)),
            "1y": pct(adj[-1], back(adj, 252)),
        },
        "cagr_pct": {"3y": cagr(adj, ts, 3), "5y": cagr(adj, ts, 5), "10y": cagr(adj, ts, 10)},
        "volatility_1y_pct": volatility(adj[-TRADING_DAYS - 1:]),
        "volatility_5y_pct": volatility(adj[-5 * TRADING_DAYS - 1:]),
        "max_drawdown_5y_pct": max_drawdown(adj[-5 * TRADING_DAYS:]),
        "ttm_dividend_yield_pct": round(ttm_div / price * 100, 2) if price else None,
        "sma_50": sma(close, 50),
        "sma_200": sma(close, 200),
        "price_vs_sma200_pct": pct(price, sma(close, 200)),
        "rsi_14": rsi(close[-250:]),
        "history_years": round(len(adj) / TRADING_DAYS, 1),
    }


def main():
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "etfs": [], "errors": {}}
    for t in load_tickers(sys.argv[1:]):
        try:
            out["etfs"].append(analyze(t))
        except Exception as e:  # keep going if one ticker fails
            out["errors"][t] = str(e)
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
