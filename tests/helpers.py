"""Builders for fake API responses and ETF records used across tests."""

from typing import Any

from etf_analyst.records import ETF

DAY = 86400  # seconds


def chart_response(prices: list[float], dividends: dict[str, Any] | None = None) -> dict[str, Any]:
    """A minimal Yahoo chart API response with one price per day."""
    timestamps = [i * DAY for i in range(len(prices))]
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": prices[-1],
                        "regularMarketTime": timestamps[-1],
                        "longName": "Test Fund",
                    },
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [{"close": prices}],
                        "adjclose": [{"adjclose": prices}],
                    },
                    "events": {"dividends": dividends or {}},
                }
            ]
        }
    }


def make_etf(ticker: str, **overrides: Any) -> ETF:
    """An average-looking fund record; override any field."""
    etf: ETF = {
        "ticker": ticker,
        "cagr_pct": {"3y": 10.0, "5y": 10.0, "10y": 10.0},
        "volatility_1y_pct": 15.0,
        "volatility_5y_pct": 15.0,
        "max_drawdown_5y_pct": -20.0,
        "expense_ratio_pct": 0.1,
        "net_assets_bn": 10.0,
        "total_return_pct": {"1m": 1.0, "3m": 3.0, "6m": 6.0, "1y": 12.0},
        "price_vs_sma200_pct": 5.0,
        "rsi_14": 55.0,
        "history_years": 10.0,
    }
    etf.update(overrides)
    return etf
