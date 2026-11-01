"""Yahoo Finance client: screen for ETFs and turn one fund's price history into metrics.

Uses the public screener and chart APIs (no key required). Only https requests to the Yahoo
Finance API host are made, with a timeout; ticker symbols are validated and URL-encoded.
"""

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from etf_analyst.metrics import TRADING_DAYS, YEAR, cagr, max_drawdown, pct, rsi, sma, volatility
from etf_analyst.records import ETF

API_ROOT = "https://query1.finance.yahoo.com/"
SCREENER_URL = (
    "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={s}&count=250"
)
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=10y&interval=1d&events=div"
# top_performing_etfs: Morningstar 4-5 star funds; top_etfs_us: today's biggest movers
SCREENERS = ("top_performing_etfs", "top_etfs_us")
MIN_NET_ASSETS = 1e9
MIN_AVG_VOLUME = 100_000
EXCLUDE_NAME = re.compile(
    r"\b(2x|3x|-1x|-2x|-3x|ultra|ultrapro|bull|bear|inverse|leveraged|daily)\b"
    r"|\bshort\b(?![- ](term|duration|maturity))",  # keep "short-term Treasury" funds
    re.IGNORECASE,
)
VALID_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")  # e.g. VOO, BRK.B, BF-B
REQUEST_TIMEOUT = 20  # seconds
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
