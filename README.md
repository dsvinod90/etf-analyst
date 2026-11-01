# etf-analyst

A Claude Code agent that fetches the latest prices for an ETF watchlist and analyzes which ETFs are better suited for long-term vs short-term investing.

## Contents

| File | Purpose |
|------|---------|
| `fetch_etf_data.py` | Pulls price history from Yahoo Finance (no API key) and computes returns, CAGR, volatility, max drawdown, dividend yield, SMAs and RSI. Outputs JSON. Python 3 stdlib only. |
| `watchlist.txt` | Tickers to track, one per line. |
| `.claude/agents/etf-analyst.md` | The Claude Code subagent definition. |

## Setup

```sh
git clone <this repo> ~/Dev/etf-analyst
ln -s ~/Dev/etf-analyst/.claude/agents/etf-analyst.md ~/.claude/agents/etf-analyst.md
```

The symlink makes the agent available in every Claude Code session. The agent runs the script from `~/Dev/etf-analyst/`; if you clone somewhere else, update the paths in `.claude/agents/etf-analyst.md`.

## Usage

In Claude Code: *"Run the etf-analyst"* or *"Ask etf-analyst whether VOO or QQQM is better long term."*

Run the script directly:

```sh
./fetch_etf_data.py              # uses watchlist.txt
./fetch_etf_data.py VOO QQQM     # specific tickers
```

Output is informational analysis, not financial advice.
