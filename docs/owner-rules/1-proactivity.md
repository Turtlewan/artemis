# Owner Rules — 1. Proactivity & Notifications

_Feeds: M6-a (hook contract) · M6-b (HIT batching + briefing) · M6-c (ntfy delivery policy) · plus
the **consolidated hook schedule** from every module. This is the "**when / whether Artemis
interrupts me**" surface — the single most owner-personal control._

Status: ⬜ not started

## On the Mini
These become `ProactivePolicy` (designed as an owner-editable `policy.json`), each module's
`HookSpec` schedule params, and the M6-b briefing/scoring prompt.

## Tunable rules
| Rule | Default | Lands in | Your value |
|------|---------|----------|------------|
| ⭐ Quiet-hours window | `22:00 → 07:00` | M6-c `QuietHours.start/end` | **`23:30 → 07:15`** (proposed from rhythm; high-urgency still breaks through). Rhythm drifts day-to-day — treat as soft anchor. |
| What's held during quiet hours | `deferrable, digest` (high still breaks through) | M6-c `QuietHours.hold_dispositions` | |
| ⭐ Global "what surfaces" urgency floor | `low` (→ noisy out of the box) | M6-c `ProactivePolicy.min_urgency_global` | **Posture: gentle nudges.** Scheduled digests welcome; outside them, important-only (email already important-only via S3 rubric). Keep `low` for now; tune up on-Mini if it feels chatty. |
| ⭐ Per-module noisiness floor | `{}` (none) | M6-c `ProactivePolicy.module_min_urgency` | none for now; revisit on-Mini against real volume |
| Global mute | `false` | M6-c `ProactivePolicy.muted` | |
| Held-message stale TTL | `8h` | M6-c `ProactivePolicy.held_ttl_hours` | |
| Tier-1 drain retry cap (→ dead-letter) | `5` | M6-c `ProactivePolicy.max_drain_attempts` | |
| Tick granularity | `60s` | M6-a `run_forever(sleep_seconds)` | |

## ⭐ Hook schedule — the master "when does Artemis act" list
_All proactive hooks across all modules. Fill the time/cadence you actually want._
| Hook | Module | Default schedule | Urgency | Your value |
|------|--------|------------------|---------|------------|
| Daily briefing | M6-b | `07:30` daily | normal | **ON** — ⚠️ overlaps morning plan (see flag) |
| Gmail urgency scan | M8-b2 | every `5 min`, notify once/day | high | **ON** — notify gated by S3 rubric (legal/payment only) |
| Morning plan | M8-d-c1 | `08:00` daily | normal | **ON** — ⚠️ overlaps daily briefing (see flag) |
| Overdue-task nudge | M8-d-c1 | hourly | normal | **ON but reduce cadence** — hourly too naggy for "gentle"; propose 1–2×/day |
| Weekly review | M8-d-c1 | weekly (+ which day?) | low | **ON** — pick day/time (Sun evening?) → |
| Calendar upcoming reminder | CAL-c | `15 min` before, polled 5 min | — | **ON** |
| Calendar prep nudge | CAL-c | `18h` lookahead, hourly | — | **ON** |
| Calendar free-gap focus-protect | CAL-c | min gap `30 min`, hourly, 1/day | — | **ON** |
| Calendar conflict alert | CAL-c | next 24h, every 30 min | — | **ON** |
| Calendar unanswered-invite nudge | CAL-c | hourly | — | **ON** |

_Which modules feed the daily briefing? (default: all summarisers injected.)_ →

**⚠️ Two tuning flags:**
1. **Briefing (07:30) + Morning plan (08:00) overlap** — two pings ~30 min apart at wake. Options:
   merge into one morning digest, OR space them (briefing 07:30 = overnight/world; morning plan
   08:30 = today's tasks/calendar). → decide on-Mini or now.
2. **Overdue nudge hourly is too frequent for "gentle"** — propose once or twice daily (e.g. folded
   into morning plan + one mid-afternoon check) instead of every hour.

## Prompt text (your voice)
**HIT batched-scoring prompt** (M6-b) — how Artemis writes each owner-facing alert line. Default is
generic ("one short owner-facing line per item"). Your preferred tone/format:
```
(leave blank to accept default)
```
**Per-hook notification templates** (M6-b, no-LLM path) — default is `"{hook}: update"`. Any hooks
you want worded specifically:
```
```

## 🔒 Frozen invariants (not owner-tunable)
- Urgency→ntfy priority/tag mapping *structure* (high→high+warning, normal→default, low→low).
- ntfy action-URL allow-list (`artemis://`, `https://127.0.0.1`, Tailscale host) — security.
- Dedup-store 7-day TTL; atomic-write / corrupt-recovery; tier-1 sink / `on_hits` / `pre_tick_steps` seams.
- `OWNER_PRIVATE ⇒ tier==1` validator (private hooks never fire while locked).
