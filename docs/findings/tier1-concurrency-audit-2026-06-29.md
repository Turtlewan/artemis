# Tier-1 Concurrency / Auth Audit — 2026-06-29

_Review-ensemble audit of the always-on background + auth surface flagged P0 in
`~/.claude/skills/apex-code/REVIEW-ENSEMBLE-DESIGN.md`. Method: 2 Codex `gpt-5.5` read-only
lenses (concurrency + security, off-Max) + Opus Tier-2 adjudication against the verified
deployment model. Raw lens outputs: scratchpad `review-concurrency.json` / `review-security.json`._

## Verdict (headline)

**None of the four Tier-1 backlog items is an active race under the current deployment.** All are
**latent / defensive-only** — they fire only if the load-bearing single-worker assumption is broken.
The audit's real product is therefore not a pile of race fixes; it is the identification of **one
load-bearing, undocumented invariant** plus **one genuine non-race correctness gap**.

## The load-bearing invariant (the actual finding)

The brain runs as **one uvicorn worker** (`run_brain.py`: `uvicorn.run(..., reload=False)`, default
`workers=1`), single asyncio event loop, single process. The auth path `complete_session` is called
**synchronously** inside its `async` route (no `await`, no threadpool), so its read-check-write of the
device counter runs to completion without yielding. The Tier-1 drain runs in a **helper thread that the
main loop `thread.join()`s on** (`tier1_queue._run_blocking`), freezing the main loop for the drain's
duration — so no request handler can interleave an `enqueue` during the drain's `await`.

**Consequence:** every "race" below is currently impossible. Each becomes live the instant any one of
these changes: `workers > 1`; auth/drain offloaded to a threadpool; a second brain process sharing
`devices.json`; or `_drain_async` awaited directly in-loop. Today nothing documents this, asserts it,
or makes the shared state safe-by-construction.

## Per-item adjudication

| Item | Lens raw | Adjudicated | Why |
|------|----------|-------------|-----|
| `app_auth.py` counter `bump_counter` lost-update | concurrency FLAG | **Latent** | `complete_session` sync-called, no await in the read-check-write; single worker. Real only across a process/thread/worker boundary sharing `devices.json`. |
| `tier1_queue.py` snapshot-then-`await`-then-mutate | concurrency FLAG | **Latent** | `drain()` runs `_drain_async` in a helper thread and `thread.join()`s it, blocking the main loop — no same-loop `enqueue` can interleave the `await` at line 133. Real only if another thread calls `enqueue`, or `_drain_async` is awaited in-loop in a future path. |
| `memory/schema.py` UNIQUE-on-current-row | concurrency CLEAN | **Not a race here** | DDL only. Write path (`repository.add/update/tombstone`) is sync, driven from one connection on one loop → serialized. SQLite uniqueness mediates anything that slips through. NB: the repo's single `sqlite3` connection is **not thread-safe** — a write from the drain thread would raise; the current drain path (ntfy delivery only) never writes the repo, so untriggered. |
| `staging/service.py` approve state-machine flip | concurrency CLEAN | **Guarded** | `approve()` does a conditional `PENDING→EXECUTING` CAS (`set_status_conditional` = `UPDATE ... WHERE status=? ` + `rowcount` check, atomic at SQL level) before the awaited dispatch. A concurrent approve/reject observes non-`PENDING` and does not double-dispatch. |

## The one genuine non-race gap (security lens, model-diversity win)

**`staging/service.py:84` — at-most-once is violated for non-atomic external twins.** On any exception
from `tool_spec.callable_ref`, `approve()` rolls the row back `EXECUTING→PENDING`, making it
re-approvable. If a `takes-action` twin performs an **external side effect and then raises** (e.g.
`calendar.create` succeeds at Google but the response handling throws), re-approval dispatches the
effect **again**. This is independent of worker count — it fires on a single request. The concurrency
lens correctly called the same code CLEAN (it is idempotent *as a state machine*); the security lens
caught the *external-effect* angle the concurrency question doesn't ask. Clean demonstration of the
ensemble's disjoint-coverage thesis.

**Calibration:** no external-effect twin is live un-gated today (calendar write is deferred to the
Google-spoke go-live). So this is a **must-fix-before-Google-spoke**, not an active bug.

## Lower findings

- **Device enumeration via `begin_session`** (security FLAG): issues a nonce then `consume`s + raises
  `AuthError` for unknown device IDs — constant *work* but observable success/failure differs, letting a
  caller probe registered device IDs. Hardening only under the loopback single-owner threat model.
- **`tier1_queue` drain blocks the main event loop** (`thread.join()`): a *liveness/latency* concern
  (apex-performance), not a correctness race — all request handling stalls for the drain's duration.

## Recommended actions (ranked)

1. **`harden-background-invariants`** (highest leverage) — convert the latent landmine to safe-by-
   construction: (a) document the single-worker invariant where it lives (contracts.md / ADR-033);
   (b) assert `workers==1` (or guard) at brain startup; (c) add an OS file lock around
   `DeviceRegistry.bump_counter`'s read-modify-write and `Tier1Queue` persist so a second process /
   future threadpool can't lost-update `devices.json` / the queue. Small, ≤3 files.
2. **`staging-at-most-once-on-external-effect`** — stop auto-rollback `EXECUTING→PENDING` on dispatch
   exception for `takes-action` twins; route to a terminal `FAILED`/needs-review state instead (or only
   rollback for known no-effect tools). Gate-time: **before** any external-effect twin goes live.
3. **Defer / document** device enumeration + drain-blocks-loop — record in this doc; not worth a spec
   under the current threat + single-owner-latency model.

## Process note

Ensemble cost: 2 Codex subprocesses (off-Max, schema-clean) + 1 Opus adjudication. Both lenses honored
the supplied deployment model and downgraded their own raw FLAGs accordingly — the adjudication tier
still earned its keep (the staging external-effect angle, the cross-thread sqlite note, the calibration
that all four are latent). Confirms keeping BOTH families. Remaining Tier-1 backlog to run next:
nothing — this drained the P0 set. Tier-2 (P1) backlog in `REVIEW-ENSEMBLE-DESIGN.md` is the next audit.
