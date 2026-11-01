import math
import statistics

import pytest

from etf_analyst import metrics


class TestPct:
    def test_percent_change(self) -> None:
        assert metrics.pct(110, 100) == 10.0
        assert metrics.pct(75, 100) == -25.0

    @pytest.mark.parametrize(("a", "b"), [(None, 100), (100, None), (100, 0)])
    def test_missing_or_zero_base_is_none(self, a: float | None, b: float | None) -> None:
        assert metrics.pct(a, b) is None


def test_sma_averages_the_last_n_values() -> None:
    assert metrics.sma([1, 2, 3, 4], 2) == 3.5


def test_sma_is_none_without_enough_values() -> None:
    assert metrics.sma([1, 2], 3) is None


class TestRsi:
    def test_only_gains_is_100(self) -> None:
        assert metrics.rsi(list(range(1, 30))) == 100.0

    def test_only_losses_is_0(self) -> None:
        assert metrics.rsi(list(range(30, 1, -1))) == 0.0

    def test_mixed_moves_are_between_0_and_100(self) -> None:
        prices = [100 + (i % 5) - (i % 3) for i in range(40)]
        result = metrics.rsi(prices)
        assert result is not None
        assert 0 < result < 100

    def test_none_without_more_than_n_prices(self) -> None:
        assert metrics.rsi(list(range(14))) is None


def test_volatility_matches_annualized_sample_stdev() -> None:
    prices = [100, 101, 99, 102, 101.5, 103]
    returns = [b / a - 1 for a, b in zip(prices, prices[1:], strict=False)]
    expected = statistics.stdev(returns) * math.sqrt(metrics.TRADING_DAYS) * 100
    assert metrics.volatility(prices) == round(expected, 2)


def test_volatility_needs_three_prices() -> None:
    assert metrics.volatility([100, 101]) is None


def test_max_drawdown_finds_the_worst_peak_to_low_drop() -> None:
    assert metrics.max_drawdown([100, 120, 90, 130, 110]) == -25.0  # 120 -> 90


def test_max_drawdown_is_zero_when_never_falling() -> None:
    assert metrics.max_drawdown([1, 2, 3]) == 0.0


class TestCagr:
    TS = (0.0, metrics.YEAR, 2 * metrics.YEAR)

    def test_annualizes_growth(self) -> None:
        assert metrics.cagr([100, 110, 121], self.TS, 2) == 10.0

    def test_none_without_enough_history(self) -> None:
        assert metrics.cagr([100, 110, 121], self.TS, 3) is None
