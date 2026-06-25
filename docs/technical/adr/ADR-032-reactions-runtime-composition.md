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

> **Superseded by the Amendment below** (2026-06-25 fork resolutions + email-layer gap). The build
> plan is re-carved into six specs across two waves; see § Amendment "Revised build plan".

---

## Amendment — fork resolutions + email structured-extract layer (owner walkthrough, 2026-06-25)

A six-agent deep-research pass (`docs/research/2026-06-25-reactions-composition/`) plus an owner
walkthrough resolved six design forks (`docs/drafts/reactions-compose-DISCUSSION.md`). Two override
Decisions in the body above; one (Fork 1) surfaced a build-time gap during codebase verification that
materially expands scope. The owner chose the full end-state build (2026-06-25).

### Fork decisions

- **Fork 1 — `EMAIL_INGESTED` payload = claim-check + thin flag envelope (refines Decision 3).**
  The emitted payload carries only `{message_id, source_ref, dedup_id}` plus small **non-sensitive
  classification flags** `has_commitment` / `has_event` / `has_gift_signal`. No summary, body, PII, or
  model output inline. Handlers read flags to route cheaply, then **fetch the laundered structured
  extract via `source_ref`** (injected lookup) for content. Rationale: **OWASP LLM01:2025** — fanning
  AI-extracted content out to every subscriber propagates prompt-injection; claim-check keeps untrusted
  content behind a ref. (Rejected: carrying laundered fields inline — lower churn but reopens the wall.)
- **Fork 1b — emit timing = post-extraction.** Emit after the laundered extract exists so the flags can
  be computed. Skipping non-usable/injection-flagged mail is intended; the path must **log (not swallow)**
  transient extraction failures so legitimate mail is not silently dropped.
- **Fork 2 — run model = continuous bounded worker (OVERRIDES Decision 2).** Replace heartbeat-drain
  with a continuous `await queue.get()` worker that drains the whole backlog on wake (reactive latency +
  batching). Bounded `asyncio.Queue(maxsize=…)` + `put_nowait` catching `QueueFull` (drop+log on
  overflow); `queue.shutdown()` for graceful stop. `compose_reactions` owns the worker task lifecycle.
- **Fork 3 — observe-first go-live (refines Decision 4) + 4 guardrails.** Keep `reactions_mode`
  default `"observe"`. Guardrails: (a) block effects at the effect **seam**, not in rule logic; (b) one
  log stream tagged `WOULD`/`DID`; (c) re-evaluate sensitivity at **fire** time, not observe time;
  (d) **manual** per-domain / whole-system flip by the owner reading the `WOULD` log — **no
  auto-graduation threshold** (intermittent dev uptime makes counts lumpy; owner stays in control).
- **Fork 4 — phantom-claim = at-least-once / idempotent (OVERRIDES the built dispatcher).** Never
  silently skip an event-triggered reaction; retry on reboot. The dispatcher moves from
  claim-before-effect (at-most-once) to **effect-then-claim** (provisional claim committed only after
  the effect succeeds), so a crashed/failed effect re-fires rather than being permanently swallowed.
  Requires: an **idempotency-key** propagated through downstream effects (GATE stage keyed by a stable
  key, ntfy dedup-keyed, ledger writes already idempotent via `raw_ref UNIQUE`); an idempotency audit
  of every external-effect reaction; and a ledger **TTL** so the dedup table is bounded.
- **Fork 5 — tiered side-effect routing = no change.** Definition-time risk classification;
  unknowns → most-restrictive; external → GATE approval; low-confidence-irreversible → inert suggestion.
- **Fork 6 — cascade/loop guard = depth-counter (NEW).** Add `depth: int = 0` to `DomainEvent`
  (producers emit at depth 0). The dispatcher hands each fired handler an `emit` pre-bound to stamp
  `depth + 1`; events past `MAX_REACTION_DEPTH` (default **5**, tunable via `policy.json` →
  `ReactionConfig.max_reaction_depth`) are dropped + logged. Depth counts **event-hops**
  (reaction → emit → reaction), not tool-calls or fan-out width. The existing per-`(rule, stable_key)`
  refraction dedup is kept (catches true same-rule loops at depth 1; depth is the coarse backstop for
  changing-key runaways). Worked examples confirm rich assistant cascades are shallow in event-hops
  (flight-email → trip → {check-in, packing, visa, leave} = depth 2; the richness is fan-out, not depth).

