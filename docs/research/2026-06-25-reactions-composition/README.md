# Research synthesis — Reactions runtime composition (decision brief)

**Date:** 2026-06-25
**For:** the next planning session (composing the dormant reactions runtime — ADR-032 + R1–R4)
**Confidence:** MEDIUM–HIGH. Idempotency, run-model, dry-run, automation-engine = HIGH (primary +
strong community). Event-payload core claims are MEDIUM ([COMMUNITY] from search snippets; only
CloudEvents fetched Tier-1) — the canonical sources (Fowler/EIP/MS/AWS/Confluent/OWASP) sit on
WebFetch-denied domains; a `NEEDS-DOMAIN` registry (~17 URLs) is listed at the bottom to upgrade them.
**Re-research after:** 2027-06-25 (general architecture patterns).

Six Phase-2 retrieval agents (Sonnet) → per-topic docs in this directory. This README is the Phase-3
synthesis: dedup across agents, confidence-weighted, mapped to the live forks, with a recommendation
per fork. **It is a recommendation for the discussion, not a locked decision.**

---

## TL;DR — recommendation per fork

| Fork | Research verdict | Recommendation |
|------|------------------|----------------|
| **`EMAIL_INGESTED` payload (A vs B)** | Don't fan out AI-extracted/untrusted content in events (OWASP LLM01 injection-propagation); **claim-check** is the named pattern; SOTA hybrid = thin envelope + reference | **Option B reframed as claim-check + thin classification envelope** — payload = ids + `source_ref` + small *non-sensitive* flags; handlers fetch the quarantined extract via the ref. Rework the built comms reactions to fetch. |
| **Emit timing (sub-fork)** | Post-commit/task-boundary triggers got 52% engagement vs mid-flow dismissed | Lean **emit post-extraction** (extract + flags exist, security-clean) — but resolve the "extraction is skippable" gap (see Fork 1). |
| **Run model** | Continuous worker ≈ 1 loop-cycle latency; tick = free lifecycle; **hybrid = drain-all-on-wake** gets both; bound the queue | Keep ADR-032's heartbeat-drain for v1 (simplest), but adopt **bounded queue + put_nowait** now; note the hybrid drain as the low-latency upgrade. |
| **Observe-first** | Validated pattern (Terraform plan, k8s dry-run, AJO); but 6 named divergence pitfalls | Keep observe-default; **block writes at the seam not the logic**, tag `WOULD`/`inDryRun` in one stream, document suppressed effects, set **explicit exit criteria** (avoid "permanent purgatory"). |
| **Idempotency / dedup** | `INSERT OR IGNORE` try_claim = canonical; single-consumer ⇒ no TOCTOU; phantom-claim is the real hazard | **Built design confirmed correct.** Decide the **phantom-claim** posture (at-most-once claim-before-effect vs at-least-once) and add **TTL** to the ledger. |
| **Tiered routing** | Classify at *definition time*, unknowns→most-restrictive; inert-suggestion ≠ approval-queue | **Built design confirmed** (rule `external_effect` at definition; A4 inert). No change. |
| **Cascade/loop prevention** | Real failure mode (reaction→event→reaction); mitigations: refraction, depth limit, control-fact sentinel | **NEW gap to address** — add a cascade guard (depth/origin tag on emitted events). |

---

## Fork 1 — `EMAIL_INGESTED` payload contract (the centerpiece)

**The three-way mismatch** (built comms read sanitized fields · R2 emits scalar `{message_id,
source_ref}` · R4 expects gift fields) maps onto canonical event patterns:
- **Option A (fat / ECST event)** — full derived state inline. *Worst* for sensitive/untrusted content;
  largest schema-coupling + versioning blast radius, amplified by fan-out. `[COMMUNITY]`
- **Option B (thin / notification)** — ID only; highest runtime coupling (N fetches). `[VERIFIED]`
- **Claim-check** — event carries a *reference*; handlers fetch from a store. The named pattern when
  payloads are sensitive or large. `[COMMUNITY — EIP]`

**The decisive security finding (`[COMMUNITY — OWASP LLM01:2025]`):** fanning out AI-extracted content
*before validation* propagates indirect prompt-injection to **every** subscriber. Mitigation: keep the
untrusted-derived body behind a reference; validate/quarantine at the producer. Artemis already
quarantines (DR-a: spotlight + blank-on-flag + `Extract.usable`) — so the body is laundered — but the
data-minimization + injection-blast-radius argument still says **don't re-fan the extracted body
through a multi-subscriber event.**

