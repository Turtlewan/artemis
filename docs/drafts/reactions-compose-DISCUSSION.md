# Reactions runtime composition — discussion prep (for the next planning session)

**Design locked + recorded:** ADR-032 (reactions runtime composition + go-live posture).
**Four Deep-Details drafts queued in `docs/drafts/`** (NOT yet gate-passed → not in `docs/changes/`):
`R1-reactions-compose.md` · `R2-reactions-emit-seams.md` · `R3-linked-task-ref.md` ·
`R4-memory-module-fact-gift.md`.

Decisions already made (ADR-032): heartbeat-drain run model · all four emit seams · observe-first
`reactions_mode` flag (default observe) · gift facts `sensitivity="general"` · `linked_task_ref`
propagated via an injected lookup.

---

## ✅ FORKS RESOLVED — owner walkthrough 2026-06-25

All six research forks decided with the owner. **Two decisions override the original ADR-032**
(run model + phantom-claim) → ADR-032 needs an amendment block; the R1–R4 drafts need patching to
match before the readiness gate.

| Fork | Decision | Override? |
|------|----------|-----------|
| **1 — `EMAIL_INGESTED` payload** | **Option B (claim-check + thin flag envelope).** Payload = `{message_id, source_ref, dedup_id}` + small NON-SENSITIVE flags `has_commitment` / `has_event` / `has_gift_signal`. No summary/body/PII inline. Handlers read flags to route cheaply, then fetch the quarantined extract via `source_ref` (injected lookup) for content. | reshapes R2/R4 + **built `recipes/comms.py`** (rework read-from-payload → fetch-via-ref) |
| **1b — emit timing** | **Post-extraction.** Emit after the laundered extract exists so the flags can be computed. Skipping non-usable/injection-flagged mail is intended (safe). Harden the path to **log (not swallow)** transient extraction failures so legitimate mail isn't silently dropped. | moves R2's emit off `ingest_message` → the extraction path + adds a flag-computation step (flags don't exist in code today) |
| **2 — run model** | **Continuous / hybrid worker (drain-on-wake) + bounded queue.** Continuous `await queue.get()` worker that drains the whole backlog on wake (reactive latency + batching). Bounded `asyncio.Queue(maxsize=…)` + `put_nowait` + catch `QueueFull`; `queue.shutdown()` for graceful stop. R1's `compose_reactions` owns the worker task. | **OVERRIDES ADR-032 Decision 2** (was heartbeat-drain v1) |
| **3 — observe-first go-live** | **Keep observe-first default + 4 guardrails: (a)** block writes at the effect SEAM not in logic; **(b)** one log stream tagged `WOULD`/`DID`; **(c)** re-evaluate sensitivity at FIRE time not observe time; **(d)** **manual yes/no flip** (owner reads the WOULD log, flips per-domain or whole-system by hand). NO auto-graduation threshold (intermittent dev uptime makes counts lumpy; owner stays in control). | refines ADR-032 (adds guardrails; picks manual over threshold) |
| **4 — phantom-claim posture** | **At-least-once (act-first / idempotent effects).** Never silently skip an event-triggered reaction; retry on reboot. Requires: dispatcher amend (effect-then-claim OR provisional-claim-committed-after-effect), idempotency audit of every external-effect reaction (GATE stage keyed by stable idempotency key, ntfy dedup-keyed, ledger writes already safe via `raw_ref UNIQUE`), **propagate ONE idempotency key** through downstream effects, + ledger **TTL**. | **OVERRIDES** the built `RXN-dispatcher` (e69e267) at-most-once claim-before-effect |
| **5 — tiered side-effect routing** | **No change.** Definition-time risk classification, unknowns→most-restrictive, external→GATE approval, low-confidence-irreversible→inert suggestion. Research-validated. | — |
| **6 — cascade / loop guard** | **Depth-counter, default 5, tunable in `policy.json` (`MAX_REACTION_DEPTH`).** Depth = EVENT-HOPS (reaction→emit→reaction), NOT tool calls or fan-out within a reaction. Add `depth: int = 0` to `DomainEvent` (producers emit at 0); dispatcher hands each handler an `emit` pre-bound to stamp `D+1`; drop+log events past the limit. Keep existing per-`(rule, stable_key)` refraction dedup (catches true same-rule loops at depth 1; depth is the coarse backstop for changing-key runaways). | NEW (gap research surfaced) |

**Worked examples confirming depth=5 is generous (Fork 6):** "my-flight email → trip → {check-in, packing, visa, leave-for-airport}" = max depth **2** (fan-out is width, not depth); "someone-else's-flight → Maps + pickup event + leave-by + task" = depth **1** (all tool calls inside one reaction). Rich assistant cascades are shallow in event-hops because the richness is tool-calls + fan-out, which depth doesn't count.

### Next-session flow (revised)
1. ~~Resolve the A/B fork~~ ✅ done above.
2. **Amend ADR-032** — record the Fork 2 (run model) + Fork 4 (phantom-claim) overrides + Fork 3 guardrails + Fork 6 cascade guard + Fork 1/1b payload contract.
3. **Patch the drafts:** R2 (emit post-extraction, Option-B payload + flags, harden transient-fail logging) · R4 (gift detection over fetched extract, not pre-computed payload fields) · R1 (own the continuous worker + bounded queue + cascade-depth stamping) · `recipes/comms.py` rework note (fetch-via-ref) · `RXN-dispatcher` amend (at-least-once + depth guard) · `DomainEvent` (+`depth`) · `policy.json` (+`MAX_REACTION_DEPTH=5`). R3 unaffected by these forks.
4. Dispatch security/data domain reviews on R1/R2/R4 (go-live + memory-contract + untrusted-email + the new at-least-once idempotency surface).
5. Readiness gate on all four; move to `docs/changes/`.
6. Build order: R1 → R2 ∥ (R3, R4 independent).

---

## 🔬 RESEARCH VERDICT (2026-06-25, L5 deep-research pass)

6-agent deep research → `docs/research/2026-06-25-reactions-composition/` (synthesis: `README.md`).
**Headline:** the research **confirms the built dispatcher, tiering, and observe-first posture**, and
gives a security-grounded answer to the EMAIL_INGESTED fork:
- **Resolve the A/B fork as Option B reframed = claim-check + thin classification envelope.** Payload =
  `{message_id, source_ref, dedup id, + small non-sensitive flags has_commitment/has_event/has_gift_signal}`;
  handlers fetch the quarantined extract via `source_ref`. Rationale: **OWASP LLM01:2025** — fanning out
  AI-extracted content before validation propagates prompt-injection to every subscriber; claim-check
  keeps the untrusted body behind a ref. Cost: rework the built comms reactions to fetch-via-ref.
- **Sub-fork (emit timing):** lean emit **post-extraction** (flags+extract exist; matches the
  "post-commit triggers = 52% engagement" finding) — but fix R2's "extraction is skippable" gap first.
- **2 NEW decisions surfaced:** (1) **phantom-claim** posture — the dispatcher claims before the effect
  (at-most-once; a failed stage/execute never retries) → keep, or move to effect-then-claim; add a
  ledger **TTL**. (2) **Cascade guard** — nothing bounds a reaction→emit→reaction chain; add a
  depth/origin marker or forbid reactions emitting the types they consume.
- **Confirmed (no change):** INSERT-OR-IGNORE try_claim is canonical; single-consumer ⇒ the
  stateful-atomicity TOCTOU is a non-issue (matches the review flag); definition-time tiering with
  unknowns→most-restrictive; inert-suggestion≠approval-queue; event-bus+SQLite-ledger = right small-system fit.
- **Observe-mode design inputs:** tag WOULD/inDryRun in one stream · block writes at the seam not the
  logic · re-evaluate sensitivity at fire time (point-in-time staleness) · set explicit observe→live
  exit criteria (avoid "permanent purgatory").

Read `README.md` first tonight; the per-topic docs carry the cited detail + a `NEEDS-DOMAIN` registry
(authorize ~14 domains to upgrade the event-payload claims from [COMMUNITY] to [VERIFIED]).

## ⛔ KEY OPEN QUESTION — the `EMAIL_INGESTED` payload contract (3-way mismatch)

The comms reactions are already BUILT and consume `EMAIL_INGESTED`, but the new emit seam (R2) and
the gift reaction (R4) disagree with them on what the event carries. All three must be reconciled
before R2/R4 can pass the readiness gate's *sufficiency-audit* (does the emit actually produce what
the consumer needs?).

