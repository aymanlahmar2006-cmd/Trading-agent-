"""Command line entry point.

    python -m crypto_agent analyze snapshot.json

The snapshot is produced by the collection layer (Claude driving the TradingView
MCP tools -- see .claude/skills/crypto-spot-agent/SKILL.md). Keeping collection
and analysis in separate steps means the numbers in the report can always be
checked against the snapshot that produced them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .journal import append_csv, append_jsonl
from .report import render_report
from .schema import SnapshotError, parse_snapshot
from .signal import analyse

DEFAULT_CONFIG = Path("config/watchlist.json")


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_snapshots(path: Path) -> list[dict]:
    """Accept either a single snapshot object or a list of them."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "snapshots" in payload:
        return payload["snapshots"]
    return [payload]


def cmd_analyze(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        raise SystemExit(f"Snapshot not found: {snapshot_path}")

    raw_snapshots = load_snapshots(snapshot_path)
    analyses = []
    failures = []
    market_context: dict = {}

    for raw in raw_snapshots:
        try:
            snapshot = parse_snapshot(raw)
        except SnapshotError as exc:
            # A bad snapshot is reported, never silently skipped -- a missing
            # symbol in the report would read as "no setup" instead of "no data".
            failures.append(str(exc))
            continue
        if snapshot.market_context and not market_context:
            market_context = snapshot.market_context
        analyses.append(analyse(snapshot, config))

    if not analyses and failures:
        print("لم يتم تحليل أي رمز. أخطاء البيانات:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(render_report(analyses, market_context))

    if failures:
        print("\n=== رموز فشل تحميلها ===")
        for failure in failures:
            print(f"- {failure}")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps([a.to_dict() for a in analyses], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[saved] {out}")

    if args.log:
        append_jsonl(analyses, Path("logs/signals.jsonl"))
        append_csv(analyses, Path("logs/signals.csv"))
        print("[logged] logs/signals.jsonl, logs/signals.csv")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="crypto_agent",
        description="Crypto spot signal engine -- analysis only, never executes trades.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze a snapshot JSON file")
    analyze.add_argument("snapshot", help="Path to the snapshot JSON")
    analyze.add_argument("--config", default=str(DEFAULT_CONFIG))
    analyze.add_argument("--json-out", help="Also write structured results here")
    analyze.add_argument("--log", action="store_true",
                         help="Append results to logs/signals.{jsonl,csv}")
    analyze.set_defaults(func=cmd_analyze)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
