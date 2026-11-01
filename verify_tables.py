#!/usr/bin/env python3
"""Check every number in an ETF report's Markdown tables against the raw data.

The data file defaults to the one named on the report's "Data file:" line, else the newest
``reports/data/etf-data-*.json`` saved before the report. If none exists, fresh data is
fetched (fine after the market close, but prices may have moved if the report is older than
today's session). Prints JSON: counts, accuracy %, and every mismatch / unverifiable cell.

Usage:
    verify_tables.py REPORT.md [--data DATA.json]
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent
REPORTS_DIR = REPO / "reports"
DATA_DIR = REPORTS_DIR / "data"
TICKER = re.compile(r"^[A-Z]{2,5}$")
NUMBER = re.compile(r"[+\-]?\d[\d,]*\.?\d*")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")  # the |---|---| line under a table header
DATA_FILE_LINE = re.compile(r"Data file:\**\s*`?([^\s`]+\.json)")
MIN_TOLERANCE = 0.011  # always allow a rounding difference of about one cent / 0.01 point
DASHES = str.maketrans({"−": "-", "–": "-"})  # typographic minus / en dash -> ASCII

ETF = dict[str, Any]
Getter = Callable[[ETF], float | None]


@dataclass(frozen=True)
class Column:
    """How to check one table column against an ETF record.

    Attributes:
        getters: Where the column's number(s) come from. A cell like ``"12.8% / 16.9%"``
            under "Volatility (1y / 5y)" has one getter per number, in order.
        any_of: If True, each number in the cell may match *any* getter (used when a
            header says "Volatility" without saying which window).
    """

    getters: tuple[Getter, ...]
    any_of: bool = False


@dataclass
class Result:
    """Counts and details accumulated while checking a report."""

    checked: int = 0
    matched: int = 0
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    unverifiable: list[dict[str, Any]] = field(default_factory=list)

    @property
    def accuracy_pct(self) -> float | None:
        """Percentage of checked cells that matched, or None if nothing was checked."""
        return round(100 * self.matched / self.checked, 1) if self.checked else None


def _return(period: str) -> Getter:
    return lambda e: e["total_return_pct"][period]


def _cagr(years: str) -> Getter:
    return lambda e: e["cagr_pct"][f"{years}y"]


def _key(name: str) -> Getter:
    return lambda e: e[name]


def column_for(header: str) -> Column | None:
    """Map a table header to the ETF field(s) it shows, or None for descriptive columns."""
    h = header.lower().replace("*", "").strip()
    period = re.fullmatch(r"(\d+)\s*([my])(\s*return)?", h)  # "1m", "3m", "6m", "1y"
    if period:
        return Column((_return(f"{period[1]}{period[2]}"),))
    years = re.search(r"(\d+)\s*y\b", h)
    if "cagr" in h and years:
        return Column((_cagr(years[1]),))
    if "vol" in h:
        one_year, five_year = _key("volatility_1y_pct"), _key("volatility_5y_pct")
        if "1y" in h and "5y" in h:
            return Column((one_year, five_year))
        if "1y" in h:
            return Column((one_year,))
        if "5y" in h:
            return Column((five_year,))
        return Column((one_year, five_year), any_of=True)
    simple = {
        "max dd": "max_drawdown_5y_pct",
        "drawdown": "max_drawdown_5y_pct",
        "expense": "expense_ratio_pct",
        "yield": "ttm_dividend_yield_pct",
        "200": "price_vs_sma200_pct",
        "rsi": "rsi_14",
        "52": "pct_below_52w_high",
    }
    for needle, name in simple.items():
        if needle in h:
            return Column((_key(name),))
    if h in ("er", "fee"):
        return Column((_key("expense_ratio_pct"),))
    if h == "price":
        return Column((_key("price"),))
    return None  # descriptive column (name, tier, theme, ...)


def number_texts(cell: str) -> list[str]:
    """Return the numbers in a table cell as text, e.g. ``"−24.52%"`` -> ``["-24.52"]``."""
    cleaned = cell.translate(DASHES).replace("*", "").replace("$", "").replace(",", "")
    return NUMBER.findall(cleaned)


def decimals(number_text: str) -> int:
    """Return how many decimal places a number was written with (``"12.30"`` -> 2)."""
    return len(number_text.split(".")[1]) if "." in number_text else 0


def close_enough(reported: float, actual: float, text: str) -> bool:
    """Reported values are usually rounded; allow half a unit of the shown precision."""
    tolerance = max(0.5 * 10.0 ** -decimals(text) + 1e-9, MIN_TOLERANCE)
    return abs(reported - actual) <= tolerance


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def tables(md: str) -> Iterator[tuple[list[str], list[list[str]]]]:
    """Yield ``(headers, rows)`` for each GitHub-style Markdown table in ``md``."""
    lines = md.splitlines()
    i = 0
    while i < len(lines) - 1:
        if lines[i].strip().startswith("|") and TABLE_RULE.match(lines[i + 1]):
            headers, rows, i = _split_row(lines[i]), [], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            yield headers, rows
        else:
            i += 1


def in_dir(path: Path | str, base: Path, suffix: str, what: str) -> Path:
    """Resolve ``path`` and exit unless it's a ``suffix`` file inside ``base``.

    Reports are written by an agent that reads the web, so paths from them are untrusted.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_relative_to(base.resolve()) or resolved.suffix != suffix:
        sys.exit(f"{what} must be a {suffix} file inside {base}")
    return resolved


