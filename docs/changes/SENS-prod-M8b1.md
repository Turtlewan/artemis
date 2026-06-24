---
spec: sens-prod-m8b1
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- amended for ADR-029 §1 (producer stage). AMENDS M8-b1 (Gmail connector). Per-source on-box
     sensitivity classification on each signal email + its extracted memory fact. Uses the SAME
     field contract canonicalised in SENS-prod-M3a. -->

# Spec: SENS-prod-M8b1 — tag signal emails (and their extracted facts) with `sensitivity` at ingestion

**Identity:** Classify each ingested signal email **once, on-box, per-source** via the existing `SensitivityClassifier`, stamping the canonical `sensitivity`/`category` fields (defined in SENS-prod-M3a) onto the email's ingested representation AND onto the memory fact extracted from it — the Gmail producer half of the ADR-029 wall.
→ why: see docs/technical/adr/ADR-029-sensitivity-ingestion-gate.md §1 · field contract in docs/changes/SENS-prod-M3a.md · reuses docs/changes/brain-sensitivity-routing.md classifier.

## Field contract (inherited from SENS-prod-M3a — do not redefine)

`sensitivity: Sensitivity` (`= Literal["general","sensitive"]`, fail-closed default `"sensitive"`) + `category: str | None = None` (reserved, `None` in v1 — the classifier returns only the label). Classification is per-source, on-box, fail-closed, via `SensitivityClassifier` from `artemis.sensitivity`. See SENS-prod-M3a § Canonical sensitivity field contract.

## Assumptions

- **brain-sensitivity-routing** complete: `artemis.sensitivity` exports `Sensitivity`, `SensitivityClassifier` (`async def classify(text) -> Sensitivity`), `SensitivityClassifierProtocol`. → impact: Stop (same classifier; no second model).
- **SENS-prod-M3a** complete (or co-built): the canonical `sensitivity`/`category` field contract is established; if the Gmail ingest path feeds the same `IngestPipeline` (M3-a) as documents, the per-source classify is ALREADY applied there — in that case this spec only ensures the **email-specific** ingest representations + the **extracted memory fact** carry the tag. If Gmail has its OWN ingest/extract path that does not route through `IngestPipeline.ingest`, this spec adds the classify call to that path. → impact: Stop (read M8-b1 to confirm whether signal-email ingestion reuses `IngestPipeline` or a Gmail-specific path; tag at the per-source boundary either way).
- **M8-b1** complete (the spec amended): the Gmail connector ingests signal emails (per `SIGNAL_CATEGORIES`) and extracts memory facts from them. The email's ingested row + the extracted `ExtractedFact` are the two surfaces that gain the tag. → impact: Stop.
- The classifier is injected at the composition root (same as M3-a). When unavailable → fail-closed `"sensitive"`. → impact: Stop.
- The classify runs on the **email's quarantined Extract content** (the privileged-safe text), NOT raw mail — consistent with M8-b1's DR-a quarantine boundary (sensitivity ≠ untrusted; both axes apply — ADR-029 orthogonality). The classifier reads the Extract summary/claims on-box. → impact: Stop (do NOT feed raw mail to the classifier; feed the quarantined Extract, which is what M8-b1 already produces for the privileged side).
- Off-hardware: `FakeSensitivityClassifier`; dev-box-runnable with the real local model. → impact: Low.

Simplicity check: per-source (one classify per email), not per-fact-per-chunk. The extracted fact inherits the email's tag (no second classify) — unless the email's classify is unavailable, in which case the fact also fails closed to `"sensitive"`. Minimum: one classify per email + tag inheritance onto its fact.

## Prerequisites

