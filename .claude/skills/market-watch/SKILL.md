---
name: "market-watch"
description: "Runs the recurring crypto watchlist scan: collect, analyse, detect regime change, alert on open positions, and message the user. Use when asked to start watching the market, run a periodic scan, or check what changed since last time."
---

# Market Watch — the recurring loop

One scan, repeated. Each run answers three questions in this order:

1. **Did anything happen to money already at risk?** (stop threatened, target hit)
2. **Did the market regime change?** (BTC trend, breadth, dominance)
3. **Is there a new setup worth the user's attention?**

That order is the whole design. An open position outranks a new idea, always.

## Running one pass

Follow `crypto-spot-agent` to collect the snapshot, then:

```bash
python3 -m crypto_agent watch snapshots/latest.json
```

The engine writes `journal/regime.json`, so the *next* run can tell a change
from a condition that was already true. Do not delete it between runs — without
it every scan reports the regime as new.

## Setting up the schedule

The user's TradingView runs on their own machine, so the loop runs there too.
Two ways, in order of preference:

**1. A Claude Code session with `/loop`** — keeps the MCP connection warm and
lets the agent reason about what it sees:
```
/loop 1h اعمل scan للـ watchlist واتبع skill market-watch
```

**2. A plain cron / Task Scheduler entry** calling `python3 -m crypto_agent watch`
on a snapshot that something else refreshes. Cheaper, but it cannot collect the
snapshot on its own — the MCP tools need a Claude session.

Match the interval to the timeframe. On the default 1h chart a 15-minute loop
mostly re-reads the same unfinished candle: noise, and a good way to get the
alerts muted. **Hourly, a few minutes after the candle closes, is the right
cadence.** On 4h, every four hours.

## Alert discipline

The engine already de-duplicates by firing on *transitions*, not on conditions
that are still true. Protect that:

- Do not lower `alerts.min_quality_for_new_setup` to make the agent chattier.
  A quiet scan is a real result; say "nothing changed" and stop.
- Do not re-send a scan's output manually after the engine reported it sent.
- If `[telegram] NOT sent` appears, the message is still in `journal/outbox.log`.
  Report the failure and its reason — never silently retry in a loop.

## What to say to the user

After a scan, lead with what changed, not with a full report:

- Alerts fired → say what fired and what it means for the position.
- Regime flipped → say the old state, the new state, and what it implies for
  open longs. A flip to risk-off with a long open is the one case worth
  interrupting for even if no stop is near.
- Nothing → "لا جديد" and the one-line regime. Do not pad it.

Never suggest an action the user did not ask for beyond what the engine printed,
and never state or imply that a signal has been validated — see the known
weakness in `crypto-spot-agent`.

## Telegram

Setup is in `docs/TELEGRAM.md`. Credentials live in the environment
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`), never in a file in the repo — this
repo is public.

If they are unset the agent still works: alerts print and append to
`journal/outbox.log`, and the run reports `telegram not configured`. That is a
degraded mode, not a failure — but tell the user, because they asked for
messages and are not getting them.
