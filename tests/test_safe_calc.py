import ast
import time

import pytest

from etf_analyst import safe_calc


def run(expr: str) -> float:
    return safe_calc.evaluate(ast.parse(expr, mode="eval"))


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
    safe_calc.main(["1 + 1", "x"])
    out = capsys.readouterr().out
    assert "1 + 1 = 2" in out
    assert "x -> error: not allowed" in out
