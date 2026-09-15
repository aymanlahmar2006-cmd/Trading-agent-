"""Deterministic bar builders so tests assert on real numbers, not random ones."""

from __future__ import annotations


def bars_from_path(turns: list[float], steps: int = 6, wick: float = 0.3,
                   start_time: int = 1_757_900_000, interval: int = 900
                   ) -> list[dict]:
    """Interpolate a zigzag through ``turns`` into OHLCV bars.

    Each leg is split into ``steps`` bars, so pivot highs and lows land on real
    turning points and ``find_pivots`` has clean fractals to confirm.
    """
    closes: list[float] = [turns[0]]
    for a, b in zip(turns, turns[1:]):
        for i in range(1, steps + 1):
            closes.append(a + (b - a) * i / steps)

    bars = []
    t = start_time
    for i, close in enumerate(closes):
        prev = closes[i - 1] if i else close
        high = max(prev, close) + wick
        low = min(prev, close) - wick
        bars.append({
            "time": t, "open": round(prev, 6), "high": round(high, 6),
            "low": round(low, 6), "close": round(close, 6), "volume": 100.0,
        })
        t += interval
    return bars


def make_snapshot(bars: list[dict], last: float, studies: dict | None = None,
                  pine_lines: list[float] | None = None,
                  symbol: str = "BINANCE:TESTUSDT") -> dict:
    return {
        "symbol": symbol,
        "timeframe": "15",
        "collected_at": "2026-09-15T12:00:00Z",
        "quote": {"last": last},
        "studies": studies or {},
        "pine_lines": pine_lines or [],
        "bars": bars,
    }


CONFIG = {
    "risk": {
        "min_risk_reward": 1.5,
        "atr_period": 14,
        "atr_stop_multiple": 1.5,
        "max_entry_distance_atr": 1.0,
        "min_stop_distance_atr": 0.6,
        "pivot_lookback": 3,
        "fee_pct": 0.1,
        "slippage_pct": 0.03,
        "max_cost_in_r": 0.25,
    },
    "filters": {"min_confidence_to_report": "medium", "long_only": True},
}
