#!/usr/bin/env python3
"""Discover ETFs, compute performance and risk metrics, and rank them by investing horizon.

Data source: Yahoo Finance public screener + chart APIs (no key required).
Prints a JSON document to stdout.

Usage:
    fetch_etf_data.py                 # discover candidates from Yahoo screeners and rank them
    fetch_etf_data.py VOO QQQM ...    # analyze and rank only these tickers
    fetch_etf_data.py --top 20        # number of picks per horizon (default 15)
    fetch_etf_data.py --save          # also save every fund analyzed to reports/data/
"""

import argparse
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from calc import TRADING_DAYS, YEAR, cagr, max_drawdown, pct, rsi, sma, volatility

ETF = dict[str, Any]  # one fund's record, as returned by analyze()
Metric = Callable[[ETF], float | None]

API_ROOT = "https://query1.finance.yahoo.com/"
SCREENER_URL = (
    "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={s}&count=250"
)
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=10y&interval=1d&events=div"
# top_performing_etfs: Morningstar 4-5 star funds; top_etfs_us: today's biggest movers
SCREENERS = ("top_performing_etfs", "top_etfs_us")
# Always included so picks can be compared against the obvious defaults
BENCHMARKS = ("SPY", "VOO", "VTI", "QQQM", "VT", "VXUS", "SCHD", "BND")
MIN_NET_ASSETS = 1e9
MIN_AVG_VOLUME = 100_000
EXCLUDE_NAME = re.compile(
    r"\b(2x|3x|-1x|-2x|-3x|ultra|ultrapro|bull|bear|inverse|leveraged|daily)\b"
    r"|\bshort\b(?![- ](term|duration|maturity))",  # keep "short-term Treasury" funds
    re.IGNORECASE,
)
SAVE_DIR = Path(__file__).resolve().parent / "reports" / "data"
RISK_FREE_PCT = 4.0  # approx. cash/T-bill yield used for the Sharpe ratio
VALID_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")  # e.g. VOO, BRK.B, BF-B
REQUEST_TIMEOUT = 20  # seconds
WORKERS = 8  # parallel downloads; enough for speed without being rate-limited
# Errors that mean "this one fund's data couldn't be fetched or parsed"
FETCH_ERRORS = (OSError, ValueError, KeyError, IndexError, TypeError)


