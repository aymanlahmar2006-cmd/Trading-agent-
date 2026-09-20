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
from .i18n import resolve, t
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


def _print_failures(failures: list[str], lang: str) -> None:
    if failures:
        print("\n" + t("load_failures", lang))
        for failure in failures:
            print(f"- {failure}")


def cmd_analyze(args: argparse.Namespace) -> int:
    lang = resolve(args.lang)
    config = load_config(Path(args.config))
    analyses, failures, _, _, raw_context = _analyse_all(Path(args.snapshot), config)

    if not analyses and failures:
        print(t("no_symbol_analysed", lang), file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    report_cfg = config.get("report", {})
    print(render_report(analyses, raw_context, lang=lang,
                        max_opportunities=int(report_cfg.get("max_opportunities", 5)),
                        compact_watching=bool(report_cfg.get("compact_watching", True)),
                        full_reasoning_for=int(report_cfg.get("full_reasoning_for", 2)),
                        show_near_misses=bool(report_cfg.get("show_near_misses", True)),
                        max_near_misses=int(report_cfg.get("max_near_misses", 5))))
    _print_failures(failures, lang)

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
    lang = resolve(args.lang)
    config = load_config(Path(args.config))
    alert_cfg = config.get("alerts", {})
    leader = config.get("market_context", {}).get("leader_symbol", "BINANCE:BTCUSDT")

    analyses, failures, prices, collected_at, raw_context = _analyse_all(
        Path(args.snapshot), config)

    if not analyses and failures:
        print(t("no_symbol_analysed", lang), file=sys.stderr)
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

    min_quality = float(alert_cfg.get("min_quality_for_new_setup", 60.0))
    stop_warn = float(alert_cfg.get("stop_warn_pct", 25.0))

    # The console and the phone get different languages: Windows cannot render
    # right-to-left text, Telegram can.
    shown = collect(analyses, book, prices, previous, current,
                    min_quality, stop_warn, lang=lang)

    report_cfg = config.get("report", {})
    print(render_report(analyses, current.to_context(lang), lang=lang,
                        max_opportunities=int(report_cfg.get("max_opportunities", 5)),
                        compact_watching=bool(report_cfg.get("compact_watching", True)),
                        full_reasoning_for=int(report_cfg.get("full_reasoning_for", 2)),
                        show_near_misses=bool(report_cfg.get("show_near_misses", True)),
                        max_near_misses=int(report_cfg.get("max_near_misses", 5))))
    _print_failures(failures, lang)

    print("\n" + t("alerts_header", lang))
    if shown:
        for alert in shown:
            print(f"{alert.icon} {alert.title}\n   {alert.detail}")
    else:
        print(t("no_alerts", lang))

    append_jsonl(analyses, Path("logs/signals.jsonl"))
    append_csv(analyses, Path("logs/signals.csv"))
    rg.save(current)

    if shown and not args.no_notify:
        message_lang = str(alert_cfg.get("language", "ar"))
        to_send = collect(analyses, book, prices, previous, current,
                          min_quality, stop_warn, lang=message_lang)
        delivery = notify(format_alerts(to_send, message_lang),
                          channel=str(alert_cfg.get("channel", "auto")))
        status = "sent" if delivery.ok else "NOT sent"
        print(f"\n[{delivery.channel}] {status}"
              + (f" — {delivery.detail}" if delivery.detail else ""))

    return 0


def cmd_open(args: argparse.Namespace) -> int:
    lang = resolve(args.lang)
    config = load_config(Path(args.config))
    fee = float(config.get("risk", {}).get("fee_pct", 0.1))
    book = pos.load(JOURNAL)

    existing = pos.find_open(book, args.symbol)
    if existing:
        print(t("already_open", lang, sym=args.symbol, id=existing.id),
              file=sys.stderr)
        return 1

    try:
        position = pos.open_position(
            book, symbol=args.symbol, entry=args.entry, size=args.size,
            stop=args.stop, targets=args.target or [], fee_pct=fee,
            note=args.note or "", signal_ref=args.signal_ref or "")
    except pos.JournalError as exc:
        print(t("rejected", lang, err=exc), file=sys.stderr)
        return 1

    pos.save(book, JOURNAL)
    fee = position.cost_basis() - position.entry * position.size
    print(f"{t('recorded', lang)}: {position.id}")
    print(f"   {t('entry', lang)} {fmt_price(position.entry)} × {position.size} | "
          f"{t('stop', lang)} {fmt_price(position.stop)}")
    print(f"   {t('risk_1r', lang, risk=fmt_price(position.total_risk))} | "
          f"{t('entry_fee', lang)} {fmt_price(fee)}")
    for target in position.targets:
        r_value = position.r_at(target)
        line = f"   {t('target', lang)} {fmt_price(target)}"
        if r_value is not None:
            line += f" → {r_value:+.2f}R {t('net', lang)}"
        print(line)
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    lang = resolve(args.lang)
    book = pos.load(JOURNAL)
    position = pos.find_open(book, args.symbol)
    if position is None:
        print(t("no_open_position", lang, sym=args.symbol), file=sys.stderr)
        return 1

    try:
        pos.close_position(position, args.price, note=args.note or "")
    except pos.JournalError as exc:
        print(f"{t('error', lang)}: {exc}", file=sys.stderr)
        return 1

    pos.save(book, JOURNAL)
    r_value = position.r_at(args.price)
    print(f"{t('closed', lang)}: {position.id}")
    print(f"   {t('exit', lang)} {fmt_price(args.price)} | "
          f"{t('result', lang)} {position.pnl_at(args.price):+.2f}"
          + (f" ({r_value:+.2f}R)" if r_value is not None else ""))
    mae, mfe = position.mae_r(), position.mfe_r()
    if mae is not None and mfe is not None:
        print(f"   {t('max_adverse', lang)} {mae:+.2f}R | "
              f"{t('max_favourable', lang)} {mfe:+.2f}R")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    lang = resolve(args.lang)
    book = pos.load(JOURNAL)
    prices: dict[str, float] = {}
    for item in args.price or []:
        if "=" not in item:
            print(t("bad_price_format", lang, item=item), file=sys.stderr)
            return 1
        symbol, value = item.split("=", 1)
        prices[symbol.split(":")[-1]] = float(value)

    open_positions = [p for p in book if p.status == "open"]
    print(t("open_positions", lang))
    if not open_positions:
        print(t("nothing", lang))
    for position in open_positions:
        short = position.symbol.split(":")[-1]
        price = prices.get(short)
        line = (f"- {short} [{position.id}] {t('entry', lang)} "
                f"{fmt_price(position.entry)} × {position.size} | "
                f"{t('stop', lang)} {fmt_price(position.stop)}")
        if price is not None:
            r_value = position.r_at(price)
            line += f" | {t('price_now', lang)} {fmt_price(price)}"
            if r_value is not None:
                line += f" → {r_value:+.2f}R"
        else:
            line += " | " + t("no_live_price", lang)
        print(line)

    print("\n" + t("closed_summary", lang))
    summary = pos.summarise(book)
    if not summary["closed_trades"]:
        print(t("no_closed", lang))
        return 0
    print(f"{t('count', lang)}: {summary['closed_trades']} | "
          f"{t('win_rate', lang)}: {summary['win_rate']}%")
    print(f"{t('expectancy', lang)}: {summary['expectancy_r']}R "
          f"{t('per_trade', lang)} | {t('total', lang)}: {summary['total_r']}R")
    # No losing trade yet means profit factor is undefined, not infinite skill.
    pf = summary["profit_factor"]
    pf_text = pf if pf is not None else t("pf_undefined", lang)
    print(f"Profit factor: {pf_text} | {t('net', lang)}: {summary['total_pnl']}")
    print(f"{t('best', lang)}: {summary['best_r']}R | "
          f"{t('worst', lang)}: {summary['worst_r']}R")
    if summary["expectancy_r"] is not None and summary["expectancy_r"] <= 0:
        print(t("negative_expectancy", lang))
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

    for name, action in sub.choices.items():
        action.add_argument(
            "--lang", choices=["auto", "ar", "en"], default="auto",
            help="Console language. 'auto' uses English on Windows, whose "
                 "console cannot render right-to-left text.")

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
