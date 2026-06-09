# ADR-008 — Observability foundation (logging · telemetry · error tracking)

- **Status:** Accepted
- **Date:** 2026-06-08
- **Deciders:** owner + planning
- **Supersedes / relates:** ADR-001 (stack), ADR-003 (teacher cost/quota), ADR-006 (two-tier proactivity); consumed by M7-c (Curiosity Loop) and M2 escalation metrics.

## Context

The brain has no self-observation. brain.md states cloud-teacher spend should be "observable from
the escalation + self-confidence telemetry the brain already logs" — but no concrete writer exists.
M7-c (Curiosity Loop) is already specced and **defines** a `TelemetrySource` Protocol + a `TokenLedger`,
both built/tested against fakes; it is inert until a concrete telemetry backend lands. We need the three
standard observability pillars — structured logging, metrics/telemetry, error tracking — sized for a
single-box, local-first, owner-private appliance (no external SaaS, no PII egress).

## Decision

1. **Local-first, no external observability services and no OpenTelemetry collector.** Single-box
   appliance → structured local persistence (stdout JSON logs captured by launchd; a local SQLite
   telemetry store). External error-tracking SaaS (Sentry et al.) and an OTel collector are **out** —
   they would mean PII/usage egress and infra the box doesn't run. OTel-shaped export is deferred until
   a multi-host topology exists.

2. **Capture seam = "meter the pipe + thin taps" (not sink-everywhere).** Token/cost/latency is captured
   passively by a `TracingModelPort` wrapper around the one `ModelPort` chokepoint (zero edits to callers).
   Confidence, escalation, and caught errors — which never flow through the model-call pipe — are captured
   by a thin `ObservabilitySink` whose taps live in **only** the Brain (route decision + degrade-don't-crash
   except sites) and `escalate_and_distill`. Other components are added to the sink on demand when a real
   consumer needs their signal (additive, no rework). Rejected: a sink threaded through every component
   (router/retriever/memory/voice/ingestion) — builds plumbing before its consumer exists.

3. **Telemetry persisted to a local SQLite store, encrypted at rest via SQLCipher (M2 key broker).**
   The store holds hashed `task_class_key`s, confidence scores, token counts, role names, latencies,
   timestamps, and `model_id` — no message content. The dispatched security review showed that bare
   `sha256(request_text)` keys are preimage-searchable over a personal-assistant's low-entropy request
   corpus, so plaintext-at-rest is rejected: the store uses **SQLCipher via the M2 key broker** (reusing
   M4's SQLCipher binding), behind a single `_connect` factory. `task_class_key` is left identical to
   M7-a2's value (no keyed-HMAC fork) so telemetry escalations cluster on the same key the recipe store
   uses — SQLCipher-at-rest closes the enumeration threat without diverging the key. Timestamps are stored
   as **epoch-millisecond integers** (not TEXT) to make range queries format-safe. The independence concern
   (decision 5) applies to the *guardrail* `TokenLedger`, which stores only counts + timestamps (no content,
   no enumeration surface) and stays plaintext/independent.

4. **Tier-aware cost model, not per-token dollars (brain.md flat-rate quota lock).** Cost is attributed by
   role tier: local roles = 0; subscription/teacher (`claude-cli` adapter) = quota-units counted against a
   ceiling; cloud roles (e.g. DeepSeek) = per-token micros via a small rate map. The constraint brain.md
   names is the shared subscription quota, not a dollar bill.

5. **M7-c's `TokenLedger` stays separate.** It is a spending *guardrail* with a hard-stop reliability
   requirement; the telemetry store is *observability* and may tolerate gaps. They read the same
   `ModelResponse.usage` independently. The guardrail must never depend on observability-store
   availability → no unification, no edit to M7-c.

## Consequences

- Two build specs: **OBS-a** (logging + `ObservabilitySink` Protocol + error capture + the Brain/distill
  taps — single writer of `brain.py`/`distill.py`) and **OBS-b** (telemetry store + `TracingModelPort` +
  cost model + concrete `TelemetrySource` reader M7-c consumes). OBS-b depends on OBS-a's Protocol.
- M1-b (`brain.py`) and M7-a2 (`distill.py`) gain additive, default-`NullSink` constructor params + tap
  calls — backward-compatible (existing tests inject nothing → no-op).
- The concrete `TelemetrySource` imports M7-c's event types from `artemis.curiosity.gaps`; `stale_items()`
  ships with recipe staleness (from `RecipeStore` provenance) — chunk staleness is gated on an M3
  verified-at capability and deferred (documented).
- The `ObservabilitySink` Protocol carries **only non-content primitives** (`task_class_key`, `confidence`,
  `path`, exception object) — never `request_text` or a `RouteDecision`. The Brain computes `task_class_key`
  before the tap, so no sink can structurally persist message content. `CallTrace` carries optional
  `model_id` + `trace_id` columns from the outset to avoid permanent gaps in historical telemetry.
