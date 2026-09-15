---
name: "crypto-spot-agent"
description: "Collects live crypto spot data from TradingView via MCP and runs it through the local signal engine. Use when asked to analyse a crypto symbol or the watchlist for intraday (15m-1h) spot entries."
---

# Crypto Spot Agent — Collection Protocol

You are the *collection layer*. You pull real numbers out of TradingView via the
MCP tools, write them into a snapshot file, and hand that file to the analysis
engine. **You do not compute entries, stops or targets yourself** — the engine
does, so the arithmetic is reproducible and auditable.

## Hard rules

1. **Never execute a trade.** Not `replay_trade`, not anything else. This project
   is signals only. There is no phase in which you place an order.
2. **Never invent a number.** If a tool errors or returns nothing, put the error
   text in the snapshot's `errors` array and leave the field out. The engine
   reports "unavailable"; that is the correct output, and a plausible-looking
   guess is not.
3. **Spot only.** No futures, no leverage, no shorts. A bearish symbol is a
   symbol you do not trade, not a short.
4. **Say when the connection is the problem.** If the MCP tools are missing or
   CDP on port 9222 is unreachable, say exactly that and stop. Do not fall back
   to remembered prices or web lookups — stale data here produces a real
   financial decision.

## Phase 1 — one symbol

### Step 1: confirm the connection is live
Call `chart_get_state`. It returns the active symbol, timeframe and indicator
entity IDs. If it fails, stop and report the failure verbatim — everything below
depends on it.

Note which studies are actually on the chart. RSI, MACD and EMAs are optional;
the engine degrades and flags them as missing. It is better to add them once via
`chart_manage_indicator` (formal names: `"Relative Strength Index"`,
`"MACD"`, `"Moving Average Exponential"`) than to run blind every pass.

### Step 2: point the chart at the symbol
```
chart_set_symbol    -> e.g. "BINANCE:BTCUSDT"
chart_set_timeframe -> "15"
```
Both come from `config/watchlist.json`. Read that file; do not hardcode symbols.

### Step 3: collect
Run these and keep the raw values:

| Tool | Purpose | Snapshot field |
|---|---|---|
| `quote_get` | live price — **required** | `quote.last` |
| `data_get_study_values` | RSI / MACD / EMA readings | `studies` |
| `data_get_ohlcv` (`summary: true`) | trend + volatility overview | `ohlcv_summary` |
| `data_get_ohlcv` (raw, `bars_to_pull` from config) | candles for ATR and pivots | `bars` |
| `data_get_pine_lines` (with `study_filter`) | drawn support/resistance | `pine_lines` |
| `data_get_pine_labels` (with `study_filter`) | context annotations | `pine_labels` |

**On the raw bar pull:** the skill's context rules prefer `summary: true`, and
that holds for the overview. But ATR and swing pivots cannot be derived from a
summary, and stops anchored on anything else are made up. So pull both: the
summary for context, plus `bars_to_pull` (default 120) raw bars. 120 × 15m ≈ 30
hours — enough for ATR(14) and several confirmed pivots, and well inside the
500-bar cap. Do not raise it without a reason.

Always pass `study_filter` on the pine readers, and never `verbose: true`.

### Step 4: write the snapshot
Write a JSON file matching `crypto_agent/schema.py`:

```json
{
  "symbol": "BINANCE:BTCUSDT",
  "timeframe": "15",
  "collected_at": "<ISO-8601 UTC of the quote_get call>",
  "quote": { "last": 59473.75, "volume": 1842.55, "change_pct": 2.14 },
  "studies": { "RSI": 56.4, "EMA 9": 59504.0, "EMA 21": 59475.3, "MACD": 42.18, "Signal": 31.04 },
  "pine_lines": [60120.0, 58890.0],
  "pine_labels": ["Daily pivot R1"],
  "ohlcv_summary": { "...": "verbatim from data_get_ohlcv" },
  "bars": [{ "time": 1757900000, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100 }],
  "errors": []
}
```

Study keys are passed through as the chart labels them — `schema.py` normalises
them. `quote.last` is the only required field; everything else may be absent.

### Step 5: run the engine
```bash
python3 -m crypto_agent analyze <snapshot.json> --log
```
Show the user its output as-is. Do not re-word the levels, and do not add a
level the engine did not print.

### Step 6: sanity-check before presenting
- Does `quote.last` match the price on the chart right now? If the chart moved
  during collection, say so — a 15m setup goes stale fast.
- Did the engine warn about missing indicators? Offer to add them.
- If it rejected the setup, present the rejection. A rejection is a result, not
  a failure to work around by loosening `config/watchlist.json`.

## Phases 2-4 (not built yet)

Do not improvise these. They are sequenced deliberately:

- **Phase 2 — watchlist loop + market context.** Repeat steps 2-4 per symbol into
  one snapshot array. Market context means: BTC on 4H (`chart_set_timeframe 240`)
  for the leader trend, and `CRYPTOCAP:BTC.D` for dominance. Dominance is a real
  TradingView symbol, but it loads on the *chart*, so reading it means switching
  the chart away from the symbol under analysis and back — collect context first,
  once per pass, before the per-symbol loop. Write it into `market_context`.
- **Phase 3 — ranking.** The engine already computes `quality_score` and sorts by
  it; phase 3 is tuning those weights against logged results, not new plumbing.
- **Phase 4 — review.** `--log` already appends to `logs/signals.{jsonl,csv}`.
  Phase 4 grades those entries against what price actually did.

## What is genuinely not available

- **Funding rates, open interest, order-book depth** — not on a TradingView
  chart. Any "funding-adjacent signal" would be inferred from price alone; the
  engine does not claim one and neither should you.
- **Stock tooling** (`vcp-screener`, `CANSLIM`, `market-breadth-analyzer`) — built
  on US equity fundamentals and equity breadth feeds. They do not apply to crypto
  and are not used here.
