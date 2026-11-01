"""Score and rank ETFs for long-term and short-term investing.

Each metric is standardized across all funds (a z-score), weighted, and summed. The weights are
heuristics, not predictions; the agents treat the result as a screen, not a verdict.
"""

import math
from collections.abc import Callable, Sequence

from etf_analyst.records import ETF

Metric = Callable[[ETF], float | None]
RISK_FREE_PCT = 4.0  # approx. cash/T-bill yield used for the Sharpe ratio


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
