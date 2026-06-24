# ADR-029 — Sensitivity ingestion gate: tag-at-ingestion, enforce-at-RAG-compose (privacy wall for retrieved/recalled context)

- **Status:** **Accepted** — 2026-06-23 (owner + planning). Implements the "gate at ingestion" named but not designed in ADR-022 § Refinement 2026-06-22.
- **Date:** 2026-06-23
- **Deciders:** owner + planning
- **Relates:** ADR-022 (model/runtime hybrid privacy policy — this is its ingestion-gate half) · ADR-007 (knowledge layer — M3-a ingestion / M3-b retrieval the gate amends) · ADR-009 (untrusted-content / quarantine — the *orthogonal* axis) · ADR-004 (memory — recalled facts are a gated context source) · ADR-012 (GATE staging — considered and **not** used for the release path) · `brain-sensitivity-routing` (the conversation gate this extends).

## Context

The hybrid privacy policy (ADR-022) keeps sensitive reasoning local and routes the rest to Codex/cloud. `brain-sensitivity-routing` (the conversation gate) classifies **only the typed `request_text`** and routes the responder role accordingly. It explicitly defers everything else: *"when M3 injects retrieved context, that context is gated by the separate ingestion-gate spec."*

The gap: once the knowledge layer is live, the cloud-bound prompt is **request + retrieved chunks (M3-b) + recalled facts (M4-c)**. The conversation gate covers term 1 only. A perfectly innocent ("general") typed request can pull a sensitive document or memory into context, and *that* is what reaches the cloud — unseen by the request-text gate. This ADR closes that hole.

ADR-022's refinement named the mechanism — "a cheap LOCAL model, run at INGESTION" — and a phasing ("detect-and-drop" now → "detect-and-route-local" later), but did not design the seam, the enforcement posture, or reconcile "drop" against keeping the owner's own data. This ADR does.

**Interpretation fixed here — "detect-and-drop" = drop from the *cloud-bound context*, never from the corpus.** Sensitive content is still ingested and retained in the already-encrypted, already-local, behind-the-M2-wall corpus; it is simply never placed into a cloud prompt. Dropping it from the corpus would discard the owner's own sensitive data and defeat the hybrid (whose point is *local* handling, not discarding). ADR-022's "now vs later" phasing is therefore only about *how good the local handler is* (base 4B now → distilled `sensitive_reasoner` after the Mac), not about whether the content is kept.

## Decision

A three-stage **tag-at-ingestion → carry → enforce-at-the-cloud-boundary** architecture, built integrally with the knowledge→reasoning path so the wall exists from the first line and is never retrofitted onto a running retrieval path.

```
PRODUCE (at ingestion)        CARRY (rides provenance)      ENFORCE (at the cloud boundary)
classify each doc/email/      sensitivity field on:         RAG-compose seam:
fact on-box → stamp a    ───▶  · RetrievedChunk (M3-b)  ──▶  retrieve + recall → assemble
`sensitivity` tag              · recalled fact (M4-c)         → run enforcer → route:
(reuses the SAME classifier                                   · any sensitive item present
brain-sensitivity-routing                                       → filter it out of the cloud
builds — no second model)                                       prompt; answer local-or-on-
                                                                remainder
                                                              · surface the held-back items
                                                              · owner may release to cloud
```

### 1 — Producer (tag at ingestion)
A **per-source** classification (one classify per document / per email / per fact — **not** per-chunk, which would be N× the local-model calls and brutal during a months-long Gmail backfill on the 8 GB dev box). The tag propagates to every chunk/row of that source.
- Reuses the **exact `SensitivityClassifier` + `sensitivity_classifier` role + taxonomy** from `brain-sensitivity-routing` (finance / health / journal / memory / credentials / identity), **fail-closed** (unsure → sensitive). No second resident model.
- Representation: a `sensitivity: Literal["general","sensitive"]` field **plus a reserved nullable `category`** column (for future routing to a specialized reasoner and for owner transparency).

### 2 — Carrier (rides provenance — nearly free)
The tag is one more field on shapes that already carry provenance: `RetrievedChunk` (M3-b materializes the LanceDB row — surfacing the column is ~a line) and the recalled fact (M4-c).

### 3 — Enforcer (at the RAG-compose seam — the missing call-site)
The true blocker was never M3-b (already a frozen `ready` spec whose security FLAG already reserves *"no sensitive chunk to cloud … the consumer enforces it; M3-b does not"*) and never the hardware. It is that **nothing wires retrieval/recall into the responder prompt yet** — the "RAG-compose" step is unspecced. The enforcer lives at that consumer seam, as an **extension of `sensitivity.py`** (classifier + router in one home), composing with the conversation gate:

> **route to cloud only if** the request is general **and** no retrieved chunk and no recalled fact is tagged sensitive (and not released). Any sensitive item in the assembled context → that item is filtered from the cloud prompt; if the request itself is sensitive, the whole turn stays local.

