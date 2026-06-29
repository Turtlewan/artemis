# Anti-Hallucination Answer Layer — Design Discussion (2026-06-29)

_Knowledge-core quality lane, thread **C** (BACKLOG "Anti-hallucination brain invariants"). Companions:
thread A (`query-shape-retrieval-design-2026-06-29.md`), thread B
(`supersession-recency-grounding-design-2026-06-29.md`). Discussion only — not a spec. Absorbs the
cross-document contradiction detection deferred from A and B._

## The problem

The **main brain answer path** (`brain._rag_messages`) has only the spotlight *injection* defense — no
faithfulness discipline. It hands the model `Retrieved context: {spotlighted}` + the question and lets it
answer freely: no gap-tagging, no citation requirement, no claim-audit. The **deep-research engine
(DR-c)** already proves the grounded-synthesis pattern locally (constrained `{answer, claims}` schema,
imperative-stripped claim extraction, "synthesise only factual claims from these safe extracts") — but
only on the research path. Thread C brings that discipline to the everyday answer path, tiered by cost.

## The design — tiered rigor (Decision C1 = c)

Four sub-capabilities, one shared mechanism (grounded synthesis + claim-audit): gap-tagging · citation
discipline · claim-audit · cross-document contradiction. Split into two tiers:

**Cheap floor — always on, dev-buildable now, DETERMINISTIC (no model dependency):**
- **Gap-tagging on empty/thin retrieval** — if retrieval returns zero chunks/facts (or below a relevance
  threshold), the answer layer itself forces a `[MATERIAL GAP]` notice rather than trusting the model to
  admit it. Plus a prompt instruction to tag gaps mid-answer.
- **Citation-presence validation** — instruct the model to cite `[chunk_id]` inline; post-generation,
  parse the answer for `[chunk_id]` tokens and verify each references a chunk actually in the provided
  context. A cited id NOT in context = a hallucinated citation → flag/strip or surface a warning.
- **Honest scope:** this floor catches (i) thin/empty evidence and (ii) invalid/hallucinated citations.
  It does NOT catch a confident *uncited* fabrication — that needs the model audit tier below.

**Heavy tier — PARKED FOR THE MAC, escalated only when warranted:**
- **Model-driven claim-audit** — reuse DR-c's grounded-synthesis: extract each claim, verify it against
  the retrieved evidence, drop/flag unsupported claims.
- **Cross-document contradiction detection** — compare retrieved candidates (and recency, from thread B)
  for conflict; surface the newest / flag disagreement. This is the deferred A+B piece.
- **Escalation triggers** — high stakes (answer will drive an action / GATE), thin or conflicting
  evidence, or owner request. Reserved for the few answers that warrant a second model pass.
- **Why Mac:** the audit pass is only trustworthy with the stronger Mac model, and per-answer second
  passes want the Mac's compute. The escalation seam is reserved now; the tier lands at Mac bring-up.

## Decision locked
**C1 — (c) tiered, heavy tier Mac-parked.** Deterministic gap-tagging + citation-presence validation as
the always-on floor (dev-buildable, no model reliance); model-driven claim-audit + cross-document
contradiction as a Mac-gated escalated tier behind a reserved trigger seam.

## Substrate readiness
- **Ready / proven:** SPOTLIGHT injection defense on the answer path; DR-c grounded-synthesis +
  constrained schema + imperative-strip (lift/share for the escalated tier); `[chunk_id]`-tagged context
  already in `_rag_messages` (citation-presence check can parse it directly).
- **New (dev floor):** the deterministic gap-tag-on-empty + citation-presence validator + cite-inline
  prompt instruction; a relevance threshold for "thin" retrieval.
- **New (Mac tier):** generalize DR-c grounded-synthesis to the main path behind an escalation trigger;
  cross-document contradiction comparator (uses thread-B recency dates).

## Rough spec breakdown (for when greenlit — NOT specced yet)
1. **deterministic answer-layer floor** — gap-tag-on-empty/thin + cite-inline instruction +
   citation-presence validator in `_rag_messages`. Dev-buildable, fake-testable, no model dependency.
2. **(Mac) escalated claim-audit + cross-doc contradiction** — generalize DR-c grounded synthesis behind
   an escalation trigger; contradiction comparator over recency-dated candidates. Mac-gated.

## Lane status after C
All three knowledge-core quality threads now DESIGNED (A query-shape · B recency · C anti-hallucination).
Each has a dev-buildable slice + clearly marked Mac-gated tails; none specced yet. The cross-document
contradiction detection deferred from A and B has its home here (C, Mac tier).
