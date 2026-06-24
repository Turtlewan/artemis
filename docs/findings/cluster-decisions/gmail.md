# Cluster Decisions — GMAIL (open design forks)

_Decision-resolution pass before build specs. Scope: Gmail's own functions, data, and behaviour.
Cross-spoke reaction wiring (email→calendar/task/finance) → Integration agent; the visual/screen
layer → UI agent. Sources read: `docs/technical/modules/gmail.md`, `docs/changes/M8-a*`,
`M8-b1-gmail-connector.md`, `M8-b2-gmail-urgency-hook.md`, `docs/owner-rules/3-email-triage.md` +
`00-INDEX.md` + `7-cross-module-reactions.md`, ADR-011, `docs/status.md`._

**Key framing fact:** the M8-b1 (connector) and M8-b2 (urgency hook) specs are marked `status: ready`
and were frozen on **2026-06-11**. The owner-rules email-triage capture happened **2026-06-19** — i.e.
AFTER the specs froze. So several owner requirements captured on 06-19 are **NOT yet in the ready
specs**. Those are the genuine open decisions below: each needs an owner judgment, then a spec
amendment, before build.

Ordered by importance (build-blocking / behaviour-changing first).

---

## D1. Stage-1 urgency gate — widen beyond the Gmail "Important" marker? (BUILD-BLOCKING)

**Context.** M8-b2 Stage-1 (the frozen ready spec) requires `unread AND Gmail-IMPORTANT AND
category∈{PRIMARY,UPDATES}` before *anything* reaches the scorer. The owner's notify policy
(owner-rules, 06-19) is **topic-driven**: notify ONLY on (1) legal matters, (2) payment warnings
(late/overdue/fraudulent). Legal notices and first-contact fraud/payment mail are *frequently NOT
flagged Important by Gmail* (unknown sender, first contact) → today's hard Important gate would
**drop exactly the mail the owner most wants**. Flagged twice (owner-rules §⚠️ flag 2 + 00-INDEX
spec-gap 2) as "needs a design decision, not just a value." The current spec does not implement any
widen.

**Options.**
- **A — OR-in topic/keyword + VIP signals.** Admit a candidate if `unread AND category∈{PRIMARY,UPDATES}`
  AND (`Gmail-IMPORTANT` **OR** subject/snippet matches a legal/fraud/payment-warning keyword set **OR**
  sender∈VIP). Trade-off: catches the owner's true-positives; adds a small deterministic keyword pass in
  the LLM-free `check_ref` (cheap), but keyword lists need tuning and can over-admit (more LLM scoring
  calls).
- **B — Keep Important-only (status quo).** Trade-off: simplest, lowest LLM cost, but knowingly drops
  legal/fraud first-contact mail — contradicts the captured policy. Effectively rejected by the owner's
  own flag.
- **C — Drop the Important gate entirely; rely on the Stage-3 LLM rubric.** Score all unread
  PRIMARY/UPDATES. Trade-off: never misses, but scores far more mail per scan (cost on the Mini) and
  leans entirely on the LLM rubric for precision.

**Recommended default: A.** It directly honours the captured topic-driven policy while keeping the
cheap pre-filter that bounds LLM cost — the owner already wrote the keyword themes (legal · fraud ·
payment-warning · interviews) and the VIP list (Ashley/Debby). Keyword match stays deterministic so
`check_ref` remains LLM-free.

**UI implication:** none directly (headless hook). Downstream notification copy is UI/notify-rubric,
already set.

---

## D2. Bank-transaction senders — exclude from urgency candidates now, or defer to Finance? (BUILD-BLOCKING for correctness)

**Context.** Owner explicitly uses UOB / Standard Chartered / DBS transaction emails as **Finance
tracking input, NOT notifications** (owner-rules §⚠️ flag 1). These senders are PRIMARY/UPDATES and may
carry the Gmail-Important marker, so under D1-A they could push an alert the owner does not want. The
*routing to Finance* is Integration-agent territory; the open Gmail-side decision is narrower: **does
M8-b2 carry a sender-exclusion list so bank mail never becomes an urgency candidate**, independent of
whether Finance exists yet?

**Options.**
- **A — Add a `URGENCY_SENDER_EXCLUDE` set in M8-b2 now.** Bank/card-notification senders are filtered
  out at Stage-1. Trade-off: small, self-contained, immediately stops the false alerts; the list is
  owner-tunable and lives with the urgency hook. Works even before Finance is built.
- **B — Defer entirely to Finance.** Trade-off: clean separation, but until Finance exists (a *later*
  spoke — needs M8-b/M3/M4/M6/M7/CLIENT) the owner gets bank-transaction alerts they explicitly don't
  want. Leaves a known-bad gap for the whole intervening period.
