"""Shared price formatting.

Lives on its own so both the signal engine and the renderer can use it without
the engine importing the renderer. Crypto spans six orders of magnitude on one
watchlist -- a fixed precision prints a sub-cent altcoin as "0.0000".
"""

from __future__ import annotations


def fmt_price(value: float | None) -> str:
    if value is None:
        return "—"
    magnitude = abs(value)
    if magnitude >= 1000:
        return f"{value:,.2f}"
    if magnitude >= 10:
        return f"{value:,.3f}"
    if magnitude >= 1:
        return f"{value:,.4f}"
    if magnitude >= 0.01:
        return f"{value:,.6f}"
    return f"{value:,.8f}"