**Recommendation — Option B reframed as claim-check + a thin classification envelope:**
- `EMAIL_INGESTED` payload = `{ message_id, source_ref (the quarantined-extract ref), dedup id,
  + small NON-SENSITIVE classification flags: has_commitment / has_event / has_gift_signal }`.
  No summary/body/PII inline. (Multiple sources converged on this thin-envelope-+-ref hybrid.)
- Handlers (A4/A5/A7, gift) read the flags to cheaply decide whether to act, then **fetch the
  quarantined extract via `source_ref`** (an injected lookup) for the content they need.
- **Cost (the honest part):** rework the *built* comms reactions from read-from-payload to
  fetch-via-ref. This is the Option-B churn — but the research says it's the security-correct design,
  and the flags let a handler skip the fetch when its flag is false.
- Dedup key = composite `(source, message_id)` per CloudEvents `[VERIFIED]`.

**Residual sub-fork to resolve at the table — emit timing:**
- *Emit at ingest* (R2's current draft): every email emits, but the extract/flags don't exist yet →
  handlers must trigger extraction themselves. Simpler emit, more handler work, no flags for routing.
- *Emit post-extraction* (recommended): the extract + classification flags exist → clean thin envelope,
  matches the "post-commit triggers = 52% engagement vs mid-flow dismissed" timing finding
  `[COMMUNITY — arxiv]`. **Blocker to fix:** R2 rejected this because the extraction path is
  "best-effort/skippable" → skipped emails never react. Resolve by making extraction reliable for
  reaction-relevant mail, or emit a minimal `{id, ref}` at ingest and let handlers pull-extract.

---

## Fork 2 — Run model

`[VERIFIED — CPython source, Temporal, nullprogram.com benchmark]` A continuous `await queue.get()`
worker wakes ~1 event-loop cycle after `put_nowait` (not tied to any tick). A tick-coupled drain adds
up to one tick of latency and *inherits event-loop saturation delay* (200 concurrent tasks → 1.5 s tick
lag in the benchmark). The **hybrid** — a continuous worker that, on wake, drains all currently-queued
items (`while not q.empty(): q.get_nowait()`) — gets reactive latency **and** per-batch coalescing.

**Recommendation:** ADR-032's heartbeat-drain is fine for v1 (free lifecycle, reactions aren't
latency-critical). Adopt **now**, regardless: a **bounded** `asyncio.Queue(maxsize=…)` + `put_nowait`
+ catch `QueueFull` (every unbounded queue is a latent bug). Keep the hybrid drain in the back pocket
as the low-latency upgrade if tick-lag ever bites. Python 3.13 `queue.shutdown()` for graceful drain.

---

## Fork 3 — Observe-first go-live

`[HIGH]` The pattern is well-established (Terraform plan/apply, k8s `--dry-run`, Adobe AJO Journey Dry
Run, ITSM agent shadow mode). Design choices worth copying:
- **Tag `WOULD`/`inDryRun` in the same event/log stream as live** (AJO) — compare would-do vs did-do
  without a separate store.
- **Block writes at the seam (API/effect boundary), not in application logic** — prevents mutation
  leakage and keeps reasoning identical between observe and live.
- **Observe = default; explicit `live` flag to act** (matches ADR-032).

**Pitfalls to design against (all `[HIGH]`):**
1. **Phantom-state paradox** — suppressing a write breaks a multi-step chain whose later step reads the
   suppressed write. (Artemis reactions are mostly single-step; flag any multi-step recipe.)
2. **Suppressed side effects change downstream branches** — *document exactly which effects observe
   suppresses* (stage / execute / suggest / memory-write).
3. **Point-in-time staleness** — a fact `general` at observe time may be `sensitive` at live time;
   re-evaluate sensitivity at fire time, not observe time.
4. **Permanent-purgatory anti-pattern** — observe with no exit criteria never graduates. **Set exit
   criteria up front** (e.g. N clean observations + zero critical mis-fires → flip to live).
5. **Training-prod gap** — observe accuracy on small/synthetic samples overstates live.

Graduation model `[HIGH — Redis 2026]`: HITL (ask) → HOTL (act + monitor/veto) → HOOTL (auto in scope)
maps onto Artemis's "always-ask → auto-with-undoable-notice → silent-auto." Confidence alone is
unreliable; use trust-score + risk-category flags.

---

## Fork 4 — Idempotency / dedup (validation of the built dispatcher)

