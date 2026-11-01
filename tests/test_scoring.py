import pytest

from etf_analyst import scoring
from tests.helpers import make_etf


def test_zscores_treat_missing_values_as_average() -> None:
    etfs = [make_etf("A", rsi_14=10.0), make_etf("B", rsi_14=30.0), make_etf("C", rsi_14=None)]
    z = scoring.zscores(etfs, lambda e: e["rsi_14"])
    assert z["A"] == pytest.approx(-1.0)
    assert z["B"] == pytest.approx(1.0)
    assert z["C"] == 0.0


def test_zscores_are_all_zero_with_fewer_than_two_values() -> None:
    assert scoring.zscores([make_etf("A")], lambda e: e["rsi_14"]) == {"A": 0.0}


def test_score_ranks_better_funds_first_and_flags_problems() -> None:
    strong = make_etf("GOOD", cagr_pct={"3y": 20.0, "5y": 20.0, "10y": 20.0})
    weak = make_etf("WEAK", cagr_pct={"3y": 2.0, "5y": 2.0, "10y": 2.0}, history_years=3.0)
    hot = make_etf("HOT", rsi_14=80.0, price_vs_sma200_pct=-1.0)
    etfs = [weak, strong, hot]
    scoring.score(etfs)

    assert strong["ranks"]["long_term"] == 1
    assert weak["flags"]["long_term"] == ["under 5 years of history"]
    assert hot["flags"]["short_term"] == [
        "overbought (RSI > 75)",
        "below 200-day average (downtrend)",
    ]
    assert sorted(e["ranks"]["short_term"] for e in etfs) == [1, 2, 3]


def test_cash_like_funds_do_not_win_on_sharpe() -> None:
    cash_like = make_etf("CASH", cagr_pct={"3y": 4.0, "5y": 4.0, "10y": 4.0}, volatility_5y_pct=0.5)
    assert scoring._sharpe(cash_like) == pytest.approx(0.0)


def test_weights_sum_to_one_per_horizon() -> None:
    for parts in (scoring.LONG_TERM, scoring.SHORT_TERM):
        assert sum(weight for weight, _ in parts.values()) == pytest.approx(1.0)
