# Owner Rules — Capture Index

_Captured on Windows (planning machine), pre-Mini. On the Mac Mini these values become each
module's defaults / prompt text when the coder builds the spec. This folder is **owner-policy
data**, not code — it does not touch the frozen ~61-spec corpus._

## Why this exists
Artemis's automation (the M6 heartbeat firing hooks + per-spoke triage) is governed by ~20 specs
whose owner-personal "rules" currently ship as **generic placeholder defaults** buried in code
constants and LLM prompt strings. This folder captures the owner's *real* values now, so Mini
move-in is "unpack and go" instead of configuring ~40 knobs from scratch against live behaviour.

## The six surfaces
| # | File | Feeds specs | Capture status |
|---|------|-------------|----------------|
| 1 | `1-proactivity.md` | M6-a/b/c + **all hook schedules** (CAL-c, M8-b2, M8-d-c1) | ✅ quiet+posture+full schedule |
| 2 | `2-scheduling.md` | CAL-a, M8-d-b | ✅ tz + hours + morning focus |
| 3 | `3-email-triage.md` | M8-b1, M8-b2 | 🟡 VIPs + rubric |
| 4 | `4-memory.md` | M4-a/b/c-1/c-2 | ✅ remember + A.U.D.N. + floor (decay→Mini) |
| 5 | `5-safety-policy.md` | M7-a2/b/c, GATE-a, DR-b | ✅ boundary + tagging + cloud (caps→M7-c) |
| 6 | `6-productivity.md` | M8-d-a/b/c1/c2 | ✅ defaults accepted |

## How to read each file
- **Tunable rules** table — `Rule | Default | Lands in | Your value`. Fill the last column
  (blank = accept default). ⭐ = highest-value / most owner-specific / most likely to be re-tuned.
- **Prompt text (your voice)** — free-text blocks where the rule *is* an LLM prompt. Write how you
  want Artemis to think/talk; the coder drops it in verbatim.
- **🔒 Frozen invariants** — security/mechanics that are **NOT** owner-tunable. Listed for awareness
  only; do not edit. Every cluster scan independently flagged these as load-bearing.

## One-home-per-rule
Some knobs are shared across modules and captured **once**:
- **All hook schedules** (when Artemis may interrupt you) → consolidated in `1-proactivity.md` §Hook schedule.
- **Recipe graduation threshold N≥2** (M7-b `Promoter.threshold`, reused by M8-d-c2 capture) → `5-safety-policy.md`.
- **Focus-block duration / scheduling window** → `2-scheduling.md` (referenced by M8-d-b).

## Deferred architecture question (not blocking)
Whether these captured values become a real **externalized runtime-config layer** (owner-editable
without code edits) or stay as **code constants the coder transcribes** is an open decision — see
status.md Open Questions. Capture works either way; this just changes how rules are re-tuned later.

## ⚠️ Spec gaps surfaced (for planning) — the real prize
These are owner-requirements the current specs don't yet support. Apply as spec amendments when each
module is built (most are Mini-gated). Each cites its target spec(s).

