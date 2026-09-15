"""Trade journal for positions the user actually took.

This is the only part of the project that touches real money, so the arithmetic
is deliberately explicit: fees are charged on both sides, R is measured against
the risk that was on the table at entry, and nothing is inferred from a signal.
A position exists here because the user says they filled it, not because the
engine suggested it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_JOURNAL = Path("journal/positions.json")


class JournalError(ValueError):
    """Raised when a position is malformed or an operation is not valid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Position:
    """One spot long the user opened. Spot has no shorts, so side is implicit."""

    id: str
    symbol: str
    entry: float
    size: float
    stop: float
    targets: list[float] = field(default_factory=list)
    opened_at: str = ""
    closed_at: str | None = None
    exit: float | None = None
    status: str = "open"
    fee_pct: float = 0.1
    note: str = ""
    signal_ref: str = ""
    # Worst and best price seen while the position was open, in price terms.
    worst_price: float | None = None
    best_price: float | None = None

    @property
    def risk_per_unit(self) -> float:
        return self.entry - self.stop

    @property
    def total_risk(self) -> float:
        """The money that was genuinely at risk at entry -- the R unit."""
        return self.risk_per_unit * self.size

    def cost_basis(self) -> float:
        """What entering cost, including the buy-side fee."""
        return self.entry * self.size * (1 + self.fee_pct / 100.0)

    def proceeds(self, price: float) -> float:
        """What exiting at ``price`` returns, after the sell-side fee."""
        return price * self.size * (1 - self.fee_pct / 100.0)

    def pnl_at(self, price: float) -> float:
        """Net profit or loss in quote currency, both fees paid."""
        return self.proceeds(price) - self.cost_basis()

    def r_at(self, price: float) -> float | None:
        """P&L in R. None when the stop was at or above entry, so R is undefined."""
        if self.total_risk <= 0:
            return None
        return self.pnl_at(price) / self.total_risk

    def mae_r(self) -> float | None:
        """Maximum adverse excursion in R -- how far underwater it went."""
        if self.worst_price is None:
            return None
        return self.r_at(self.worst_price)

    def mfe_r(self) -> float | None:
        """Maximum favourable excursion in R -- how far it ran before the exit."""
        if self.best_price is None:
            return None
        return self.r_at(self.best_price)

    def stop_distance_pct(self, price: float) -> float | None:
        """How close price is to the stop, as a share of the original risk.

        0% means the stop is being touched; 100% means price is at entry.
        """
        if self.risk_per_unit <= 0:
            return None
        return (price - self.stop) / self.risk_per_unit * 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate(position: Position) -> None:
    if position.size <= 0:
        raise JournalError(f"{position.symbol}: size must be positive")
    if position.entry <= 0:
        raise JournalError(f"{position.symbol}: entry must be positive")
    if position.stop >= position.entry:
        raise JournalError(
            f"{position.symbol}: stop {position.stop} is at or above entry "
            f"{position.entry}. On a spot long the stop sits below entry -- "
            "with it above, there is no defined risk and R is meaningless."
        )
    for target in position.targets:
        if target <= position.entry:
            raise JournalError(
                f"{position.symbol}: target {target} is at or below entry "
                f"{position.entry}; a long does not profit there."
            )


def load(path: Path = DEFAULT_JOURNAL) -> list[Position]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    positions = []
    for raw in payload:
        known = {k: v for k, v in raw.items() if k in Position.__dataclass_fields__}
        positions.append(Position(**known))
    return positions


def save(positions: list[Position], path: Path = DEFAULT_JOURNAL) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([p.to_dict() for p in positions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def next_id(positions: list[Position], symbol: str) -> str:
    short = symbol.split(":")[-1]
    day = utc_now()[:10]
    same_day = [p for p in positions if p.id.startswith(f"{day}-{short}")]
    return f"{day}-{short}-{len(same_day) + 1}"


def open_position(positions: list[Position], symbol: str, entry: float, size: float,
                  stop: float, targets: list[float] | None = None,
                  fee_pct: float = 0.1, note: str = "",
                  signal_ref: str = "") -> Position:
    position = Position(
        id=next_id(positions, symbol),
        symbol=symbol,
        entry=entry,
        size=size,
        stop=stop,
        targets=sorted(targets or []),
        opened_at=utc_now(),
        fee_pct=fee_pct,
        note=note,
        signal_ref=signal_ref,
        worst_price=entry,
        best_price=entry,
    )
    _validate(position)
    positions.append(position)
    return position


def find_open(positions: list[Position], symbol: str) -> Position | None:
    short = symbol.split(":")[-1]
    for position in positions:
        if position.status == "open" and position.symbol.split(":")[-1] == short:
            return position
    return None


def mark(position: Position, price: float) -> None:
    """Record a live price against an open position, updating MAE/MFE."""
    if position.status != "open":
        return
    position.worst_price = price if position.worst_price is None \
        else min(position.worst_price, price)
    position.best_price = price if position.best_price is None \
        else max(position.best_price, price)


def close_position(position: Position, price: float, note: str = "") -> Position:
    if position.status != "open":
        raise JournalError(f"{position.id} is already closed")
    mark(position, price)
    position.exit = price
    position.closed_at = utc_now()
    position.status = "closed"
    if note:
        position.note = f"{position.note} | {note}".strip(" |")
    return position


def summarise(positions: list[Position]) -> dict[str, Any]:
    """Aggregate closed trades. Expectancy here is realised, not simulated."""
    closed = [p for p in positions if p.status == "closed" and p.exit is not None]
    r_values = [p.r_at(p.exit) for p in closed]
    r_values = [r for r in r_values if r is not None]

    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "closed_trades": len(closed),
        "open_trades": sum(1 for p in positions if p.status == "open"),
        "win_rate": round(len(wins) / len(r_values) * 100, 1) if r_values else None,
        "expectancy_r": round(sum(r_values) / len(r_values), 4) if r_values else None,
        "total_r": round(sum(r_values), 3) if r_values else None,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "total_pnl": round(sum(p.pnl_at(p.exit) for p in closed), 2) if closed else None,
        "best_r": round(max(r_values), 3) if r_values else None,
        "worst_r": round(min(r_values), 3) if r_values else None,
    }