### Email structured-extract layer (NEW — closes the Fork-1 build gap)

Codebase verification found that **no producer builds the structured email payload** the shipped comms
reactions (A4/A5/A7) read, and **no fetchable laundered-extract store exists**: `QuarantinedReader`
returns only `summary`/`claims`/`flagged_injection` (transient), `GmailIngestor.ingest_message` emits
nothing, and the rich-payload reactions are dormant. Realizing the email-reaction path (under either
fork option) requires a detection step that was never specced. The owner chose to build it fully:

1. **Email detection/structuring step** (gmail module). Runs over the **laundered** `Extract.summary`
   (post-quarantine, injection-flagged input already blanked — privileged-safe), on the **LOCAL**
   responder (ADR-022: email is owner-private → local; never cloud), via structured output. Produces
   the non-sensitive flags (`has_commitment`/`has_event`/`has_gift_signal`) + the structured
   `event_kind`/`start_dt`/`end_dt`/`location`/`attendees`/trip-fields/`gift_item` content. Runs only
   on usable extracts; logs (not swallows) transient failures.
2. **Quarantined-extract store** (owner-private SQLCipher, TTL'd, keyed by `source_ref` =
   `gmail:{message_id}`). Persists the structured laundered extract so reactions can fetch it after
   emit. **Owner-private — never leaves the box.** A `fetch_extract(source_ref)` lookup seam is injected
   into the comms reactions.
3. **Emit** `EMAIL_INGESTED` (Fork-1 thin payload) **after** detection+store. Calendar `EVENT_INGESTED`
   stays scalar-only (no detection layer — calendar fields are already structured/laundered upstream).
4. **comms fetch-via-ref rework.** A4/A5/A7 read the payload flags for routing, then fetch the
   structured extract from the owner-private store by `source_ref` for content — replacing the
   read-from-payload path. The gift reaction reads `has_gift_signal` + fetches `gift_item`, then writes
   a general-tagged fact via `MemoryWritePath.add_module_fact` (Decision 6).

Privacy invariant: the **only** thing that crosses to cloud is the gift fact (tagged `general` per
Decision 6); the laundered extract, flags routing, held-event creation, and task suggestions all stay
owner-private/local — consistent with the locked "email stays local" owner rule.

### Revised build plan (six specs, two waves)

**Wave 1 (file-disjoint, parallel):**
- **R1** — `compose_reactions` root + continuous bounded worker (Fork 2) + observe-mode gate (Fork 3) +
  effect-then-claim & ledger TTL (Fork 4) + `DomainEvent.depth` & cascade guard (Fork 6) +
  `reactions_mode`/`max_reaction_depth` on `ReactionConfig`. Foundation.
- **R3** — `linked_task_ref` propagation (Decision 5; lights up `react_bill_paid_lifecycle`). Unchanged
  by the forks.
- **R4m** — `MemoryWritePath.add_module_fact` structured push (Decision 6); buildable/testable against
  fakes. Gift *reaction* registration deferred to R6.
- **R5d** — email detection/structuring step + quarantined-extract store + `fetch_extract` seam.

**Wave 2 (file-disjoint, parallel):**
- **R2** — emit seams: gmail `EMAIL_INGESTED` (post-detect, Fork-1 payload, log-not-swallow) + calendar
  `EVENT_INGESTED` (scalar) + wire all four producers. Depends on R1 (bus) + R5d (flags/store).
- **R6c** — comms A4/A5/A7 + gift fetch-via-ref rework + register `reaction:gift_signal`. Depends on
  R5d (`fetch_extract`) + R4m (`add_module_fact`).

R1/R2/R4m/R5d/R6c carry `cross_model_review: true` (first end-to-end go-live on live untrusted email +
the first non-owner memory writer + a dispatcher delivery-semantics change). R3 does not.