`[VERIFIED/COMMUNITY — Stripe/Brandur, Temporal, Hooklistener, theburningmonk]`
- `INSERT OR IGNORE` try_claim = **the canonical atomic-claim pattern**. ✓ built correctly.
- **Single-consumer sequential drain ⇒ the TOCTOU race is absent** — confirms the RXN-dispatcher review
  flag: the `state_hash` read-compare-then-write is safe for one writer; only a *future multi-consumer*
  drain needs CAS / `BEGIN IMMEDIATE`. ✓
- **Phantom-claim hazard (decide tonight):** the dispatcher claims *before* the effect (at-most-once —
  claim persists even if the effect raises). A failed stage/execute is then never retried. Choose:
  keep at-most-once (simple, safe-by-omission), or move to effect-then-claim / idempotent effects
  (at-least-once) for the external-effect path. For a single-owner assistant, at-most-once + a logged
  failure is defensible — but make it a *conscious* choice.
- **Add a TTL** to the ledger sized to the retry/replay window (Stripe uses 24 h); note DLQ-replay
  bypasses an expired key. Propagate the same idempotency key to downstream effects (ntfy, GATE stage).

---

## Fork 5 — Tiered side-effect routing (validation)

`[VERIFIED]` Across HA / n8n / Zapier / published taxonomies (MindStudio 4-tier, Antigravity 3-tier
~70/22/8 auto/checkpoint/block): **reversibility/irreversibility is the central axis**, classified at
**definition time in the action registry**, unknowns default to most-restrictive. "Inert suggestion" =
below-confidence + irreversible → a *suggestion* queue, distinct from an *approval* queue. This is
exactly Artemis's design: rule `external_effect` set at definition; external→GATE stage;
internal-reversible→auto+notice; A4→inert CaptureService suggestion. **No change recommended.**
(Minor divergence: consumer products embed rules in flow config; Artemis uses a `ReactionRuleStore` +
`TIER_A_BUILTINS` — a deliberate, fine choice.)

---

## Fork 6 — Cascade / loop prevention (NEW gap)

`[VERIFIED]` The classic rule-engine failure mode: a reaction's effect emits an event that triggers
another reaction → infinite cascade. Mitigations: **refraction** (don't re-fire the same activation),
**depth/iteration limit**, **control-fact sentinel**, **edge-triggering**, payload-hash dedup at entry.
Artemis's per-`(rule, stable_key)` dedup ledger already gives refraction for *repeat* events, but does
**not** bound a reaction→emit→reaction *chain*. **Recommend:** tag emitted events with an origin/depth
marker and have the dispatcher drop events beyond a small depth (e.g. 3), or forbid reactions from
emitting the event types they consume. Cheap insurance; worth a task in R1 or a follow-up.

---

## Architecture validation (comparable systems)

`[VERIFIED]` Home Assistant's core *is* an event bus + a rule layer on top — Artemis's exact shape.
Event-sourcing/CQRS and full Temporal/saga are overkill for a single-user box; the in-process bus +
SQLite ledger is the validated "80% at 20% complexity" point. Letta's **single-writer memory
discipline** is a clean answer to concurrent memory writes — relevant as the module-fact-push becomes
the first non-owner writer (keep memory writes single-flight, which `MemoryWriteQueue` already is).
MemOS validates **provenance-at-write** (source/trigger/model id per memory unit) — supports R4's
`source_ref` provenance on module facts.

---

## Confidence caveats & `NEEDS-DOMAIN` registry (for a Tier-1 upgrade pass)

Many event-payload + automation-engine claims are `[COMMUNITY]` (search snippets) because the canonical
sources are on WebFetch-denied domains. To upgrade them to `[VERIFIED]`, authorize these and I'll
re-dispatch a short fetch pass: `martinfowler.com`, `microservices.io`, `learn.microsoft.com`,
`docs.aws.amazon.com`, `developer.confluent.io`, `event-driven.io`, `genai.owasp.org`,
`www.enterpriseintegrationpatterns.com`, `www.home-assistant.io`, `docs.n8n.io`, `www.elastic.co`,
`verraes.net`, `oneuptime.com`, `redis.io`. (Per-topic docs list the full per-claim URLs.)

**Bottom line for tonight:** the research **confirms the built dispatcher + tiering + observe-first
posture**, and gives a clear, security-grounded answer to the `EMAIL_INGESTED` fork — **claim-check +
thin classification envelope (Option B refined)** — at the cost of reworking the built comms reactions
to fetch-via-ref. Two new decisions surfaced: the **phantom-claim** posture and a **cascade guard**.
