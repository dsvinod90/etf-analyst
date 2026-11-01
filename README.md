# etf-analyst

Claude Code agents that scan the US ETF market with live prices, rank ETFs for long-term and short-term investing, explain the best picks, and independently verify the report.

## How it works

1. `etf-screen` pulls ~200 candidates from Yahoo Finance's ETF screeners (Morningstar 4–5 star funds and today's top movers), keeps liquid, unleveraged funds (≥ $1B assets, ≥ 100k avg volume), and adds a few benchmarks (SPY, VOO, VTI, QQQM, VT, VXUS, SCHD, BND).
2. For each fund it computes returns, CAGR, volatility, max drawdown, dividend yield, moving averages and RSI, then scores it:
   - **Long-term:** 5y/10y CAGR, Sharpe ratio, max drawdown, expense ratio, fund size.
   - **Short-term:** 1m/3m/6m momentum, trend vs 200-day average, volatility; overbought funds penalized.
3. The **etf-analyst** agent researches the top picks, groups duplicates (e.g. VOO/IVV/SPY), and writes a report explaining why each pick fits each horizon. It's saved to `reports/etf-report-<date>.md` and published as a PDF by `etf-pdf`; the raw data is saved to `reports/data/`. The `reports/` folder is git-ignored.
4. The **etf-report-verifier** agent checks the report independently and gives it a 0–100 confidence score:
   - `etf-verify` compares every number in the report's tables with the saved raw data.
   - The agent checks numbers and arithmetic in the prose (with `etf-calc`), fact-checks the main news claims with web search, reviews whether the conclusions follow from the data, and checks completeness.
   - Scoring: data accuracy 40, factual claims 25, reasoning 20, completeness 15. An error that would change a recommendation caps the score at 74, and so does table accuracy below 98% (checked in code).
   - The final PDF gets a confidence badge and the verification as an appendix.

No API key needed. The package uses only the Python 3.12 standard library. The PDF step needs Google Chrome plus either `pandoc` (`brew install pandoc`) or the Python `markdown` package.

## Layout

```
src/etf_analyst/
  metrics.py     price-series math: pct, sma, rsi, volatility, max_drawdown, cagr
  yahoo.py       Yahoo Finance client: screen for ETFs, compute one fund's metrics
  scoring.py     z-scores, weights and ranks for each horizon
  screen.py      etf-screen  — run the screen, print JSON
  verify.py      etf-verify  — check a report's table numbers against the saved data
  safe_calc.py   etf-calc    — arithmetic-only calculator for checking a report's math
  pdf.py         etf-pdf     — Markdown report -> PDF via headless Chrome
  sanitize.py    allowlist HTML sanitizer for rendered reports
  paths.py       project directories + the guard that keeps untrusted paths in reports/
  records.py     shared record types
  assets/report.css
tests/           pytest suite (one file per module)
.claude/agents/  the two agents' instructions
run-report.sh    runs both agents; holds their tool permissions
launchd/         the daily 8 AM job
```

## Setup

```sh
git clone <this repo> ~/Dev/etf-analyst
cd ~/Dev/etf-analyst
make venv      # .venv with the package (and its etf-* commands) + dev tools
ln -s ~/Dev/etf-analyst/.claude/agents/etf-analyst.md ~/.claude/agents/etf-analyst.md
ln -s ~/Dev/etf-analyst/.claude/agents/etf-report-verifier.md ~/.claude/agents/etf-report-verifier.md
```

The symlinks make the agents available in every Claude Code session. The agents and `run-report.sh` call the commands in `~/Dev/etf-analyst/.venv/bin/`; if you clone somewhere else, update those paths in `.claude/agents/*.md`, `run-report.sh` and the launchd plist.

## Usage

In Claude Code: *"Run the etf-analyst"*, *"Which ETFs are good for long-term investing right now?"*, or *"Compare VOO, QQQM and SCHD."* To check a report: *"Run the etf-report-verifier on the latest report."*

Run the commands directly (from `.venv/bin/`, or anywhere after `source .venv/bin/activate`):

```sh
etf-screen                       # screen the market, top 15 per horizon
etf-screen --top 25              # longer lists
etf-screen VOO QQQM SCHD         # rank only these tickers
etf-screen --save                # also save full data to reports/data/
etf-pdf reports/etf-report-2026-10-30.md       # Markdown report -> PDF
etf-verify reports/etf-report-2026-10-30.md    # check table numbers against saved data
etf-calc "10000 * 1.1542 ** 10"                # safe arithmetic
```

## Daily run on your Mac

`launchd/com.dsvinod90.etf-analyst.plist` is a macOS launchd job that runs `run-report.sh` every day at 8:00 AM (Mac local time; America/New_York here). The script runs the analyst agent headless with Claude Code, then the verifier agent. It writes both reports to `reports/`, logs to `reports/logs/`, and shows a Mac notification with the confidence score (e.g. "Report ready · Confidence 91/100"). Clicking the notification opens the report. If the Mac is asleep at 8:00 the job runs at the next wake; if it's shut down, that day is skipped.

```sh
# install / enable
cp launchd/com.dsvinod90.etf-analyst.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dsvinod90.etf-analyst.plist

# run on demand
./run-report.sh                                            # in the foreground
launchctl kickstart gui/$(id -u)/com.dsvinod90.etf-analyst # as the background job

# disable
launchctl bootout gui/$(id -u)/com.dsvinod90.etf-analyst
```

## Development

Coding standards and project rules are in [CLAUDE.md](CLAUDE.md). Dev tools are pinned in `requirements-dev.txt`.

```sh
make venv     # create .venv: package (editable) + ruff, mypy, pytest
make format   # format and auto-fix
make check    # lint (ruff + shellcheck), mypy --strict, pytest with coverage
```

CI (`.github/workflows/ci.yml`) runs `make lint`, `make typecheck` and `make test` on every push and pull request. It needs no secrets.

Output is informational analysis, not financial advice.