- Specs complete: **brain-sensitivity-routing**, **M8-b1** (Gmail connector + signal-email ingest + fact extraction), **SENS-prod-M3a** (field contract; and, if shared, the `IngestPipeline` classify already in place).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/gmail/` (the signal-email ingest path — confirm exact file from M8-b1, e.g. `ingest.py` / `connector.py`) | modify | classify the email's quarantined Extract once per email (fail-closed); stamp `sensitivity`/`category` on the ingested email representation |
| `/Users/artemis-build/artemis/src/artemis/modules/gmail/` (the fact-extraction path) | modify | the `ExtractedFact` produced from a signal email inherits the email's `sensitivity`/`category` |
| `/Users/artemis-build/artemis/tests/test_gmail_sensitivity.py` | create | per-email classify (one call), tag on email row + extracted fact, fail-closed paths |

All paths under `/Users/artemis-build/artemis/`. (Exact filenames resolved against M8-b1's Files-to-Change at build time.)

## Tasks

- [ ] **Task 1: Classify each signal email per-source** — files: the M8-b1 signal-email ingest path (modify) —

  At the point M8-b1 ingests a signal email (after the DR-a `QuarantinedReader` produces the privileged-safe `Extract`), add a per-email classify:
  ```python
  sensitivity: Sensitivity = "sensitive"
  if self._classifier is not None:
      try:
          # classify the quarantined Extract content (sensitivity ≠ untrusted; both axes apply)
          sensitivity = await self._classifier.classify(extract.summary)
      except Exception:
          sensitivity = "sensitive"   # fail-closed
  ```
  Stamp `sensitivity` (+ `category=None`) onto the email's ingested representation (whatever row/record M8-b1 persists for a signal email — if it routes through `IngestPipeline`, that classify is already applied per SENS-prod-M3a and this becomes a no-op assertion; document which path applies). NEVER log the Extract content; log message-id + label at debug only.

  The classifier is injected (a new param on the Gmail ingest constructor / composition wiring), defaulted `None` → fail-closed.

  — done when: `uv run mypy --strict src` passes; ingesting a signal email with `FakeSensitivityClassifier("sensitive")` tags the email `"sensitive"`; `classify` is called exactly once per email; `classifier=None` / raising → `"sensitive"`.

- [ ] **Task 2: Extracted fact inherits the email tag** — files: the M8-b1 fact-extraction path (modify) —

  When M8-b1 extracts a memory fact from a signal email, the produced `ExtractedFact` (M4-b shape) carries the email's `sensitivity`/`category` (inheritance — no second classify). If the email's classify was unavailable (fail-closed `"sensitive"`), the fact is `"sensitive"` too. This dovetails with SENS-prod-M4b (which adds the `sensitivity` field to `ExtractedFact`); M8-b1 supplies the value from the email's tag.

  — done when: `uv run mypy --strict src` passes; a fact extracted from a `"general"`-tagged email is `"general"`; from a `"sensitive"` email is `"sensitive"`; no second classify call for the fact (assert call count == 1 per email).

- [ ] **Task 3: Tests** — files: `/Users/artemis-build/artemis/tests/test_gmail_sensitivity.py` (create) —

  `FakeSensitivityClassifier` (configured label / raising variant), a `FakeQuarantinedReader` producing a canned Extract.

  - **Per-email classify:** ingest a signal email → `classify` called once; email tagged with the configured label.
  - **Fact inheritance:** the extracted fact carries the email's tag; no second classify call.
  - **Fail-closed:** `classifier=None` and raising classifier → email + fact both `"sensitive"`.
  - **category reserved:** `category is None`.
  - **No raw-mail to classifier:** assert the classifier received the Extract summary, not raw mail text (mirrors the M8-b1 quarantine invariant).

  — done when: `uv run pytest -q tests/test_gmail_sensitivity.py` passes AND `uv run mypy --strict src tests/test_gmail_sensitivity.py` passes.

- [ ] **Task 4 (GATED — on-hardware):** Real classifier on real signal emails — a bank-alert email (sensitive) vs a newsletter (general); confirm one classify per email + fact inheritance. — done when: recorded in handoff. (Dev-box runnable.)

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/gmail/` (signal-email ingest + fact-extraction paths — exact files per M8-b1) |
| Create | `/Users/artemis-build/artemis/tests/test_gmail_sensitivity.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_gmail_sensitivity.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_gmail_sensitivity.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the modified Gmail ingest/extract files, `tests/test_gmail_sensitivity.py` |
| `git commit` | `"feat: SENS-prod-M8b1 — sensitivity tag on signal emails + extracted facts (ADR-029 §1)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + roles (sensitivity_classifier endpoint) |

### Network
| Action | Purpose |
|--------|---------|
| local `127.0.0.1` (GATED) | loopback classifier; off-hardware uses the fake |

## Specialist Context

### Security

- **Two orthogonal axes both apply** (ADR-029): the email is *untrusted* (→ DR-a quarantine, M8-b1) AND classified for *sensitivity* (→ this spec). The classifier reads the **quarantined Extract**, never raw mail — preserving the M8-b1 quarantine boundary. A bank-alert email is both untrusted and sensitive; a newsletter is neither.
- **Fail-closed** at every site (None classifier / raise / missing): `"sensitive"`. A false "general" on a financial alert would leak it to the cloud — unacceptable.
- The extracted fact inherits the email tag so a sensitive email cannot produce a general memory fact that later reaches the cloud via recall (closes the loop with SENS-carry-M4c1 + the enforcer).

[apex-security review: confirm the classifier sees only the Extract (not raw mail); confirm fail-closed at all sites; confirm the fact inherits (no general fact from a sensitive email). cross_model_review covers the email-corpus re-tag migration.]

### Performance

- One classify per email (per-source). The fact inherits — zero extra calls. Heaviest during the bounded Gmail backfill (ADR-029 names this as the cost driver); incremental thereafter.

### Accessibility

(none)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | the Gmail ingest path | Document the per-email classify on the Extract (not raw mail), fail-closed, and fact-tag inheritance |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_gmail_sensitivity.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_gmail_sensitivity.py` → verify: one classify per email; email + extracted fact carry the tag; fact inherits (no second classify); fail-closed on None/raising classifier; classifier sees the Extract not raw mail; category None.
- [ ] (GATED) real bank-alert → sensitive, newsletter → general, fact inherits → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