**What each side currently assumes:**
- **Built comms (A4/A5/A7), `recipes/comms.py`:** reads SANITIZED EXTRACT FIELDS from the payload —
  `extract_summary`, a `commitment` bool, `event_kind`, `start_datetime`/`end_dt`, `location`,
  `attendee_emails`, plus trip fields (`origin`/`destination`/`confirmation_ref`/`co_travellers`).
  Comment: *"The live Gmail pre-flight stores only sanitized extract fields on the event."* → expects
  emit to happen AFTER the quarantined extraction, payload carrying the laundered fields.
- **R2 draft (emit seam):** `EMAIL_INGESTED` = scalar-only `{message_id, source_ref}`, emitted at
  INGEST time in `GmailIngestor.ingest_message` (before/without the quarantined Extract). R2 explicitly
  rejected emitting from `GmailMemoryExtractor.extract` because that path is best-effort/skippable.
- **R4 draft (gift reaction):** reads `gift_signal_detected` / `gift_item` from the payload (gift
  detection assumed pre-computed upstream).

**The fork to decide:**
- **Option A — emit post-extraction, payload carries sanitized extract fields.** Matches the built
  comms reactions with zero rework; gift detection + commitment/event detection are upstream (gmail
  extraction). Cost: emit lives on the best-effort extraction path (skippable → some emails never
  emit), and the event payload grows (still sanitized/scalar text, no raw body — Seam 7 OK since the
  quarantined summary is laundered).
