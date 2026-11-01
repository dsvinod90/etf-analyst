import pytest

from etf_analyst import metrics, yahoo
from tests.conftest import NetworkBlockedError
from tests.helpers import chart_response


@pytest.mark.parametrize("ticker", ["VOO", "BRK.B", "BF-B", "SPY"])
def test_valid_tickers_are_accepted(ticker: str) -> None:
    assert yahoo.VALID_TICKER.match(ticker)


@pytest.mark.parametrize("ticker", ["../x?y=1", "VOO/../../evil", "voo", "", "A" * 11, "V O O"])
def test_invalid_tickers_are_rejected_before_any_request(
    ticker: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(url: str) -> None:
        raise AssertionError(f"should not fetch {url}")

    monkeypatch.setattr(yahoo, "get_json", no_network)
    with pytest.raises(ValueError, match="invalid ticker"):
        yahoo.analyze(ticker)


def test_get_json_refuses_other_hosts() -> None:
    with pytest.raises(ValueError, match="non-Yahoo"):
        yahoo.get_json("file:///etc/passwd")


def test_analyze_computes_metrics_from_the_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    prices = [100.0 + i for i in range(300)]
    monkeypatch.setattr(yahoo, "get_json", lambda url: chart_response(prices))
    etf = yahoo.analyze("TEST", {"netExpenseRatio": 0.03, "netAssets": 2.5e9})

    assert etf["price"] == 399.0
    assert etf["expense_ratio_pct"] == 0.03
    assert etf["net_assets_bn"] == 2.5
    assert etf["total_return_pct"]["1m"] == metrics.pct(399, 378)
    assert etf["max_drawdown_5y_pct"] == 0.0
    assert etf["rsi_14"] == 100.0
    assert etf["cagr_pct"]["10y"] is None  # under a year of fake history


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
    assert bool(yahoo.EXCLUDE_NAME.search(name)) is excluded


def test_discover_keeps_only_liquid_unleveraged_etfs(monkeypatch: pytest.MonkeyPatch) -> None:
    liquid = {"quoteType": "ETF", "netAssets": 5e9, "averageDailyVolume3Month": 1e6}
    quotes = [
        {**liquid, "symbol": "GOOD", "longName": "Good Fund"},
        {**liquid, "symbol": "TINY", "netAssets": 1e8},
        {**liquid, "symbol": "LEV", "longName": "ProShares UltraPro QQQ"},
        {**liquid, "symbol": "STK", "quoteType": "EQUITY"},
    ]
    monkeypatch.setattr(
        yahoo, "get_json", lambda url: {"finance": {"result": [{"quotes": quotes}]}}
    )
    assert list(yahoo.discover()) == ["GOOD"]


def test_unmocked_requests_are_blocked_in_tests() -> None:
    """Guards the guard: a real request must fail fast, never reach Yahoo."""
    with pytest.raises(NetworkBlockedError):
        yahoo.get_json(yahoo.CHART_URL.format(t="VOO"))
