"""Screen the ETF market (or given tickers), score the funds, and print the results as JSON.

Usage:
    etf-screen                 # discover candidates from Yahoo screeners and rank them
    etf-screen VOO QQQM ...    # analyze and rank only these tickers
    etf-screen --top 20        # number of picks per horizon (default 15)
    etf-screen --save          # also save every fund analyzed to reports/data/
"""

import argparse
import json
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from etf_analyst import paths
from etf_analyst.records import ETF
from etf_analyst.scoring import by_score, score
from etf_analyst.yahoo import (
    FETCH_ERRORS,
    MIN_AVG_VOLUME,
    MIN_NET_ASSETS,
    SCREENERS,
    analyze,
    discover,
)

# Always included so picks can be compared against the obvious defaults
BENCHMARKS = ("SPY", "VOO", "VTI", "QQQM", "VT", "VXUS", "SCHD", "BND")
WORKERS = 8  # parallel downloads; enough for speed without being rate-limited


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("tickers", nargs="*", help="analyze only these (comma or space separated)")
    ap.add_argument("--top", type=int, default=15, help="picks per horizon")
    ap.add_argument(
        "--save",
        action="store_true",
        help="also save the full data (every fund analyzed) to reports/data/ for verification",
    )
    return ap.parse_args(argv)


def analyze_all(quotes: dict[str, dict[str, Any] | None], errors: dict[str, str]) -> list[ETF]:
    """Analyze every ticker in parallel; failures are recorded in ``errors``, not raised."""

    def run(ticker: str) -> ETF | None:
        try:
            return analyze(ticker, quotes[ticker])
        except FETCH_ERRORS as e:  # one bad ticker mustn't stop the screen
            errors[ticker] = str(e)
            return None

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return [e for e in pool.map(run, quotes) if e is not None]


def _ticker_list(args: Sequence[str]) -> list[str]:
    """Split ``["VOO,SPY", "qqqm"]`` into ``["VOO", "SPY", "QQQM"]``."""
    return [t.strip().upper() for a in args for t in a.split(",") if t.strip()]


def run_screen(tickers: Sequence[str] = (), top: int = 15, save: bool = False) -> dict[str, Any]:
    """Screen the market (or analyze ``tickers``), score every fund, and return the results.

    Args:
        tickers: Analyze only these symbols. Empty means discover candidates from the screeners
            and add the benchmarks.
        top: Number of picks to return per horizon.
        save: Also write every fund analyzed to ``reports/data/`` and record the path in
            ``saved_to``, so a report built from these results can be verified later.

    Returns:
        A JSON-ready dict: ``long_term_picks``, ``short_term_picks``, ``benchmarks``,
        ``errors`` (ticker -> message) and run metadata.
    """
    errors: dict[str, str] = {}
    out: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(), "errors": errors}
    quotes: dict[str, dict[str, Any] | None]
    if tickers:
        quotes = dict.fromkeys(tickers)
        out["mode"] = "tickers"
    else:
        quotes = dict(discover())
        out["mode"] = "discovery"
        out["screeners"] = list(SCREENERS)
        out["filters"] = {
            "min_net_assets": MIN_NET_ASSETS,
            "min_avg_volume": MIN_AVG_VOLUME,
            "excluded": "leveraged/inverse",
        }
        for ticker in BENCHMARKS:
            quotes.setdefault(ticker, None)

    etfs = analyze_all(quotes, errors)
    score(etfs)
    long_picks = sorted(etfs, key=by_score("long_term"))[:top]
    short_picks = sorted(etfs, key=by_score("short_term"))[:top]
    picked = {e["ticker"] for e in long_picks + short_picks}
    out["candidates_analyzed"] = len(etfs)
    out["long_term_picks"] = long_picks
    out["short_term_picks"] = short_picks
    out["benchmarks"] = [e for e in etfs if e["ticker"] in BENCHMARKS and e["ticker"] not in picked]
    if save:
        out["saved_to"] = str(_save(out, etfs))
    return out


def _save(out: dict[str, Any], etfs: list[ETF]) -> Path:
    """Write the results plus every fund analyzed to a new file in ``reports/data/``."""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).astimezone().strftime("%Y-%m-%d-%H%M%S")
    path = paths.DATA_DIR / f"etf-data-{stamp}.json"
    path.write_text(json.dumps({**out, "saved_to": str(path), "all_etfs": etfs}, indent=2))
    return path


def main(argv: Sequence[str] | None = None) -> None:
    """Run the screen from the command line and print the results as JSON."""
    args = parse_args(argv)
    out = run_screen(_ticker_list(args.tickers), args.top, args.save)
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
