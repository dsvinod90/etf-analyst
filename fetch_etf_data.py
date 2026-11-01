#!/usr/bin/env python3
"""Discover ETFs, compute performance/risk metrics, and rank them for long- and short-term investing.

Data source: Yahoo Finance public screener + chart APIs (no key required).
Usage:
  fetch_etf_data.py                 # discover candidates from Yahoo screeners and rank them
  fetch_etf_data.py VOO QQQM ...    # analyze and rank only these tickers
  fetch_etf_data.py --top 20        # number of picks per horizon (default 15)
Prints a JSON document to stdout.
"""
import argparse
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={s}&count=250"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=10y&interval=1d&events=div"
# top_performing_etfs: Morningstar 4-5 star funds; top_etfs_us: today's biggest movers
SCREENERS = ["top_performing_etfs", "top_etfs_us"]
# Always included so picks can be compared against the obvious defaults
BENCHMARKS = ["SPY", "VOO", "VTI", "QQQM", "VT", "VXUS", "SCHD", "BND"]
MIN_NET_ASSETS = 1e9
MIN_AVG_VOLUME = 100_000
EXCLUDE_NAME = re.compile(
    r"\b(2x|3x|-1x|-2x|-3x|ultra|ultrapro|bull|bear|inverse|leveraged|daily)\b|\bshort\b(?![- ](term|duration|maturity))",
    re.I)
SAVE_DIR = Path(__file__).resolve().parent / "reports" / "data"
RISK_FREE_PCT = 4.0  # approx. cash/T-bill yield used for the Sharpe ratio
TRADING_DAYS = 252
VALID_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")  # e.g. VOO, BRK.B, BF-B
YEAR = 365.25 * 86400


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def discover():
    """Return {ticker: screener quote} for liquid, unleveraged ETFs from Yahoo's screeners."""
    found = {}
    for s in SCREENERS:
        for q in get_json(SCREENER_URL.format(s=s))["finance"]["result"][0]["quotes"]:
            name = q.get("longName") or q.get("shortName") or ""
            if (q.get("quoteType") == "ETF"
                    and (q.get("netAssets") or 0) >= MIN_NET_ASSETS
                    and (q.get("averageDailyVolume3Month") or 0) >= MIN_AVG_VOLUME
                    and not EXCLUDE_NAME.search(name)):
                found.setdefault(q["symbol"], q)
    return found


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
    target = ts[-1] - years * YEAR
    if ts[0] > target + 7 * 86400:  # not enough history
        return None
    i = next(i for i, t in enumerate(ts) if t >= target)
    return round(((xs[-1] / xs[i]) ** (YEAR / (ts[-1] - ts[i])) - 1) * 100, 2)


def analyze(ticker, quote=None):
    if not VALID_TICKER.match(ticker):
        raise ValueError("invalid ticker symbol")
    res = get_json(CHART_URL.format(t=urllib.parse.quote(ticker, safe="")))["chart"]["result"][0]
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
    quote = quote or {}

    def back(xs, days):
        return xs[-1 - days] if len(xs) > days else None

    divs = (res.get("events") or {}).get("dividends", {})
    year_ago = datetime.now(timezone.utc).timestamp() - 365 * 86400
    ttm_div = sum(d["amount"] for d in divs.values() if d["date"] >= year_ago)
    last_year = close[-TRADING_DAYS:]
    sma200 = sma(close, 200)

    return {
        "ticker": ticker,
        "name": meta.get("longName") or meta.get("shortName"),
        "price": round(price, 2),
        "as_of": datetime.fromtimestamp(meta["regularMarketTime"], timezone.utc).isoformat(),
        "day_change_pct": meta.get("regularMarketChangePercent") and round(meta["regularMarketChangePercent"], 2),
        "expense_ratio_pct": quote.get("netExpenseRatio"),
        "net_assets_bn": quote.get("netAssets") and round(quote["netAssets"] / 1e9, 1),
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
        "sma_200": sma200,
        "price_vs_sma200_pct": pct(price, sma200),
        "rsi_14": rsi(close[-250:]),
        "history_years": round((ts[-1] - ts[0]) / YEAR, 1),
    }


def zscores(etfs, key):
    """Standardize key(e) across etfs; missing values score 0 (the average)."""
    vals = {e["ticker"]: key(e) for e in etfs}
    present = [v for v in vals.values() if v is not None]
    if len(present) < 2:
        return {t: 0.0 for t in vals}
    m = sum(present) / len(present)
    sd = math.sqrt(sum((v - m) ** 2 for v in present) / len(present)) or 1
    return {t: 0.0 if v is None else (v - m) / sd for t, v in vals.items()}


