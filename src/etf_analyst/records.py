"""Shared record types."""

from typing import Any

ETF = dict[
    str, Any
]  # one fund's record, as built by yahoo.analyze() and extended by scoring.score()
