# ADR-032 — Reactions runtime composition + go-live posture

**Status:** Accepted (2026-06-25)
**Relates to:** ADR-021 (cross-module reactions design) · ADR-029 (sensitivity wall) · ADR-022 (model/runtime routing)
**Supersedes/extends:** none (the missing composition half of ADR-021)

## Context

The ADR-021 reactions layer is **fully built but never composed into the running app**. As of
2026-06-25 (`7ab1c43`) the engine, idempotency ledger, rule store, reconciler, trip/maps connectors,
calendar-create seam, and all three recipe packs (planning/comms/self) exist and pass their tests —
but `EventBus()` is constructed **only in tests**. No production code wires
`EventBus → ReactionDispatcher → rule store/ledger → register_*_reactions`, and the emitters' `emit=`
seams default to no-op. Every reaction is therefore dormant.

Two surfaced "blockers" were symptoms of this gap:
- `reaction:gift_signal` is unregistered (needs a memory module-fact-push that didn't exist).
- `react_bill_paid_lifecycle` is dead in production (`bill_paid_event()` never emits the
  `linked_task_ref` it reads).

Additionally, emit seams are unevenly built: **finance** and **trips** expose an `emit=` callable;
**gmail** (`EMAIL_INGESTED`) and **calendar** (`EVENT_INGESTED`) have no emit seam, so the comms
reactions (A4/A5/A7), which consume `EMAIL_INGESTED`, can never fire as-is.

## Decision

Compose the reactions runtime end-to-end, behind the existing dispatcher safety wall, with an
observe-first break-in period.

1. **`compose_reactions` root (new `src/artemis/reactions/compose.py`).** Mirrors `compose_proactive`:
   constructs the `EventBus`, `ReactionLedger` (keyed sqlite), `ReactionRuleStore` (seeded with
   `TIER_A_BUILTINS`), and the `ReactionDispatcher`; registers
   `register_planning_reactions`/`register_comms_reactions`/`register_self_reactions`; returns the bus
   (for emitters) + the dispatcher.

2. **Run model = heartbeat-drain.** `ReactionDispatcher.drain_once` is injected as a heartbeat
   `pre_tick_step` (the seam the Tier-1 queue already uses via `attach_to_heartbeat`). Reactions fire
   at heartbeat cadence — no new task lifecycle. `EventBus.emit` is sync and enqueues sync, so emitting
   is cheap and non-blocking; the async drain happens on the tick. (Rejected: a dedicated `run_forever`
   background task — lower latency, more lifecycle to manage, unnecessary for "when-X-then-Y" automations.)

3. **Wire all four emitters.** Pass `bus.emit` into the existing finance and trips `emit=` seams, and
   **add** an `EMAIL_INGESTED` emit seam to the gmail ingest path and an `EVENT_INGESTED` emit seam to
   the calendar ingest path. Without the gmail seam the comms reactions cannot fire at all.

4. **Go-live posture = observe-first dry-run.** Add `reactions_mode: Literal["observe","live"]` to
   `RuntimeConfig` (default `"observe"`). In `observe`, the dispatcher routes every would-be effect
   (stage / execute / suggest) to the `notice_sink` as a logged "would do X" and takes **no** action —
   no staging, no writes, no suggestions. Flip to `live` after the break-in period. In `live`, the
   ADR-021 tiering holds (the owner's locked autonomy boundary): internal-reversible auto-runs with an
   undoable notice; external-effect only ever `stage`s for owner approval (GATE); A4 is structurally
   inert. The composition injects the **real** staging/capture/notice services — never fakes.

5. **`linked_task_ref` propagation.** `bill_paid_event()` gains an optional `linked_task_ref`; A1/A9
   source it from the bill record (FIN-a schema already carries `linked_task_ref`) so
   `react_bill_paid_lifecycle` can complete the linked task in production.

6. **Gift-signal module-fact-push (memory contract addition).** Add a module-initiated **structured**
   fact push to the memory write path (the gift detection already happened in the reaction — it must
   NOT re-extract from text). Gift facts are person-attached, `category="gift_signal"`, and tagged
   **`sensitivity="general"`** (owner decision 2026-06-25): cloud-injectable so proactive gift help
   ("what should I get Ashley?") can use them. Provenance records the module source ref. This is the
   one place a non-owner, non-extractor source writes a fact — it carries an explicit sensitivity
   (general) rather than defaulting through the classifier.

## Consequences

- Reactions become live for the first time; the observe-first flag makes the cutover auditable and
  reversible (flip back to `observe` is a config change).
- The dispatcher gains an `observe` mode gate (additive to the `7ab1c43` build).
- New emit seams on gmail/calendar are additive (no-op default preserved off-composition).
- The memory write path gains a module-source structured-fact push — the first writer outside the
  owner/extractor; tagged general for gifts, fail-closed sensitive remains the default for all other
  module facts.
- Security review required on the go-live path (first time reactions act on live email/finance) —
  the spec carries `cross_model_review: true`.

## Build plan

Four file-disjoint, dependency-ordered specs (see docs/changes/): **R1** compose root + observe mode +
`reactions_mode` config + heartbeat wiring · **R2** emit seams (gmail `EMAIL_INGESTED` + calendar
`EVENT_INGESTED`) + wire all four emitters into the composition · **R3** `linked_task_ref` propagation
(unblocks `react_bill_paid_lifecycle`) · **R4** memory module-fact-push + register `gift_signal`
(general). R3 and R4 are independent of each other and of R2; R1 is the foundation.
