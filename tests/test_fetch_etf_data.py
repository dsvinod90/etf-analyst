import json
from pathlib import Path
from typing import Any

import pytest

import calc
import fetch_etf_data as fetch


def chart_response(prices: list[float], dividends: dict[str, Any] | None = None) -> dict[str, Any]:
    """A minimal Yahoo chart API response with one price per day."""
    day = 86400
    timestamps = [i * day for i in range(len(prices))]
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


def make_etf(ticker: str, **overrides: Any) -> fetch.ETF:
    etf: fetch.ETF = {
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


@pytest.mark.parametrize("ticker", ["VOO", "BRK.B", "BF-B", "SPY"])
def test_valid_tickers_are_accepted(ticker: str) -> None:
    assert fetch.VALID_TICKER.match(ticker)


@pytest.mark.parametrize("ticker", ["../x?y=1", "VOO/../../evil", "voo", "", "A" * 11, "V O O"])
def test_invalid_tickers_are_rejected_before_any_request(
    ticker: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(url: str) -> None:
        raise AssertionError(f"should not fetch {url}")

    monkeypatch.setattr(fetch, "get_json", no_network)
    with pytest.raises(ValueError, match="invalid ticker"):
        fetch.analyze(ticker)


def test_get_json_refuses_other_hosts() -> None:
    with pytest.raises(ValueError, match="non-Yahoo"):
        fetch.get_json("file:///etc/passwd")


def test_analyze_computes_metrics_from_the_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    prices = [100.0 + i for i in range(300)]
    monkeypatch.setattr(fetch, "get_json", lambda url: chart_response(prices))
    etf = fetch.analyze("TEST", {"netExpenseRatio": 0.03, "netAssets": 2.5e9})

    assert etf["price"] == 399.0
    assert etf["expense_ratio_pct"] == 0.03
    assert etf["net_assets_bn"] == 2.5
    assert etf["total_return_pct"]["1m"] == calc.pct(399, 378)
    assert etf["max_drawdown_5y_pct"] == 0.0
    assert etf["rsi_14"] == 100.0
    assert etf["cagr_pct"]["10y"] is None  # under a year of fake history


def test_zscores_treat_missing_values_as_average() -> None:
    etfs = [make_etf("A", rsi_14=10.0), make_etf("B", rsi_14=30.0), make_etf("C", rsi_14=None)]
    z = fetch.zscores(etfs, lambda e: e["rsi_14"])
    assert z["A"] == pytest.approx(-1.0)
    assert z["B"] == pytest.approx(1.0)
    assert z["C"] == 0.0


def test_score_ranks_better_funds_first_and_flags_problems() -> None:
    strong = make_etf("GOOD", cagr_pct={"3y": 20.0, "5y": 20.0, "10y": 20.0})
    weak = make_etf("WEAK", cagr_pct={"3y": 2.0, "5y": 2.0, "10y": 2.0}, history_years=3.0)
    hot = make_etf("HOT", rsi_14=80.0, price_vs_sma200_pct=-1.0)
    etfs = [weak, strong, hot]
    fetch.score(etfs)

    assert strong["ranks"]["long_term"] == 1
    assert weak["flags"]["long_term"] == ["under 5 years of history"]
    assert hot["flags"]["short_term"] == [
        "overbought (RSI > 75)",
        "below 200-day average (downtrend)",
    ]
    assert sorted(e["ranks"]["short_term"] for e in etfs) == [1, 2, 3]


def test_cash_like_funds_do_not_win_on_sharpe() -> None:
    cash_like = make_etf("CASH", cagr_pct={"3y": 4.0, "5y": 4.0, "10y": 4.0}, volatility_5y_pct=0.5)
    assert fetch._sharpe(cash_like) == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("name", "excluded"),
    [
        ("ProShares UltraPro QQQ", True),
        ("Direxion Daily Semiconductor Bull 3X", True),
        ("ProShares Short S&P500", True),
        ("Schwab Short-Term U.S. Treasury ETF", False),
        ("Vanguard S&P 500 ETF", False),
    ],
)
def test_leveraged_and_inverse_funds_are_excluded(name: str, excluded: bool) -> None:
    assert bool(fetch.EXCLUDE_NAME.search(name)) is excluded


def test_discover_keeps_only_liquid_unleveraged_etfs(monkeypatch: pytest.MonkeyPatch) -> None:
    quotes = [
        {
            "symbol": "GOOD",
            "quoteType": "ETF",
            "netAssets": 5e9,
            "averageDailyVolume3Month": 1e6,
            "longName": "Good Fund",
        },
        {"symbol": "TINY", "quoteType": "ETF", "netAssets": 1e8, "averageDailyVolume3Month": 1e6},
        {
            "symbol": "LEV",
            "quoteType": "ETF",
            "netAssets": 5e9,
            "averageDailyVolume3Month": 1e6,
            "longName": "ProShares UltraPro QQQ",
        },
        {"symbol": "STK", "quoteType": "EQUITY", "netAssets": 5e9, "averageDailyVolume3Month": 1e6},
    ]
    monkeypatch.setattr(
        fetch, "get_json", lambda url: {"finance": {"result": [{"quotes": quotes}]}}
    )
    assert list(fetch.discover()) == ["GOOD"]


def test_main_prints_and_saves_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prices = [100.0 + i for i in range(300)]
    monkeypatch.setattr(fetch, "get_json", lambda url: chart_response(prices))
    monkeypatch.setattr(fetch, "SAVE_DIR", tmp_path)
    fetch.main(["VOO,SPY", "../bad", "--top", "1", "--save"])

    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "tickers"
    assert out["candidates_analyzed"] == 2
    assert len(out["long_term_picks"]) == 1
    assert out["errors"] == {"../BAD": "invalid ticker symbol"}
    saved = json.loads(Path(out["saved_to"]).read_text())
    assert {e["ticker"] for e in saved["all_etfs"]} == {"VOO", "SPY"}
