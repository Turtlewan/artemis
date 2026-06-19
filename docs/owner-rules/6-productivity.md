# Owner Rules — 6. Productivity (Tasks / Projects / Areas)

_Feeds: M8-d-a (core) · M8-d-b (time-blocking) · M8-d-c1 (hooks) · M8-d-c2 (capture). Hook *timings*
→ `1-proactivity.md`; focus-block/scheduling-window → `2-scheduling.md`; graduation threshold →
`5-safety-policy.md`. This file holds the productivity-specific rules not homed elsewhere._

Status: ⬜ not started

## On the Mini
Consts/enums in the productivity module + the commitment-detection LLM prompt/schema (M8-d-c2).

## Tunable rules
| Rule | Default | Lands in | Your value |
|------|---------|----------|------------|
| ⭐ Fixed-recurrence grammar | `every N days/weeks/months`, `every <weekday>`, `monthly on N` | M8-d-a recurrence parser | |
| ⭐ Recurrence drift policy | calendar rules snap to next boundary; interval rules advance from `due_at` (late completion doesn't drift) | M8-d-a recurrence engine | |
| Completion-based recurrence | `N days/weeks after completion` (from `completed_at`) | M8-d-a recurrence engine | |
| Task priority vocabulary | `none / low / medium / high` | M8-d-a `TaskPriority` | |
| "Upcoming tasks" window | `7 days` | M8-d-a `upcoming_tasks(days=7)` | |
| ⭐ Commitment-shape vocabulary | `will_send / call / meet / pay / review / schedule / complete / other` | M8-d-c2 `COMMITMENT_SCHEMA` | |

## Prompt text (your voice)
**Commitment-detection prompt** (M8-d-c2) — what counts as a task-commitment Artemis should capture
from your email/conversation. Default: "Extract task commitments… respond in JSON." Your wording:
```
```

## Cross-referenced (captured elsewhere)
- Morning-plan `08:00` / overdue hourly / weekly-review cadence → `1-proactivity.md` §Hook schedule.
- Focus-block duration `90m`, default scheduling window `7d` → `2-scheduling.md`.
- Capture→recipe graduation threshold `N≥2` → `5-safety-policy.md` (same `Promoter.threshold`).

## 🔒 Frozen invariants (not owner-tunable)
- Suggestions inert until accepted (`status='pending'`); email capture quarantine-first
  (`raw_context=None`); capture recipes are `TOUCHES_DATA` → gated → never auto-enabled.
- Morning/weekly LLM hook payloads are **counts + IDs only** (no task titles forwarded) — injection boundary.
- Month-overflow clamp (Jan 31 → Feb 28/29); search result cap (50).
