# Sensitivity Ground Rules v1 — decision record

_Decided 2026-06-25 (planning, owner-led). Closes the **Source.sensitivity override (HIGH privacy gap)** flagged in continuation 7. This record feeds two durable homes (to author at session end): an **ADR-022 § Refinement** (whole-domain finance → content-grade) + a **build spec** (`Source.force_sensitive` + ground-rules policy + detectors). The ADR-029 RAG-compose enforcer is **unchanged** — it still gates on the sensitivity tag; we only changed *what gets tagged_._

## Decision summary

The privacy wall stays **tag-based** (enforcer gates on `chunk.sensitivity` / `fact.sensitivity`, not scope — `sensitivity.py:235`). What changes is the **tagging policy**: a three-layer model (deterministic ground rules → local classifier → ask-owner-and-remember), with the finance domain **narrowed from whole-domain to content-grade**.

### ⚠️ ADR-022 posture change (owner-approved)
ADR-022 currently treats **all finance** as sensitive (reason locally, never cloud). Owner narrowed this 2026-06-25: **only access/identity-grade content is hard-sensitive**; soft finance facts (spending patterns) are **general / cloud-OK**. Honest risks recorded: (1) **aggregation** — many soft facts compose into a profile; (2) classifier must reliably separate access-grade from soft, and **fail closed to sensitive** when unsure. Both accepted; fail-closed is mandatory.

This also **changes FIN-d**: the derived spending-pattern facts (`derive_finance_facts`) become **general**, so `push_finance_knowledge` must **not** force them sensitive. The `force_sensitive` lever now serves journal + health + email + access-grade content, not soft finance.

**FIN-d memory-path resolution (owner, 2026-06-25 — Option A):** `push_finance_knowledge` currently pushes to BOTH the knowledge index AND general memory. The soft-finance→general decision was about the **knowledge/RAG** path; the owner's locked rule **excludes finance from general memory** ("financial → Finance ledger only"). Resolution: **drop the memory `enqueue` entirely** — finance facts live in the Finance ledger + the knowledge/RAG index (general, retrieved on-demand via the now-wired retriever), never the bitemporal memory store. (Dropping only the `source_sensitivity` kwarg was insufficient — `memory/extraction.py` resolves `None`→classifier/fail-closed-sensitive, so the fact would still land in memory.) Orphans the `memory_queue` param + `MemoryQueuePort` + `manifest.py` wiring → cleaned up. Captured in the spec Task 6.

## Ground Rules v1

### 🔒 Hard-sensitive — auto-lock, never cloud

**By source/domain** (producing module sets `force_sensitive=True`; no content scanning):
- **Journal / personal notes** — whole-domain
- **Health / medical** — whole-domain (fail-closed default; owner indifferent → safe default chosen)
- **Email content** — whole-domain (keeps the locked "email stays local" owner-rule; flaggable to relax to classify later)

**By content** (detected in *any* source — upgrades that document to sensitive):
- Credentials/secrets: logins, passwords, OTPs, CVV, full card/account numbers
- **Account/card numbers exposing more than the masked tail** (> last-4 digits) → sensitive; masked `•••• 1234` is fine
- **Government IDs (NRIC/passport), DOB, home address**

### ☁️ General — cloud-OK (not auto-locked; classifier/ask decides if ambiguous)
- Soft finance: spending patterns, subscriptions, category totals
- Account balances / net worth
- Individual transactions (merchant + amount + date)
- Institution names tied to owner ("banks with DBS")
- General knowledge: web pages, public docs, files

### 🤔 Fallback — the "ask me" tail
Uncovered content → local classifier, **precision-first**. Unsure, or a *partial* access-grade signal → **fail closed to sensitive + ask owner**. Owner's answer **graduates into a new ground rule** (`policy.json`), so it stops asking that case.

## Mechanisms (how it automates)

| Rule type | Mechanism | Nature |
|---|---|---|
| Domain rules (journal/health/email) | `Source.force_sensitive=True`, set by the module | deterministic, zero scanning |
| Content rules (card/ID/DOB/address) | **deterministic detectors** — Luhn (card), NRIC checksum, regexes — + classifier backup, **fail-closed** | code first (un-foolable), model backstop |
| Ask + remember | owner-review surface (reuses M7-b needs-review pattern); answers → new `policy.json` rules | human-in-loop, shrinks over time |

- **The lever:** `Source.force_sensitive: bool` (A′ — one-directional; callers may only *upgrade* to sensitive, never assert general). Mirrors the memory port's `source_sensitivity`.
- **In `IngestPipeline.ingest`:** if `source.force_sensitive`, hard-set `document.sensitivity = "sensitive"` and **skip** `_classify_source()`; else classify as today.
- **Ground rules home:** `RuntimeConfig` / `policy.json` (X3 layer) — declarative, owner-tunable, no redeploy.
- **Hard detectors are plain code, not an LLM** — deliberately, so the highest-value items (full card/ID numbers) are caught by the layer that **cannot be prompt-injected**. The LLM classifier is the backstop for nuance, not the front line.

## Cross-link — injection is a *separate* wall (not handled here)
Sensitivity tagging stops data leaking **out**; it does nothing against malicious instructions getting **in**. Prompt-injection defense lives in `src/artemis/untrusted/` (DR-a quarantine: spotlight markers + unicode/zero-width scrub + toolless powerless reader + `flagged_injection`). Two coverage holes fold into today's other items:
- **Item #3** — `GmailMemoryExtractor` checks `parse_failed` but not `flagged_injection`.
- **Item #2** — knowledge ingestion (web/file → RAG) does not yet route through the quarantine; retrieved chunks composed into a cloud prompt are untrusted text and need spotlighting.

## To author at session end
1. **ADR-022 § Refinement 2026-06-25** — whole-domain finance → content-grade; record the two accepted risks + fail-closed mandate.
2. **Build spec** — `Source.force_sensitive` + `IngestPipeline` branch + ground-rules `policy.json` schema + deterministic detectors (Luhn/NRIC/regex) + classifier integration + ask-and-graduate surface. Amend FIN-d (`push_finance_knowledge` stops forcing soft facts sensitive).