- **Option B — emit at ingest (`{message_id, source_ref}`), reactions FETCH the extract.** Generic
  `EMAIL_INGESTED` (one event, every reaction does its own detection over the fetched quarantined
  extract via an injected lookup). Cost: rework the BUILT comms reactions (A4/A5/A7) from
  read-from-payload to fetch-via-ref, plus R4 runs its own gift detection. More work, cleaner contract,
  fires on every email regardless of extraction success.

**Recommendation to weigh:** Option B is the architecturally cleaner end-state (generic event +
per-reaction detection over the laundered extract, matching ADR-021 Seam 7 "event carries the ref,
not the content"), but it reworks already-shipped comms code. Option A is lower-churn but couples the
emit to the skippable extraction path and bakes detection upstream. Decide this first — it reshapes
R2, R4, and the built `recipes/comms.py`.

## Secondary couplings (smaller, resolve after the contract)
- **R1 → R2 wiring boundary:** R1 keeps `compose_reactions` a thin wiring root and DEFERS passing
  `bus.emit` into producers to R2; R2 wires it at each construction site (no app-root exists yet).
  Confirm that split.
- **No production app-root/daemon exists** — nothing calls `compose_proactive`/`compose_reactions`
  together; reactions become integration-testable + observable, but a daemon mount is a separate
  bring-up step. (Not blocking R1–R4; flag for the bring-up plan.)
- **R3:** adds a surgical `get_bill(id)` finance read + injects `get_linked_task_ref_fn` into A1/A9
  (mark_bill_paid returns None today). Independent; low-risk.
- **R4 naming:** `TIER_A_BUILTINS` already has a `gift_signal` rule on `FACT_ADDED→memory.note_gift_signal`
  (downstream); R4 adds a DISTINCT `EMAIL_INGESTED` comms rule. Keep both, don't collide names.

## Next-session flow
1. Resolve the `EMAIL_INGESTED` contract fork (A vs B) → patch R2 + R4 (+ `recipes/comms.py` if B).
2. Dispatch security/data domain reviews on R1/R2/R4 (go-live + memory-contract + untrusted-email).
3. Run the readiness gate on all four; move to `docs/changes/`.
4. Build order: R1 → R2 ∥ (R3, R4 independent).
