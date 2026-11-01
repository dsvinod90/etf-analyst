#!/usr/bin/env python3
"""Check every number in an ETF report's Markdown tables against the raw data.

Usage: verify_tables.py REPORT.md [--data DATA.json]
  The data file defaults to the one named on the report's "Data file:" line,
  else the newest reports/data/etf-data-*.json saved before the report.
  If none exists, fresh data is fetched (fine after the market close, but
  prices may have moved if the report is older than today's session).
Prints JSON: counts, accuracy %, and every mismatch / unverifiable cell.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
DATA_DIR = REPO / "reports" / "data"
TICKER = re.compile(r"^[A-Z]{2,5}$")
NUMBER = re.compile(r"[+\-]?\d[\d,]*\.?\d*")


def field_for(header):
    """Map a table header to a getter on the ETF record (or a list of candidate getters)."""
    h = header.lower().replace("*", "").strip()
    m = re.search(r"(\d+)\s*([my])\b", h)  # "1m", "3m", "6m", "1y" as a return column
    if re.fullmatch(r"(\d+)\s*([my])(\s*return)?", h):
        return [lambda e, k=f"{m[1]}{m[2]}": e["total_return_pct"][k]]
    if "cagr" in h and m:
        return [lambda e, k=f"{m[1]}y": e["cagr_pct"][k]]
    if "vol" in h:
        if "1y" in h and "5y" in h:
            return [lambda e: e["volatility_1y_pct"], lambda e: e["volatility_5y_pct"]]  # "a / b"
        if "1y" in h:
            return [lambda e: e["volatility_1y_pct"]]
        if "5y" in h:
            return [lambda e: e["volatility_5y_pct"]]
        return "either_vol"
    if "max dd" in h or "drawdown" in h:
        return [lambda e: e["max_drawdown_5y_pct"]]
    if "expense" in h or h in ("er", "fee"):
        return [lambda e: e["expense_ratio_pct"]]
    if "yield" in h:
        return [lambda e: e["ttm_dividend_yield_pct"]]
    if "200" in h:
        return [lambda e: e["price_vs_sma200_pct"]]
    if "rsi" in h:
        return [lambda e: e["rsi_14"]]
    if "52" in h:
        return [lambda e: e["pct_below_52w_high"]]
    if h == "price":
        return [lambda e: e["price"]]
    return None  # descriptive column (name, tier, theme, ...)


def parse_numbers(cell):
    cell = cell.replace("−", "-").replace("–", "-").replace("*", "").replace("$", "")
    return [float(n.replace(",", "")) for n in NUMBER.findall(cell)]


def decimals(cell_number_text):
    return len(cell_number_text.split(".")[1]) if "." in cell_number_text else 0


def close_enough(reported, actual, text):
    """Reported values are usually rounded; allow half a unit of the shown precision."""
    tol = 0.5 * 10 ** -decimals(text) + 1e-9
    return abs(reported - actual) <= max(tol, 0.011)


def tables(md):
    """Yield (headers, rows) for each GitHub-style Markdown table."""
    lines = md.splitlines()
    i = 0
    while i < len(lines) - 1:
        if lines[i].strip().startswith("|") and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            split = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
            headers, rows, i = split(lines[i]), [], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split(lines[i]))
                i += 1
            yield headers, rows
        else:
            i += 1


def find_data_file(report_path, md):
    m = re.search(r"Data file:\**\s*`?([^\s`]+\.json)", md)
    if m and Path(m[1]).expanduser().exists():
        return Path(m[1]).expanduser()
    older = [p for p in DATA_DIR.glob("etf-data-*.json") if p.stat().st_mtime <= report_path.stat().st_mtime]
    return max(older, key=lambda p: p.stat().st_mtime) if older else None


def load_etfs(data_path):
    d = json.loads(data_path.read_text())
    etfs = {}
    for key in ("all_etfs", "long_term_picks", "short_term_picks", "benchmarks"):
        for e in d.get(key, []):
            etfs.setdefault(e["ticker"], e)
    return d, etfs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path)
    ap.add_argument("--data", type=Path)
    args = ap.parse_args()
    md = args.report.read_text()

    data_path = args.data or find_data_file(args.report, md)
    note = None
    if not data_path:
        note = "No saved data file for this report; verified against freshly fetched data."
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(REPO / "fetch_etf_data.py"), "--save"],
                       check=True, capture_output=True)
        data_path = max(DATA_DIR.glob("etf-data-*.json"), key=lambda p: p.stat().st_mtime)
    data, etfs = load_etfs(data_path)

    checked = matched = 0
    mismatches, unverifiable = [], []
    for headers, rows in tables(md):
        getters = [field_for(h) for h in headers]
        for row in rows:
            ticker = next((c.replace("*", "").strip() for c in row
                           if TICKER.match(c.replace("*", "").strip())), None)
            if not ticker:
                continue
            e = etfs.get(ticker)
            for header, cell, get in zip(headers, row, getters):
                if get is None or not parse_numbers(cell):
                    continue
                texts = [t for t in NUMBER.findall(cell.replace("−", "-").replace(",", ""))]
                values = parse_numbers(cell)
                if e is None:
                    unverifiable.append({"ticker": ticker, "column": header, "reported": cell,
                                         "reason": "ticker not in data file"})
                    continue
                if get == "either_vol":
                    get = [lambda e: e["volatility_1y_pct"], lambda e: e["volatility_5y_pct"]]
                    pairs = [(v, t, get) for v, t in zip(values, texts)]  # match either window
                else:
                    pairs = [(v, t, [g]) for v, t, g in zip(values, texts, get)]
                for value, text, candidates in pairs:
                    actuals = [g(e) for g in candidates]
                    if all(a is None for a in actuals):
                        unverifiable.append({"ticker": ticker, "column": header, "reported": text,
                                             "reason": "value missing from data feed"})
                        continue
                    checked += 1
                    if any(a is not None and close_enough(value, a, text) for a in actuals):
                        matched += 1
                    else:
                        mismatches.append({"ticker": ticker, "column": header, "reported": text,
                                           "actual": [a for a in actuals if a is not None]})

    json.dump({
        "report": str(args.report),
        "data_file": str(data_path),
        "data_generated_at": data.get("generated_at"),
        "note": note,
        "cells_checked": checked,
        "cells_matched": matched,
        "numeric_accuracy_pct": round(100 * matched / checked, 1) if checked else None,
        "mismatches": mismatches,
        "unverifiable": unverifiable,
    }, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
