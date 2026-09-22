"""Answer "is the engine too strict?" from logged scans instead of opinion.

Every scan appends its analyses to logs/signals.jsonl and archives the raw
snapshot. That is enough to ask two questions that matter more than any
argument about the filters:

  1. Which gate is actually doing the rejecting?
  2. Would the symbols it rejected have made money?

The second one is the real test. A filter that rejects a symbol which then
falls has earned its keep. One that rejects a symbol which then rallies is
costing money, however sound its reasoning sounds.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG = Path("logs/signals.jsonl")
SNAPSHOTS = Path("snapshots")


def load_log(path: Path = LOG) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def rejection_counts(records: list[dict[str, Any]]) -> Counter:
    return Counter(r.get("rejected_kind") or ("actionable" if r.get("actionable")
                                              else "other")
                   for r in records)


def price_history(records: list[dict[str, Any]]) -> dict[str, list[tuple[str, float]]]:
    """Every price the log ever saw, per symbol, in time order."""
    history: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for record in records:
        when = record.get("collected_at") or ""
        price = record.get("price")
        symbol = record.get("symbol")
        if symbol and isinstance(price, (int, float)):
            history[symbol].append((when, float(price)))
    for symbol in history:
        history[symbol].sort(key=lambda pair: pair[0])
    return history


@dataclass
class Outcome:
    kind: str
    count: int
    measured: int
    mean_move_pct: float
    up: int
    down: int

    @property
    def verdict(self) -> str:
        """What the later price says about this gate."""
        if self.measured < 5:
            return "not enough data"
        if self.mean_move_pct > 0.5:
            return "rejections rose -- this gate is costing money"
        if self.mean_move_pct < -0.5:
            return "rejections fell -- this gate is saving money"
        return "no clear effect"


def what_happened_next(records: list[dict[str, Any]],
                       horizon: int = 4) -> list[Outcome]:
    """For each rejection kind, how price moved ``horizon`` scans later.

    Uses only prices the log already contains, so it needs several scans before
    it says anything. It reports how many it could measure rather than filling
    the gap with an assumption.
    """
    history = price_history(records)
    index: dict[tuple[str, str], int] = {}
    for symbol, points in history.items():
        for position, (when, _) in enumerate(points):
            index[(symbol, when)] = position

    moves: dict[str, list[float]] = defaultdict(list)
    totals: Counter = Counter()

    for record in records:
        kind = record.get("rejected_kind") or ("actionable" if record.get("actionable")
                                               else "other")
        totals[kind] += 1
        symbol = record.get("symbol")
        when = record.get("collected_at") or ""
        position = index.get((symbol, when))
        if position is None:
            continue
        points = history[symbol]
        later = position + horizon
        if later >= len(points):
            continue
        start, end = points[position][1], points[later][1]
        if start > 0:
            moves[kind].append((end - start) / start * 100.0)

    outcomes = []
    for kind, count in totals.most_common():
        values = moves.get(kind, [])
        outcomes.append(Outcome(
            kind=kind,
            count=count,
            measured=len(values),
            mean_move_pct=round(sum(values) / len(values), 3) if values else 0.0,
            up=sum(1 for v in values if v > 0),
            down=sum(1 for v in values if v <= 0),
        ))
    return outcomes


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    scans = sorted({r.get("collected_at", "") for r in records if r.get("collected_at")})
    return {
        "evaluations": len(records),
        "scans": len(scans),
        "first_scan": scans[0] if scans else None,
        "last_scan": scans[-1] if scans else None,
        "symbols": len({r.get("symbol") for r in records}),
        "actionable": sum(1 for r in records if r.get("actionable")),
    }


def archived_snapshots(path: Path = SNAPSHOTS) -> list[Path]:
    return sorted(path.glob("*.json")) if path.exists() else []