- **C — Suppress at Stage-3 rubric only** ("stay silent on routine bank confirmations" — already in the
  owner's rubric text). Trade-off: zero new code, but still spends an LLM scoring call per bank email and
  relies on the rubric not misfiring.

**Recommended default: A.** Cheap, deterministic, and closes the false-alert gap immediately without
waiting on the Finance spoke. The exclusion list is the same owner-data the Finance ingest will later
*include* — capture it once.

**UI implication:** none.

---

## D3. VIP / sender-priority model — static list vs memory-derived vs hybrid (BUILD-SHAPING)

**Context.** The frozen M8-b2 derives "known senders" dynamically via `build_known_senders` (memory
recall over "known contact person name") — purely inferred, no explicit list. The owner-rules capture
gives a concrete VIP list: **Ashley, Debby** (exact addresses TBD on Mini), and notes importance is
*also topic-driven, not only sender*. Open question: how does the VIP list get represented — and does
it just *boost* (Stage-2, current behaviour) or also *admit* (feed D1's widen)?

**Options.**
- **A — Explicit static VIP set + memory-derived set, unioned.** A small owner-config `VIP_SENDERS`
  (Ashley/Debby) merged with the memory-recall set. Trade-off: deterministic guarantee the named VIPs
  always count, plus memory's broader coverage; needs one new config knob.
- **B — Memory-only (status quo).** Trade-off: zero new config, but VIP status depends on memory having
  ingested those contacts first (cold-start gap) and the owner can't directly pin a VIP.
- **C — Static-only.** Trade-off: predictable but loses the "recurring contact auto-boost" the memory
  path gives for free.

**Recommended default: A (hybrid).** Guarantees the named VIPs without losing memory's auto-coverage;
the owner already supplied the explicit list, so honour it deterministically. Tie to D1: VIP-sender
should also be an *admit* signal (Stage-1), not only a Stage-2 boost.

**UI implication:** minor — a VIP list is an owner-editable setting; surfacing/editing it is a later
client-settings concern (UI agent), not build-blocking.

---

## D4. Outbound send / reply capability — wanted now, or stays deferred? (SCOPE)

**Context.** Send is consistently **deferred** across ADR-011 §5, gmail.md (Deferred/future), and
M8-b1 (read-only scope only). The prompt asks whether the owner now wants it. It is a real scope fork:
send needs the `gmail.send` scope + the M7-b write-gating path + the CLIENT Review screen (the
"unlock" milestone). No source shows the owner asking for it yet.

**Options.**
- **A — Keep deferred (status quo).** Trade-off: matches every locked doc; v1 stays a pure read-only
  mirror with zero destructive blast radius; revisit post-CLIENT. Lowest risk.
- **B — Add send as a gated `TAKES_ACTION` recipe now.** Trade-off: unlocks reply/compose, but pulls
  CLIENT + GATE + write-scope into the Gmail critical path — a large scope increase the build order
  deliberately sequences *after* the first spoke wave.
- **C — Draft-only (compose a draft via `gmail.compose`, never send).** Trade-off: a middle ground —
  owner reviews/sends manually in Gmail; needs a broader scope than readonly but no auto-send risk.

**Recommended default: A — keep deferred.** Nothing in the corpus signals the owner wants it, and the
locked ADR sequences write-enabled spokes after the CLIENT unlock. Confirm explicitly so it's a
*decided* deferral, not an assumed one. (If the owner says "yes, I want it" → this becomes a new
post-CLIENT spec, not a v1 amendment.)

**UI implication:** large IF pursued — send routes through the CLIENT Review/approval screen (UI
agent). Not for v1.

---

## D5. Write actions on the mailbox — label / archive / mark-read / star (SCOPE)

**Context.** gmail.md and M8-b1 ship **no** modify/label/archive/trash — these need `gmail.modify`
and the write-gating path; listed under Deferred. The owner's auto-tagging requirement (owner-rules
06-19) is about *Artemis-internal* tags (precision-first, needs_review), NOT writing labels back into
Gmail. Open question: does the owner want Artemis to manage the *Gmail* mailbox (auto-archive promos,
mark-read, apply Gmail labels), or is internal-only awareness enough for v1?

**Options.**
- **A — Read-only mirror, internal tags only (status quo).** Trade-off: matches ADR-011's
  single-direction-of-truth posture (Gmail = truth, no write-back); the owner's tagging happens in
  Artemis's own store, never mutating Gmail. Simplest, safest.
- **B — Add reversible mailbox writes (mark-read / archive / label) as auto-safe recipes.** Per the
  owner's `classify_safety` internal-reversible-tier gap (00-INDEX gap 6), label/archive are
  internal/reversible — could be auto-enabled without the external-effect gate. Trade-off: useful
  inbox-zero automation, but adds `gmail.modify` scope (larger blast radius) and a write path the v1
  read-only mirror deliberately avoids.

**Recommended default: A.** Keep v1 read-only; internal tagging satisfies the captured requirement
without a write scope. Revisit B alongside D4 post-CLIENT if the owner wants active inbox management.

**UI implication:** none for A.

---

## D6. Backfill window & attachment cap — accept defaults? (TUNABLE, low-stakes)

**Context.** Owner-rules table leaves "Your value" blank for: backfill window (default **12 months**),
attachment size cap (default **10 MB**), max emails scored per scan (default **10**), notification
dedup (**once/day**). Blank = accept default per the capture convention. Surfaced only to confirm the
owner doesn't want to override (e.g. a longer backfill for a richer initial knowledge base, or a
larger attachment cap).

