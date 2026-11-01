"""Price-series metrics: percent change, moving average, RSI, volatility, drawdown, CAGR.

Pure functions: lists of numbers in, a number (or None when there isn't enough data) out.
Percentages are returned as percent numbers (12.34 means 12.34%).
"""

import math
from collections.abc import Sequence

TRADING_DAYS = 252
YEAR = 365.25 * 86400  # seconds
WEEK = 7 * 86400  # seconds


def pct(a: float | None, b: float | None) -> float | None:
    """Return the percent change from ``b`` to ``a``, rounded to 2 decimals.

    Example: ``pct(110, 100)`` is ``10.0``. Returns None if either value is missing or ``b`` is 0.
    """
    if a is None or b is None or b == 0:
        return None
    return round((a / b - 1) * 100, 2)


def sma(xs: Sequence[float], n: int) -> float | None:
    """Return the simple moving average: the mean of the last ``n`` values.

    Returns None if there are fewer than ``n`` values.
    """
    if len(xs) < n:
        return None
    return round(sum(xs[-n:]) / n, 2)


def rsi(xs: Sequence[float], n: int = 14) -> float | None:
    """Return the relative strength index (0-100) of a price series, with Wilder's smoothing.

    Compares the average size of up moves with down moves over ``n`` periods: above 70 means
    the price has risen unusually fast (overbought), below 30 that it has fallen unusually fast
    (oversold). Returns None if there are ``n`` or fewer prices.
    """
    if len(xs) <= n:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        change = xs[i] - xs[i - 1]
        gains += max(change, 0)
        losses += max(-change, 0)
    avg_gain, avg_loss = gains / n, losses / n
    for i in range(n + 1, len(xs)):
        change = xs[i] - xs[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(change, 0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-change, 0)) / n
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 1)


def volatility(xs: Sequence[float]) -> float | None:
    """Return annualized volatility in %: the std. deviation of daily returns x sqrt(252).

    15 means a typical year lands roughly 15 points above or below the average return.
    Returns None if there are fewer than 3 prices.
    """
    returns = [xs[i] / xs[i - 1] - 1 for i in range(1, len(xs))]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(TRADING_DAYS) * 100, 2)


def max_drawdown(xs: Sequence[float]) -> float:
    """Return the largest peak-to-low drop in the series, in % (0 or negative).

    -25 means a value of 100 fell to 75 at the worst point.
    """
    peak, worst = xs[0], 0.0
    for x in xs:
        peak = max(peak, x)
        worst = min(worst, x / peak - 1)
    return round(worst * 100, 2)


def cagr(xs: Sequence[float], ts: Sequence[float], years: float) -> float | None:
    """Return the compound annual growth rate in % over the last ``years`` years.

    Args:
        xs: Prices, oldest first.
        ts: Unix timestamps (seconds) of those prices.
        years: Length of the period to measure.

    Starts from the first price on or after the start date and annualizes over the exact
    time elapsed. Returns None if the series starts more than a week after the start date
    (not enough history).
    """
    target = ts[-1] - years * YEAR
    if ts[0] > target + WEEK:
        return None
    start = next(i for i, t in enumerate(ts) if t >= target)
    growth = float((xs[-1] / xs[start]) ** (YEAR / (ts[-1] - ts[start])))
    return round((growth - 1) * 100, 2)
