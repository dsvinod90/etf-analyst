"""Screen US ETFs, score them for long- and short-term investing, and publish verified reports.

Modules:
    metrics    Pure price-series math (percent change, RSI, volatility, drawdown, CAGR).
    yahoo      Yahoo Finance client: screen for ETFs and compute one fund's metrics.
    scoring    Standardize, weight and rank funds for each horizon.
    screen     ``etf-screen`` CLI: run the screen and print JSON.
    verify     ``etf-verify`` CLI: check a report's table numbers against the saved data.
    safe_calc  ``etf-calc`` CLI: arithmetic-only calculator for checking a report's math.
    sanitize   Allowlist HTML sanitizer for rendered reports.
    pdf        ``etf-pdf`` CLI: Markdown report -> PDF via headless Chrome.
    paths      Project directories and the guard that confines untrusted paths to them.
    records    Shared record types.
"""

__version__ = "0.2.0"