1. **`working_days` field** (CAL-a `CalPrefs`) — "weekends off." `find_time` + free-gap hook must
   respect days, not just hours (today they'd offer Saturday slots).
2. **Gmail Stage-1 gate widen** (M8-b2) — admit topic/keyword (legal / fraud / payment-warning) +
   VIP-sender (Ashley/Debby) signals **regardless of Gmail's IMPORTANT marker**, which first-contact
   legal/fraud mail often lacks → today they'd be dropped before scoring.
3. **Bank-email → Finance routing** (M8-b2 + Finance) — exclude UOB/SCB/DBS transaction senders from
   urgency candidates (never alert); route to Finance ingest.
4. **Finance reconciliation** (FIN-*) — `transaction.type` (purchase/refund/transfer/settlement) +
   exclude transfers/settlements from spend totals (else CC-bill-payment double-counts). ✅ already
   written into `finance.md`.
5. **`needs_review` state + confidence floor on ALL auto-taggers** (M4-b, Gmail categories, M3
   ingestion, Productivity areas, Finance categorization) — precision-first: below floor → no tag +
   "needs review", never mis-tag. Resolves M4-b's missing confidence cutoff.
6. **`classify_safety` internal-reversible tier** (M7-b) — auto-enable internal/reversible data
   actions (tagging/filing), not only READ_ONLY/NO_DATA; gate external-effect (send/book/pay) only.
7. **Wake / event-triggered hook type** (M6-a/b + M8-d-c1) — new trigger class beyond cron/interval:
   a "good morning" wake intent → merged Morning digest; optional first-interaction-of-day detection
   (reuse M7-c `last_interaction_at`); **per-day-of-week gating** (Weekend review = Saturday wake only).
8. **`preferred_focus_window`** (CAL-a + M8-d-b) — morning deep-work bias for time-block slot pick +
   free-gap focus-protect (defend morning gaps first), replacing earliest-slot.

## Elicitation log
_Surface-by-surface; updated as values are captured._
- **2026-06-19 — daily rhythm anchor.** Timezone = **Asia/Singapore (SGT, UTC+8)**; wake ~07:15,
  sleep ~23:30–00:00, drifts day-to-day. Derived (proposed, pending confirm): quiet-hours
  `23:30→07:15` (S1), curiosity idle `00:00→07:00` (S5). Timezone standardization is a real change —
  several specs default `UTC`. Surfaces 1/2/5 now 🟡.
- **2026-06-19 — work rhythm.** Working hours **09:00–18:00, Mon–Fri**; no meetings outside that;
  weekends off. Surfaced a gap: `CalPrefs` has no `working_days` field (find_time would suggest
  weekends) — small spec addition to confirm. Buffer/focus-block/reminder left at default.
- **2026-06-19 — email triage.** VIP senders Ashley + Debby; notify ONLY on legal OR payment
  warnings (late/fraudulent); importance is topic-driven (interviews, faulty txns). Two flags: (1)
  bank emails (UOB/SCB/DBS) → **Finance tracking, not alerts** (cross-module, carry into finance.md);
  (2) M8-b2 Stage-1 Gmail-Important gate may drop legal/fraud emails — widen Stage-1 to topic/VIP
  signals. Both need a design decision (not just a value).
- **2026-06-19 — proactivity posture.** **Gentle nudges** (not alerts-only): all scheduled digest
  hooks ON; ad-hoc chatter filtered important-only. Two tuning flags: (1) briefing 07:30 + morning
  plan 08:00 overlap → merge or space; (2) hourly overdue nudge too frequent → 1–2×/day. Open:
  weekly-review day/time; which modules feed the briefing.
- **2026-06-19 — auto-tagging (owner requirement).** Tagging = AUTO (never gated) + **accurate**:
  confidence floor → **precision-first** (when unsure, NO tag + "needs review", never mis-tag) +
  always correctable + learns from corrections. Resolves the M4-b no-confidence-cutoff gap.
  ⚠️ Spec gap: auto-taggers need a `needs_review` state + floor check (memory, email, M3 ingestion,
  productivity areas, finance). Self-teaching autonomy boundary (auto-enable vs gate) still OPEN —
  tagging steered it toward auto-for-internal, but the external-effect line isn't confirmed.
- **2026-06-19 — memory: what to remember.** REMEMBER: important dates, project awareness +
  execution style, key people & dates (Ashley primary: birthday/anniversary/flights/events),
  commitments, goals, travel, vendors, standing logistics (non-financial). **EXCLUDE entirely:
  financial + health facts** (financial → Finance ledger only; never memory). Autonomy boundary
  CONFIRMED (auto internal-reversible incl. tagging; gate external-effect). Task list ≠ memory →
  Productivity (S6). Remaining S4: A.U.D.N. update rule (replace vs keep-both).
- **2026-06-19 — memory A.U.D.N. + cloud line + Finance reconciliation.** A.U.D.N. = cardinality
  default + **keep-both-when-unsure, dated** (bitemporal, never silent overwrite, no auto-delete).
  Cloud-teacher line: **local handles all email** (triage/summarize/extract — good enough; quality
  is a model-size tunable, verify on Mini); cloud only for general skills, never personal data.
  Finance double-count: owner case (CC bill payment vs purchase) → expanded `finance.md` with a
  `transaction.type` + transfers/settlements excluded from spend; receipt-vs-card-alert dedup already
  covered (L0–L4). Local model classifies; deterministic ledger reconciles; ambiguous → owner.
- **2026-06-19 — morning digest = WAKE-triggered (design gap #6).** Briefing + morning plan MERGE
  into one Morning digest, fired when the owner gets up (says "good morning" / first interaction),
  **not a clock time**. New requirement: M6 needs an **event/intent hook trigger** (today cron/interval
  only) + a "good morning" wake intent + optional first-interaction-of-day detection (reuse M7-c
  `last_interaction_at`). Overdue-nudge → ~daily (folded into digest). Reviews SPLIT: **Weekend
  review = Saturday wake** (day-gated, rides Sat digest); **Week-ahead = Sunday evening (~19:00)**.
  Wake-trigger (gap #6) must support per-day-of-week gating. Surface 1 ✅ complete.