def get_json(url: str) -> Any:  # noqa: ANN401 -- arbitrary JSON from the API
    """Fetch ``url`` from Yahoo Finance's https API and parse it as JSON.

    Raises:
        ValueError: ``url`` isn't on the Yahoo Finance API host (only https there is allowed).
    """
    if not url.startswith(API_ROOT):
        raise ValueError(f"refusing to fetch non-Yahoo URL: {url[:60]}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})  # noqa: S310 -- checked above
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:  # noqa: S310 -- checked above
        return json.load(resp)


def discover() -> dict[str, dict[str, Any]]:
    """Return ``{ticker: screener quote}`` for liquid, unleveraged ETFs from Yahoo's screeners."""
    found: dict[str, dict[str, Any]] = {}
    for screener in SCREENERS:
        result = get_json(SCREENER_URL.format(s=screener))["finance"]["result"][0]
        for quote in result["quotes"]:
            name = quote.get("longName") or quote.get("shortName") or ""
            if (
                quote.get("quoteType") == "ETF"
                and (quote.get("netAssets") or 0) >= MIN_NET_ASSETS
                and (quote.get("averageDailyVolume3Month") or 0) >= MIN_AVG_VOLUME
                and not EXCLUDE_NAME.search(name)
            ):
                found.setdefault(quote["symbol"], quote)
    return found


def _back(xs: Sequence[float], days: int) -> float | None:
    """Return the value ``days`` trading days before the last one, or None if too far back."""
    return xs[-1 - days] if len(xs) > days else None


def _round_or_none(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _history(res: dict[str, Any]) -> tuple[list[float], list[float], list[float]]:
    """Return ``(timestamps, closes, adjusted closes)`` from a chart response, skipping gaps.

    Adjusted closes include reinvested dividends, so returns built on them are total returns.
    """
    indicators = res["indicators"]
    raw_close = indicators["quote"][0]["close"]
    raw_adj = (indicators.get("adjclose") or [{}])[0].get("adjclose") or raw_close
    rows = [
        (t, c, a)
        for t, c, a in zip(res["timestamp"], raw_close, raw_adj, strict=True)
        if c is not None and a is not None
    ]
    return [t for t, _, _ in rows], [c for _, c, _ in rows], [a for _, _, a in rows]


def _dividend_yield(res: dict[str, Any], price: float) -> float | None:
    """Return dividends paid over the last 365 days as a % of ``price``."""
    if not price:
        return None
    dividends = (res.get("events") or {}).get("dividends", {})
    year_ago = datetime.now(UTC).timestamp() - 365 * 86400
    paid = float(sum(d["amount"] for d in dividends.values() if d["date"] >= year_ago))
    return round(paid / price * 100, 2)


def analyze(ticker: str, quote: dict[str, Any] | None = None) -> ETF:
    """Download one fund's 10-year daily history and compute its metrics.

    Args:
        ticker: Symbol, e.g. ``"VOO"``. Validated before use in the request URL.
        quote: The fund's screener entry, if any; supplies expense ratio and assets.

    Returns:
        A JSON-ready record: price, returns, CAGR, volatility, drawdown, yield, SMAs, RSI.
        Percentages are in percent (12.34 means 12.34%); missing values are None.

    Raises:
        ValueError: ``ticker`` isn't a valid symbol.
        OSError: The download failed.
    """
    if not VALID_TICKER.match(ticker):
        raise ValueError("invalid ticker symbol")
    url = CHART_URL.format(t=urllib.parse.quote(ticker, safe=""))
    res = get_json(url)["chart"]["result"][0]
    meta = res["meta"]
    ts, close, adj = _history(res)
    price = meta.get("regularMarketPrice") or close[-1]
    quote = quote or {}
    last_year = close[-TRADING_DAYS:]
    sma200 = sma(close, 200)
    net_assets = quote.get("netAssets")

    return {
        "ticker": ticker,
        "name": meta.get("longName") or meta.get("shortName"),
        "price": round(price, 2),
        "as_of": datetime.fromtimestamp(meta["regularMarketTime"], UTC).isoformat(),
        "day_change_pct": _round_or_none(meta.get("regularMarketChangePercent"), 2),
        "expense_ratio_pct": quote.get("netExpenseRatio"),
        "net_assets_bn": None if net_assets is None else round(net_assets / 1e9, 1),
        "52w_high": round(max(last_year), 2),
        "52w_low": round(min(last_year), 2),
        "pct_below_52w_high": pct(price, max(last_year)),
        "total_return_pct": {
            "1m": pct(adj[-1], _back(adj, 21)),
            "3m": pct(adj[-1], _back(adj, 63)),
            "6m": pct(adj[-1], _back(adj, 126)),
            "1y": pct(adj[-1], _back(adj, 252)),
        },
        "cagr_pct": {"3y": cagr(adj, ts, 3), "5y": cagr(adj, ts, 5), "10y": cagr(adj, ts, 10)},
        "volatility_1y_pct": volatility(adj[-TRADING_DAYS - 1 :]),
        "volatility_5y_pct": volatility(adj[-5 * TRADING_DAYS - 1 :]),
        "max_drawdown_5y_pct": max_drawdown(adj[-5 * TRADING_DAYS :]),
        "ttm_dividend_yield_pct": _dividend_yield(res, price),
        "sma_50": sma(close, 50),
        "sma_200": sma200,
        "price_vs_sma200_pct": pct(price, sma200),
        "rsi_14": rsi(close[-250:]),
        "history_years": round((ts[-1] - ts[0]) / YEAR, 1),
    }


def zscores(etfs: Sequence[ETF], key: Metric) -> dict[str, float]:
    """Standardize ``key(e)`` across ``etfs``: how many std. deviations above or below average.

    Missing values score 0 (exactly average), so missing data neither helps nor hurts a fund.
    """
    values = {e["ticker"]: key(e) for e in etfs}
    present = [v for v in values.values() if v is not None]
    if len(present) < 2:
        return dict.fromkeys(values, 0.0)
    mean = sum(present) / len(present)
    sd = math.sqrt(sum((v - mean) ** 2 for v in present) / len(present)) or 1.0
    return {t: 0.0 if v is None else (v - mean) / sd for t, v in values.items()}


def _sharpe(e: ETF) -> float | None:
    """Excess 5y return over cash per unit of volatility, so cash-like funds don't win."""
    growth, vol = e["cagr_pct"]["5y"], e["volatility_5y_pct"]
    return (growth - RISK_FREE_PCT) / vol if growth is not None and vol else None


def _negated(value: float | None) -> float | None:
    return None if value is None else -value


def _log_or_none(value: float | None) -> float | None:
    return math.log(value) if value else None


# component name -> (weight, metric); higher metric is better. Weights are heuristics.
LONG_TERM: dict[str, tuple[float, Metric]] = {
    "5y_cagr": (0.20, lambda e: e["cagr_pct"]["5y"]),
    "10y_cagr": (0.20, lambda e: e["cagr_pct"]["10y"]),
    "sharpe_5y": (0.30, _sharpe),
    "max_drawdown_5y": (0.10, lambda e: e["max_drawdown_5y_pct"]),
    "low_expense": (0.15, lambda e: _negated(e["expense_ratio_pct"])),
    "fund_size": (0.05, lambda e: _log_or_none(e["net_assets_bn"])),
}
SHORT_TERM: dict[str, tuple[float, Metric]] = {
    "3m_return": (0.30, lambda e: e["total_return_pct"]["3m"]),
    "6m_return": (0.25, lambda e: e["total_return_pct"]["6m"]),
    "1m_return": (0.10, lambda e: e["total_return_pct"]["1m"]),
    "trend_vs_sma200": (0.20, lambda e: e["price_vs_sma200_pct"]),
    "low_volatility_1y": (0.15, lambda e: _negated(e["volatility_1y_pct"])),
}


def by_score(label: str) -> Callable[[ETF], float]:
    """Return a sort key that puts the highest ``label`` score first."""
    return lambda e: -e["scores"][label]


def score(etfs: Sequence[ETF]) -> None:
    """Attach ``scores``, ``flags`` and ``ranks`` for both horizons to each record, in place."""
    for label, parts in (("long_term", LONG_TERM), ("short_term", SHORT_TERM)):
        z = {name: zscores(etfs, metric) for name, (_, metric) in parts.items()}
        for e in etfs:
            total = sum(weight * z[name][e["ticker"]] for name, (weight, _) in parts.items())
            flags = []
            if label == "long_term" and e["history_years"] < 5:
                total -= 1.0
                flags.append("under 5 years of history")
            if label == "short_term":
                if e["rsi_14"] and e["rsi_14"] > 75:
                    total -= 0.5
                    flags.append("overbought (RSI > 75)")
                if e["price_vs_sma200_pct"] is not None and e["price_vs_sma200_pct"] < 0:
                    flags.append("below 200-day average (downtrend)")
            e.setdefault("scores", {})[label] = round(total, 3)
            if flags:
                e.setdefault("flags", {})[label] = flags
        for rank, e in enumerate(sorted(etfs, key=by_score(label)), 1):
            e.setdefault("ranks", {})[label] = rank


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("tickers", nargs="*", help="analyze only these (comma or space separated)")
    ap.add_argument("--top", type=int, default=15, help="picks per horizon")
    ap.add_argument(
        "--save",
        action="store_true",
        help="also save the full data (every fund analyzed) to reports/data/ for verification",
    )
    return ap.parse_args(argv)


def analyze_all(quotes: dict[str, dict[str, Any] | None], errors: dict[str, str]) -> list[ETF]:
    """Analyze every ticker in parallel; failures are recorded in ``errors``, not raised."""

    def run(ticker: str) -> ETF | None:
        try:
            return analyze(ticker, quotes[ticker])
        except FETCH_ERRORS as e:  # one bad ticker mustn't stop the screen
            errors[ticker] = str(e)
            return None

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return [e for e in pool.map(run, quotes) if e is not None]


def main(argv: Sequence[str] | None = None) -> None:
    """Screen (or analyze the given tickers), score, and print the results as JSON."""
    args = parse_args(argv)
    errors: dict[str, str] = {}
    out: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(), "errors": errors}
    quotes: dict[str, dict[str, Any] | None]
    if args.tickers:
        quotes = {t.strip().upper(): None for a in args.tickers for t in a.split(",") if t.strip()}
        out["mode"] = "tickers"
    else:
        quotes = dict(discover())
        out["mode"] = "discovery"
        out["screeners"] = list(SCREENERS)
        out["filters"] = {
            "min_net_assets": MIN_NET_ASSETS,
            "min_avg_volume": MIN_AVG_VOLUME,
            "excluded": "leveraged/inverse",
        }
        for ticker in BENCHMARKS:
            quotes.setdefault(ticker, None)

    etfs = analyze_all(quotes, errors)
    score(etfs)
    long_picks = sorted(etfs, key=by_score("long_term"))[: args.top]
    short_picks = sorted(etfs, key=by_score("short_term"))[: args.top]
    picked = {e["ticker"] for e in long_picks + short_picks}
    out["candidates_analyzed"] = len(etfs)
    out["long_term_picks"] = long_picks
    out["short_term_picks"] = short_picks
    out["benchmarks"] = [e for e in etfs if e["ticker"] in BENCHMARKS and e["ticker"] not in picked]
    if args.save:
        # full record of every fund analyzed, so a report can be verified against it later
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        path = (
            SAVE_DIR / f"etf-data-{datetime.now(UTC).astimezone().strftime('%Y-%m-%d-%H%M%S')}.json"
        )
        out["saved_to"] = str(path)
        path.write_text(json.dumps({**out, "all_etfs": etfs}, indent=2))
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
