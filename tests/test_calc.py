import ast
import math
import statistics
import time

import pytest

import calc


def run(expr: str) -> float:
    return calc.evaluate(ast.parse(expr, mode="eval"))


# --- metrics -----------------------------------------------------------------------------


class TestPct:
    def test_percent_change(self) -> None:
        assert calc.pct(110, 100) == 10.0
        assert calc.pct(75, 100) == -25.0

    @pytest.mark.parametrize(("a", "b"), [(None, 100), (100, None), (100, 0)])
    def test_missing_or_zero_base_is_none(self, a: float | None, b: float | None) -> None:
        assert calc.pct(a, b) is None


def test_sma_averages_the_last_n_values() -> None:
    assert calc.sma([1, 2, 3, 4], 2) == 3.5


def test_sma_is_none_without_enough_values() -> None:
    assert calc.sma([1, 2], 3) is None


class TestRsi:
    def test_only_gains_is_100(self) -> None:
        assert calc.rsi(list(range(1, 30))) == 100.0

    def test_only_losses_is_0(self) -> None:
        assert calc.rsi(list(range(30, 1, -1))) == 0.0

    def test_mixed_moves_are_between_0_and_100(self) -> None:
        prices = [100 + (i % 5) - (i % 3) for i in range(40)]
        result = calc.rsi(prices)
        assert result is not None
        assert 0 < result < 100

    def test_none_without_more_than_n_prices(self) -> None:
        assert calc.rsi(list(range(14))) is None


def test_volatility_matches_annualized_sample_stdev() -> None:
    prices = [100, 101, 99, 102, 101.5, 103]
    returns = [b / a - 1 for a, b in zip(prices, prices[1:], strict=False)]
    expected = statistics.stdev(returns) * math.sqrt(calc.TRADING_DAYS) * 100
    assert calc.volatility(prices) == round(expected, 2)


def test_volatility_needs_three_prices() -> None:
    assert calc.volatility([100, 101]) is None


def test_max_drawdown_finds_the_worst_peak_to_low_drop() -> None:
    assert calc.max_drawdown([100, 120, 90, 130, 110]) == -25.0  # 120 -> 90


def test_max_drawdown_is_zero_when_never_falling() -> None:
    assert calc.max_drawdown([1, 2, 3]) == 0.0


class TestCagr:
    TS = (0.0, calc.YEAR, 2 * calc.YEAR)

    def test_annualizes_growth(self) -> None:
        assert calc.cagr([100, 110, 121], self.TS, 2) == 10.0

    def test_none_without_enough_history(self) -> None:
        assert calc.cagr([100, 110, 121], self.TS, 3) is None


# --- safe calculator ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("2 + 3 * 4", 14),
        ("(2 + 3) * 4", 20),
        ("-5 + abs(-2)", -3),
        ("10000 * 1.1542 ** 10", 10000 * 1.1542**10),
        ("round(12.3456, 2)", 12.35),
        ("max(1, 7, 3) - min(4, 2)", 5),
        ("7 // 2 + 7 % 2", 4),
    ],
)
def test_evaluates_plain_arithmetic(expr: str, expected: float) -> None:
    assert run(expr) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('id')",  # imports / calls
        "open('/etc/passwd').read()",
        "(1).__class__",  # attribute access
        "x + 1",  # names
        "'a' * 3",  # strings
        "[1, 2][0]",  # lists and subscripts
        "(lambda: 1)()",  # lambdas
        "True + 1",  # booleans aren't numbers here
        "round(x=1)",  # keyword arguments
    ],
)
def test_refuses_anything_but_math(expr: str) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        run(expr)


@pytest.mark.parametrize(
    "expr",
    [
        "10 ** 101",
        "(((10 ** 1000) ** 1000) ** 1000)",
        "9 ** 9 ** 9",
        "1" + "0" * 200,  # huge literal
        "10 ** 99 * 10 ** 99",
    ],
)
def test_refuses_oversized_results(expr: str) -> None:
    with pytest.raises(ValueError, match="too large"):
        run(expr)


@pytest.mark.parametrize("digits", ["-1000000000", "-1", "11", "2.5"])
def test_round_digits_must_be_0_to_10(digits: str) -> None:
    with pytest.raises(ValueError, match="digits"):
        run(f"round(1.5, {digits})")


def test_denial_of_service_attempts_fail_fast() -> None:
    start = time.perf_counter()
    for expr in ("round(1, -1000000000)", "(((10 ** 1000) ** 1000) ** 1000)"):
        with pytest.raises(ValueError):
            run(expr)
    assert time.perf_counter() - start < 0.5


def test_division_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        run("1 / 0")


def test_main_prints_results_and_errors(capsys: pytest.CaptureFixture[str]) -> None:
    calc.main(["1 + 1", "x"])
    out = capsys.readouterr().out
    assert "1 + 1 = 2" in out
    assert "x -> error: not allowed" in out
