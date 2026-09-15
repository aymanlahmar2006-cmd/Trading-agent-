"""Append analyses to a local journal so signals can be graded later."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .signal import SymbolAnalysis

CSV_COLUMNS = [
    "collected_at", "symbol", "timeframe", "price", "trend", "trend_strength",
    "actionable", "confidence", "quality_score", "entry_low", "entry_high",
    "stop", "target", "risk_reward", "atr", "rejected_reason",
]


def append_jsonl(analyses: list[SymbolAnalysis], path: Path) -> None:
    """Full fidelity record -- every vote and warning is kept for review."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for analysis in analyses:
            handle.write(json.dumps(analysis.to_dict(), ensure_ascii=False) + "\n")


def append_csv(analyses: list[SymbolAnalysis], path: Path) -> None:
    """Flat record for spreadsheets. Header is written only on creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        if is_new:
            writer.writeheader()
        for analysis in analyses:
            plan = analysis.plan
            writer.writerow({
                "collected_at": analysis.collected_at,
                "symbol": analysis.symbol,
                "timeframe": analysis.timeframe,
                "price": analysis.price,
                "trend": analysis.trend,
                "trend_strength": analysis.trend_strength,
                "actionable": analysis.actionable,
                "confidence": analysis.confidence,
                "quality_score": analysis.quality_score,
                "entry_low": plan.entry_low if plan else "",
                "entry_high": plan.entry_high if plan else "",
                "stop": plan.stop if plan else "",
                "target": plan.target if plan else "",
                "risk_reward": round(plan.risk_reward, 3) if plan else "",
                "atr": analysis.atr if analysis.atr is not None else "",
                "rejected_reason": analysis.rejected_reason or "",
            })