**Options.**
- **A — Accept all defaults (12mo / 10MB / 10-scored / once-day).** Trade-off: matches the capture;
  conservative on Mini cost/storage. Likely fine.
- **B — Lengthen backfill (e.g. 24–36 months) for a richer cold-start corpus.** Trade-off: more
  knowledge on day one; heavier one-time backfill pass + more storage/embed cost on the Mini.
- **C — Raise attachment cap (e.g. 25 MB).** Trade-off: catches larger PDFs/decks; more parse cost +
  larger untrusted-input surface.

**Recommended default: A — accept defaults.** All are env-configurable later (`ARTEMIS_GMAIL_*`), so
this is reversible and not build-blocking; only flag if the owner has a strong cold-start preference.

**UI implication:** none (env/config knobs).

---

## D7. Confidence-floor / `needs_review` state on Gmail category tagging (CROSS-CUTTING, confirm scope)

**Context.** The owner's precision-first auto-tagging requirement (06-19) names **Gmail categories** as
one of the auto-taggers that should get a `needs_review` state + confidence floor (00-INDEX gap 5:
"below floor → no tag + needs review, never mis-tag"). But Gmail's category is *Gmail's own label*
(deterministic, not an Artemis classifier) — so the floor may not apply to category mapping at all, and
instead applies to any *Artemis-side* classification layered on top. Open: does Gmail need a
`needs_review` path, or is the gap really about other taggers (memory/finance/productivity)?

**Options.**
- **A — No Gmail-side floor needed; `categorize()` is deterministic Gmail-label mapping.** Trade-off:
  correct if Gmail categories are taken as ground truth (they are, in the spec); the floor requirement
  lands on the genuinely-probabilistic taggers elsewhere. Removes Gmail from the gap-5 scope.
- **B — Apply the floor to any Artemis urgency/topic classification** (e.g. the D1 keyword/topic
  match → "needs review" when ambiguous rather than silently admitting/dropping). Trade-off: extends
  precision-first to the urgency path; small added state on the hook.

**Recommended default: A (with a nod to B for the D1 topic-classifier).** Gmail's own category is
deterministic — no floor. IF D1 adds an Artemis topic-classifier, that specific classifier should carry
the floor; the raw Gmail category should not. Confirm which surface gap-5 actually targets so it isn't
mis-applied to deterministic label mapping.

**UI implication:** a "needs review" state, if built, surfaces in the client triage view (UI agent) —
not build-blocking here.

---

## Appendix — already resolved / locked (NOT re-asking)

- **Read-only mirror posture** — LOCKED (ADR-011 §5; gmail.md Decisions).
- **Split-by-depth ingestion** (metadata-all + full-body/attachments/memory for PRIMARY/UPDATES/FORUMS
  only) — DECIDED 2026-06-09.
- **Urgency candidate set = {PRIMARY, UPDATES}, Forums excluded** — Decision D2 2026-06-11 (in spec).
- **3-stage funnel structure** (Important+unread → memory-boost → quarantined LLM scoring → batched
  briefing) — DECIDED; mechanism frozen.
- **Quarantine / untrusted boundary** (raw mail never reaches the scoring/privileged model; bodies
  spotlighted; subject/snippet dropped from payloads) — FROZEN invariant (Seam 7/B4).
- **History-API incremental sync, OAuth/token mechanics, `gmail.readonly` least-privilege scope** —
  FROZEN invariant (owner-rules §🔒).
- **Notify rubric** (notify=legal+payment-warning only; important≠notify; stay-silent list) — CAPTURED
  in owner's voice (owner-rules §Prompt text); the *rubric text* is settled. The OPEN part is the
  Stage-1 gate that decides what reaches the rubric (→ D1).
- **Memory: financial + health facts EXCLUDED from memory entirely** (financial → Finance ledger) —
  CONFIRMED 06-19.
- **Cross-module email reactions** (bill→task, flight→travel playbook, interview-prep, Ashley CRM,
  charge↔receipt linking) — these are Integration-agent scope (owner-rules file 7), not Gmail-function
  decisions; listed here only to mark them out-of-scope for this cluster.
- **Externalized runtime-config layer vs code constants** — a project-wide open question (00-INDEX
  §Deferred architecture question + status.md), not Gmail-specific; capture works either way.
