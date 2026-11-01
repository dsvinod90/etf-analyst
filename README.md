# etf-analyst

A Claude Code agent that scans the US ETF market with live prices, ranks ETFs for long-term and short-term investing, and explains the best picks.

## How it works

1. `fetch_etf_data.py` pulls ~200 candidates from Yahoo Finance's ETF screeners (Morningstar 4–5 star funds and today's top movers), keeps liquid, unleveraged funds (≥ $1B assets, ≥ 100k avg volume), and adds a few benchmarks (SPY, VOO, VTI, QQQM, VT, VXUS, SCHD, BND).
2. For each fund it computes returns, CAGR, volatility, max drawdown, dividend yield, moving averages and RSI, then scores it:
   - **Long-term:** 5y/10y CAGR, Sharpe ratio, max drawdown, expense ratio, fund size.
   - **Short-term:** 1m/3m/6m momentum, trend vs 200-day average, volatility; overbought funds penalized.
3. The agent researches the top picks, groups duplicates (e.g. VOO/IVV/SPY), and writes a report explaining why each pick fits each horizon.
4. The report is saved to `reports/etf-report-<date>.md` and published as `reports/etf-report-<date>.pdf` by `make_pdf.py`. The `reports/` folder is git-ignored.

No API key needed. The data script uses only the Python 3 standard library. The PDF step needs Google Chrome plus either `pandoc` (`brew install pandoc`) or the Python `markdown` package.

## Setup

```sh
git clone <this repo> ~/Dev/etf-analyst
ln -s ~/Dev/etf-analyst/.claude/agents/etf-analyst.md ~/.claude/agents/etf-analyst.md
```

The symlink makes the agent available in every Claude Code session. The agent runs the script from `~/Dev/etf-analyst/`; if you clone somewhere else, update the path in `.claude/agents/etf-analyst.md`.

## Usage

In Claude Code: *"Run the etf-analyst"*, *"Which ETFs are good for long-term investing right now?"*, or *"Compare VOO, QQQM and SCHD."*

Run the script directly:

```sh
./fetch_etf_data.py                # screen the market, top 15 per horizon
./fetch_etf_data.py --top 25       # longer lists
./fetch_etf_data.py VOO QQQM SCHD  # rank only these tickers
./make_pdf.py reports/etf-report-2026-10-30.md   # Markdown report -> PDF
```

Output is informational analysis, not financial advice.