### Enforcement posture — filter-by-default + per-item surface + one-time release
When a cloud-eligible ("general") query assembles context containing sensitive items:
1. **Filter** — the sensitive items are stripped from the cloud-bound prompt; the cloud answers on the general remainder.
2. **Surface, per-item** — Artemis reports *what it held back* (listed individually), so the answer is never *silently* incomplete.
3. **Release — inline offer, non-blocking, audited.** The held-back items are offered inline ("say 'include the medical email' to redo with it"); the owner acts only to get the fuller answer. **Releases go through an inline offer, NOT the GATE staging subsystem** (ADR-012) — conversational flow matches the single-owner appliance; a blocking approval on every sensitive-context hit is too heavy. **Every release is written to the activity/audit log** so the egress is recorded without a hard gate. Release is **one-time per query** — it never silently re-tags the item as general (a future "always allow this source" is reserved, not built).

### Orthogonality — sensitive ≠ untrusted (load-bearing clarity)
This adds a **third, independent axis** to the existing two boundaries (ADR-009): *untrusted* (attacker-controlled content → spotlight/quarantine before any LLM) and *at-rest encryption* (the M2 wall). **Sensitivity** asks a different question — *is this private-to-the-owner → keep off cloud.* A medical bill is both untrusted and sensitive; a newsletter is neither. The gate adds the sensitive axis **without touching the quarantine machinery**; the classifier reads raw content on-box (loopback-guarded, like the conversation gate) and emits only a label.

## Build wave (all dev-box-buildable + end-to-end testable against real Ollama models; integral, in order)
- **0 — foundation (in flight):** `brain-sensitivity-routing` builds `SensitivityClassifier` + the request→role gate. Proceeds **as-is**; the gate builds on it and reuses its classifier.
- **1 — producer amendments:** `M3-a` (classify each doc → tag on Document/chunk/LanceDB row), `M8-b1` (tag each signal email + its extracted memory fact), `M4-b` (facts inherit source-derived sensitivity; note owner-rules already exclude finance/health from memory, so the residual sensitive memory is journal/credentials/identity).
- **2 — carrier:** `M3-b` surfaces the tag on `RetrievedChunk`; `M4-c-1` surfaces it on recalled facts.
- **3 — enforcer + seam (new spec):** RAG-compose-with-gate — retrieve+recall → assemble → enforcer (filter + route) → responder/responder_cloud → surface held-back + inline release + audit. Enforcer logic extends `sensitivity.py`.

**Mac-gated tail:** only the later quality upgrade (distilled `sensitive_reasoner`) — a separate ADR-022 phase. The gate's logic and correctness are entirely dev-box territory.

## Consequences
- The privacy wall now covers **all three** cloud-bound prompt terms (request + retrieved + recalled), not just the typed request. There is never a window where retrieval can reach the cloud ungated, because the gate is built integrally with the RAG path rather than bolted on after.
- One classifier serves three call-sites (conversation gate, ingestion tagging, enforcer) — `sensitivity.py` is the single home; no second resident model on the 8 GB box.
- Ingestion cost: one extra local-model call per source document/email/fact at write time (per-source, not per-chunk). Heaviest during the bounded Gmail backfill; incremental thereafter.
- Cloud answers on filtered context may be *incomplete* — accepted, because incompleteness is **always surfaced** (per-item) and the owner holds the one-time release switch.
- Accepted residual (same as the conversation gate): a 4B classifier is not fully injection-proof. Single-owner appliance; the owner is not adversarial to themselves. Hardening (canary / second pass) stays a reserved follow-up.

## Alternatives considered
- **Drop sensitive content from the corpus entirely** — *rejected*: discards the owner's own data; defeats the hybrid's local-handling purpose.
- **A separate local-only corpus** that sensitive content is sorted into — *rejected*: the existing corpus is already local-at-rest behind the M2 wall and gated at the cloud boundary; a second store buys nothing.
- **Per-chunk classification** — *rejected*: N× the local-model calls; cost-prohibitive at backfill. Per-source with whole-source tagging is fail-safe and cheap.
- **Whole-query-local on any sensitive hit** (no filtering) — *rejected*: needlessly downgrades the general majority of a query to the weaker local model.
- **Release via GATE staging (ADR-012), blocking** — *rejected* as the default: too heavy for an interactive turn on a single-owner appliance; the inline-offer-plus-audit synthesis gives conversational flow with a recorded egress.
- **Defer the enforcer to whenever M3-b is built** — *rejected*: M3-b is already specced and its contract already reserves the gate; the missing piece is the RAG-compose seam, which is dev-box-buildable now. Building the wall integrally avoids an ungated window.

## Parked / next
- Release-delivery is inline; a future **"always allow this source"** persistent re-tag is reserved, not built.
- Classifier **injection hardening** (canary token / second validation pass) — reserved follow-up, shared with the conversation gate.
- The distilled `sensitive_reasoner` quality upgrade — Mac/training-gated (ADR-022 § Refinement phasing).
- The `category` column is written but unconsumed in v1 (reserved for specialized-reasoner routing + owner transparency).