def score(etfs):
    """Attach long_term and short_term scores. Weights are heuristics, not predictions."""
    def sharpe(e):
        # excess return over cash, so ultra-low-volatility bond funds don't win by default
        c, v = e["cagr_pct"]["5y"], e["volatility_5y_pct"]
        return (c - RISK_FREE_PCT) / v if c is not None and v else None

    long_parts = {  # weight, metric (higher is better)
        "5y_cagr": (0.20, lambda e: e["cagr_pct"]["5y"]),
        "10y_cagr": (0.20, lambda e: e["cagr_pct"]["10y"]),
        "sharpe_5y": (0.30, sharpe),
        "max_drawdown_5y": (0.10, lambda e: e["max_drawdown_5y_pct"]),
        "low_expense": (0.15, lambda e: None if e["expense_ratio_pct"] is None else -e["expense_ratio_pct"]),
        "fund_size": (0.05, lambda e: e["net_assets_bn"] and math.log(e["net_assets_bn"])),
    }
    short_parts = {
        "3m_return": (0.30, lambda e: e["total_return_pct"]["3m"]),
        "6m_return": (0.25, lambda e: e["total_return_pct"]["6m"]),
        "1m_return": (0.10, lambda e: e["total_return_pct"]["1m"]),
        "trend_vs_sma200": (0.20, lambda e: e["price_vs_sma200_pct"]),
        "low_volatility_1y": (0.15, lambda e: e["volatility_1y_pct"] and -e["volatility_1y_pct"]),
    }
    for label, parts in (("long_term", long_parts), ("short_term", short_parts)):
        z = {k: zscores(etfs, f) for k, (_, f) in parts.items()}
        for e in etfs:
            s = sum(w * z[k][e["ticker"]] for k, (w, _) in parts.items())
            flags = []
            if label == "long_term" and e["history_years"] < 5:
                s -= 1.0
                flags.append("under 5 years of history")
            if label == "short_term":
                if e["rsi_14"] and e["rsi_14"] > 75:
                    s -= 0.5
                    flags.append("overbought (RSI > 75)")
                if e["price_vs_sma200_pct"] is not None and e["price_vs_sma200_pct"] < 0:
                    flags.append("below 200-day average (downtrend)")
            e.setdefault("scores", {})[label] = round(s, 3)
            if flags:
                e.setdefault("flags", {})[label] = flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*", help="analyze only these (comma or space separated)")
    ap.add_argument("--top", type=int, default=15, help="picks per horizon")
    ap.add_argument("--save", action="store_true",
                    help="also save the full data (every fund analyzed) to reports/data/ for verification")
    args = ap.parse_args()

    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "errors": {}}
    if args.tickers:
        quotes = {t.strip().upper(): None for a in args.tickers for t in a.split(",") if t.strip()}
        out["mode"] = "tickers"
    else:
        quotes = discover()
        out["mode"] = "discovery"
        out["screeners"] = SCREENERS
        out["filters"] = {"min_net_assets": MIN_NET_ASSETS, "min_avg_volume": MIN_AVG_VOLUME,
                          "excluded": "leveraged/inverse"}
        for b in BENCHMARKS:
            quotes.setdefault(b, None)

    def run(t):
        try:
            return analyze(t, quotes[t])
        except Exception as e:  # keep going if one ticker fails
            out["errors"][t] = str(e)

    with ThreadPoolExecutor(max_workers=8) as pool:
        etfs = [e for e in pool.map(run, quotes) if e]
    score(etfs)
    for label in ("long_term", "short_term"):
        for rank, e in enumerate(sorted(etfs, key=lambda e: -e["scores"][label]), 1):
            e.setdefault("ranks", {})[label] = rank

    out["candidates_analyzed"] = len(etfs)
    out["long_term_picks"] = sorted(etfs, key=lambda e: -e["scores"]["long_term"])[:args.top]
    out["short_term_picks"] = sorted(etfs, key=lambda e: -e["scores"]["short_term"])[:args.top]
    picked = {e["ticker"] for e in out["long_term_picks"] + out["short_term_picks"]}
    out["benchmarks"] = [e for e in etfs if e["ticker"] in BENCHMARKS and e["ticker"] not in picked]
    if args.save:
        # full record of every fund analyzed, so a report can be verified against it later
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        path = SAVE_DIR / f"etf-data-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.json"
        out["saved_to"] = str(path)
        path.write_text(json.dumps({**out, "all_etfs": etfs}, indent=2))
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
