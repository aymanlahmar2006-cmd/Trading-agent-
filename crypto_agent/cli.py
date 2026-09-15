"""Command line entry point.

    python -m crypto_agent watch   snapshot.json      # scan, alert, notify
    python -m crypto_agent analyze snapshot.json      # report only
    python -m crypto_agent open    --symbol ... --entry ... --size ... --stop ...
    python -m crypto_agent close   --symbol ... --price ...
    python -m crypto_agent status  --price BTCUSDT=64000

Snapshots are produced by the collection layer (Claude driving the TradingView
MCP tools -- see .claude/skills/). Keeping collection and analysis in separate
steps means the numbers in a report can always be checked against the snapshot
that produced them.

No command in this file places, modifies or cancels an order. The journal
records fills the user reports; it never creates one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import positions as pos
from . import regime as rg
from .alerts import collect
from .formatting import fmt_price
from .journal import append_csv, append_jsonl
from .notify import format_alerts, notify
from .report import render_report
from .schema import SnapshotError, parse_snapshot
from .signal import analyse

DEFAULT_CONFIG = Path("config/watchlist.json")
JOURNAL = Path("journal/positions.json")


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


def _analyse_all(snapshot_path: Path, config: dict):
    """Returns (analyses, failures, prices, collected_at, raw_context)."""
    if not snapshot_path.exists():
        raise SystemExit(f"Snapshot not found: {snapshot_path}")

    analyses, failures, prices = [], [], {}
    collected_at, raw_context = "", {}

    for raw in load_snapshots(snapshot_path):
        try:
            snapshot = parse_snapshot(raw)
        except SnapshotError as exc:
            # Reported, never silently skipped -- a missing symbol would read as
            # "no setup" instead of "no data".
            failures.append(str(exc))
            continue
        prices[snapshot.symbol] = snapshot.quote.last
        prices[snapshot.symbol.split(":")[-1]] = snapshot.quote.last
        collected_at = collected_at or snapshot.collected_at
        if snapshot.market_context and not raw_context:
            raw_context = snapshot.market_context
        analyses.append(analyse(snapshot, config))

    return analyses, failures, prices, collected_at, raw_context


def _print_failures(failures: list[str]) -> None:
    if failures:
        print("\n=== رموز فشل تحميلها ===")
        for failure in failures:
            print(f"- {failure}")


def cmd_analyze(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    analyses, failures, _, _, raw_context = _analyse_all(Path(args.snapshot), config)

    if not analyses and failures:
        print("لم يتم تحليل أي رمز. أخطاء البيانات:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(render_report(analyses, raw_context))
    _print_failures(failures)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps([a.to_dict() for a in analyses], ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"\n[saved] {out}")

    if args.log:
        append_jsonl(analyses, Path("logs/signals.jsonl"))
        append_csv(analyses, Path("logs/signals.csv"))
        print("[logged] logs/signals.jsonl, logs/signals.csv")

    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """One full scan: analyse, assess the market, mark positions, alert."""
    config = load_config(Path(args.config))
    alert_cfg = config.get("alerts", {})
    leader = config.get("market_context", {}).get("leader_symbol", "BINANCE:BTCUSDT")

    analyses, failures, prices, collected_at, raw_context = _analyse_all(
        Path(args.snapshot), config)

    if not analyses and failures:
        print("لم يتم تحليل أي رمز. أخطاء البيانات:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    btc = next((a for a in analyses
                if a.symbol.split(":")[-1] == leader.split(":")[-1]), None)
    others = [a for a in analyses if a is not btc]
    current = rg.assess(btc, others,
                        dominance_note=str(raw_context.get("dominance_note", "")),
                        assessed_at=collected_at)
    previous = rg.load_previous()

    # Mark open positions against the prices this scan collected.
    book = pos.load(JOURNAL)
    for position in book:
        price = prices.get(position.symbol, prices.get(position.symbol.split(":")[-1]))
        if price is not None:
            pos.mark(position, price)
    if book:
        pos.save(book, JOURNAL)

    alerts = collect(analyses, book, prices, previous, current,
                     min_quality=float(alert_cfg.get("min_quality_for_new_setup", 60.0)))

    print(render_report(analyses, current.to_context()))
    _print_failures(failures)

    if alerts:
        print("\n=== تنبيهات ===")
        for alert in alerts:
            print(f"{alert.icon} {alert.title}\n   {alert.detail}")
    else:
        print("\n=== تنبيهات ===\nلا جديد يستدعي التنبيه.")

    append_jsonl(analyses, Path("logs/signals.jsonl"))
    append_csv(analyses, Path("logs/signals.csv"))
    rg.save(current)

    if alerts and not args.no_notify:
        delivery = notify(format_alerts(alerts),
                          channel=str(alert_cfg.get("channel", "auto")))
        status = "sent" if delivery.ok else "NOT sent"
        print(f"\n[{delivery.channel}] {status}"
              + (f" — {delivery.detail}" if delivery.detail else ""))

    return 0


def cmd_open(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    fee = float(config.get("risk", {}).get("fee_pct", 0.1))
    book = pos.load(JOURNAL)

    existing = pos.find_open(book, args.symbol)
    if existing:
        print(f"في صفقة مفتوحة بالفعل على {args.symbol} ({existing.id}). "
              "اقفلها الأول أو استخدم رمز مختلف.", file=sys.stderr)
        return 1

    try:
        position = pos.open_position(
            book, symbol=args.symbol, entry=args.entry, size=args.size,
            stop=args.stop, targets=args.target or [], fee_pct=fee,
            note=args.note or "", signal_ref=args.signal_ref or "")
    except pos.JournalError as exc:
        print(f"الصفقة مترفضة: {exc}", file=sys.stderr)
        return 1

    pos.save(book, JOURNAL)
    risk = position.total_risk
    print(f"✅ اتسجلت: {position.id}")
    print(f"   دخول {fmt_price(position.entry)} × {position.size} | "
          f"ستوب {fmt_price(position.stop)}")
    print(f"   المخاطرة {fmt_price(risk)} (= 1R) | رسوم الدخول "
          f"{fmt_price(position.cost_basis() - position.entry * position.size)}")
    if position.targets:
        for target in position.targets:
            r = position.r_at(target)
            print(f"   هدف {fmt_price(target)} → {r:+.2f}R صافي" if r is not None
                  else f"   هدف {fmt_price(target)}")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    book = pos.load(JOURNAL)
    position = pos.find_open(book, args.symbol)
    if position is None:
        print(f"مفيش صفقة مفتوحة على {args.symbol}.", file=sys.stderr)
        return 1

    try:
        pos.close_position(position, args.price, note=args.note or "")
    except pos.JournalError as exc:
        print(f"خطأ: {exc}", file=sys.stderr)
        return 1

    pos.save(book, JOURNAL)
    r = position.r_at(args.price)
    pnl = position.pnl_at(args.price)
    print(f"✅ اتقفلت: {position.id}")
    print(f"   خروج {fmt_price(args.price)} | النتيجة {pnl:+.2f} "
          + (f"({r:+.2f}R)" if r is not None else ""))
    mae, mfe = position.mae_r(), position.mfe_r()
    if mae is not None and mfe is not None:
        print(f"   أقصى تراجع {mae:+.2f}R | أقصى ربح غير محقق {mfe:+.2f}R")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    book = pos.load(JOURNAL)
    prices: dict[str, float] = {}
    for item in args.price or []:
        if "=" not in item:
            print(f"صيغة غلط: {item} — المفروض SYMBOL=PRICE", file=sys.stderr)
            return 1
        symbol, value = item.split("=", 1)
        prices[symbol.split(":")[-1]] = float(value)

    open_positions = [p for p in book if p.status == "open"]
    print("=== صفقات مفتوحة ===")
    if not open_positions:
        print("لا شيء.")
    for position in open_positions:
        short = position.symbol.split(":")[-1]
        price = prices.get(short)
        line = (f"- {short} [{position.id}] دخول {fmt_price(position.entry)} × "
                f"{position.size} | ستوب {fmt_price(position.stop)}")
        if price is not None:
            r = position.r_at(price)
            line += f" | السعر {fmt_price(price)}"
            if r is not None:
                line += f" → {r:+.2f}R"
        else:
            line += " | (مفيش سعر لحظي — مرر --price)"
        print(line)

    print("\n=== ملخص الصفقات المقفولة ===")
    summary = pos.summarise(book)
    if not summary["closed_trades"]:
        print("لسه مفيش صفقات مقفولة.")
        return 0
    print(f"العدد: {summary['closed_trades']} | نسبة الربح: {summary['win_rate']}%")
    print(f"التوقع: {summary['expectancy_r']}R لكل صفقة | الإجمالي: {summary['total_r']}R")
    # No losing trade yet means profit factor is undefined, not infinite skill.
    pf = summary["profit_factor"]
    pf_text = pf if pf is not None else "غير محسوب (مفيش صفقة خاسرة لسه)"
    print(f"Profit factor: {pf_text} | صافي: {summary['total_pnl']}")
    print(f"أفضل: {summary['best_r']}R | أسوأ: {summary['worst_r']}R")
    if summary["expectancy_r"] is not None and summary["expectancy_r"] <= 0:
        print("\n⚠ التوقع سالب — الإشارات دي مش رابحة على بياناتك الفعلية حتى الآن.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="crypto_agent",
        description="Crypto spot agent -- analysis and journalling only, never executes trades.")
    sub = parser.add_subparsers(dest="command", required=True)

    common = {"default": str(DEFAULT_CONFIG)}

    analyze = sub.add_parser("analyze", help="Analyze a snapshot and print the report")
    analyze.add_argument("snapshot")
    analyze.add_argument("--config", **common)
    analyze.add_argument("--json-out")
    analyze.add_argument("--log", action="store_true")
    analyze.set_defaults(func=cmd_analyze)

    watch = sub.add_parser("watch", help="Full scan: report, market regime, alerts, notify")
    watch.add_argument("snapshot")
    watch.add_argument("--config", **common)
    watch.add_argument("--no-notify", action="store_true",
                       help="Print alerts without sending them")
    watch.set_defaults(func=cmd_watch)

    opener = sub.add_parser("open", help="Record a fill you actually took")
    opener.add_argument("--symbol", required=True)
    opener.add_argument("--entry", type=float, required=True)
    opener.add_argument("--size", type=float, required=True)
    opener.add_argument("--stop", type=float, required=True)
    opener.add_argument("--target", type=float, action="append")
    opener.add_argument("--note")
    opener.add_argument("--signal-ref")
    opener.add_argument("--config", **common)
    opener.set_defaults(func=cmd_open)

    closer = sub.add_parser("close", help="Record an exit")
    closer.add_argument("--symbol", required=True)
    closer.add_argument("--price", type=float, required=True)
    closer.add_argument("--note")
    closer.set_defaults(func=cmd_close)

    status = sub.add_parser("status", help="Open positions and realised performance")
    status.add_argument("--price", action="append",
                        help="SYMBOL=PRICE, repeatable")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