def find_data_file(report_path: Path, md: str) -> Path | None:
    """Find the data file a report was built from, accepting only files in ``DATA_DIR``."""
    m = DATA_FILE_LINE.search(md)
    if m:
        candidate = Path(m[1]).expanduser().resolve()
        if candidate.is_relative_to(DATA_DIR.resolve()) and candidate.exists():
            return candidate
    report_time = report_path.stat().st_mtime
    older = [p for p in DATA_DIR.glob("etf-data-*.json") if p.stat().st_mtime <= report_time]
    return max(older, key=lambda p: p.stat().st_mtime) if older else None


def fetch_fresh_data() -> Path:
    """Run the screener with ``--save`` and return the data file it wrote."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(REPO / "fetch_etf_data.py"), "--save"],
        check=True,
        capture_output=True,
    )
    return max(DATA_DIR.glob("etf-data-*.json"), key=lambda p: p.stat().st_mtime)


def load_etfs(data_path: Path) -> tuple[dict[str, Any], dict[str, ETF]]:
    """Return the data file's contents and its ETF records keyed by ticker."""
    data = json.loads(data_path.read_text())
    etfs: dict[str, ETF] = {}
    for key in ("all_etfs", "long_term_picks", "short_term_picks", "benchmarks"):
        for e in data.get(key, []):
            etfs.setdefault(e["ticker"], e)
    return data, etfs


def _row_ticker(row: Sequence[str]) -> str | None:
    cells = (c.replace("*", "").strip() for c in row)
    return next((c for c in cells if TICKER.match(c)), None)


def _check_cell(
    result: Result, ticker: str, header: str, cell: str, column: Column, e: ETF
) -> None:
    texts = number_texts(cell)
    if column.any_of:
        pairs = [(text, column.getters) for text in texts]
    else:
        pairs = [(text, (getter,)) for text, getter in zip(texts, column.getters, strict=False)]
    for text, getters in pairs:
        actuals = [a for a in (g(e) for g in getters) if a is not None]
        if not actuals:
            result.unverifiable.append(
                {
                    "ticker": ticker,
                    "column": header,
                    "reported": text,
                    "reason": "value missing from data feed",
                }
            )
            continue
        result.checked += 1
        if any(close_enough(float(text), a, text) for a in actuals):
            result.matched += 1
        else:
            result.mismatches.append(
                {"ticker": ticker, "column": header, "reported": text, "actual": actuals}
            )


def check_report(md: str, etfs: dict[str, ETF]) -> Result:
    """Compare every number in ``md``'s tables with the matching field in ``etfs``."""
    result = Result()
    for headers, rows in tables(md):
        columns = [column_for(h) for h in headers]
        for row in rows:
            ticker = _row_ticker(row)
            if ticker is None:
                continue
            e = etfs.get(ticker)
            for header, cell, column in zip(headers, row, columns, strict=False):
                if column is None or not number_texts(cell):
                    continue
                if e is None:
                    result.unverifiable.append(
                        {
                            "ticker": ticker,
                            "column": header,
                            "reported": cell,
                            "reason": "ticker not in data file",
                        }
                    )
                    continue
                _check_cell(result, ticker, header, cell, column, e)
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("report", type=Path, help="the report's Markdown file, inside reports/")
    ap.add_argument("--data", type=Path, help="data file to check against, inside reports/data/")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Check the report given on the command line and print the results as JSON."""
    args = parse_args(argv)
    report = in_dir(args.report, REPORTS_DIR, ".md", "report")
    md = report.read_text()

    note = None
    if args.data:
        data_path = in_dir(args.data, DATA_DIR, ".json", "data file")
    else:
        found = find_data_file(report, md)
        if found is None:
            note = "No saved data file for this report; verified against freshly fetched data."
            found = fetch_fresh_data()
        data_path = found
    data, etfs = load_etfs(data_path)
    result = check_report(md, etfs)

    json.dump(
        {
            "report": str(report),
            "data_file": str(data_path),
            "data_generated_at": data.get("generated_at"),
            "note": note,
            "cells_checked": result.checked,
            "cells_matched": result.matched,
            "numeric_accuracy_pct": result.accuracy_pct,
            "mismatches": result.mismatches,
            "unverifiable": result.unverifiable,
        },
        sys.stdout,
        indent=2,
    )
    print()


if __name__ == "__main__":
    main()
