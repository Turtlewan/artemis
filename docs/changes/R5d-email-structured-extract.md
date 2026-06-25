---
spec: R5d-email-structured-extract
status: ready
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: R5d — Email detection/structuring step + quarantined-extract store + fetch seam

**Identity:** Adds the privileged-side email structuring layer the comms reactions need: an `EmailClassifier` that turns the LAUNDERED `Extract` (summary+claims) into a `StructuredEmailExtract` (non-sensitive flags + structured event/trip/gift fields) on the LOCAL responder, and an owner-private SQLCipher `EmailExtractStore` keyed by `source_ref` with a `fetch` lookup. Closes the Fork-1 build gap: no producer builds the structured payload today and no fetchable extract store exists.
<!-- → why: see docs/technical/adr/ADR-032-reactions-runtime-composition.md (§ Amendment: Email structured-extract layer). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- The structuring step runs over the LAUNDERED `Extract.summary` + `Extract.claims` (`untrusted/quarantine.py` — injection-flagged input already blanked, `usable` gates it), NEVER raw body. It is therefore a privileged-side call and uses the normal LOCAL responder via structured output (`ModelPort.complete(..., response_schema=…)`), mirroring `QuarantinedReader`'s constrained-decode pattern but without the spotlight wrapper (input is already safe). → impact: Stop (running it on raw body, or on the cloud responder, violates ADR-022 "email stays local" + the injection wall).
- The local responder is injected as a `ModelPort` (no cloud egress). The classifier never calls a cloud model. → impact: Stop (ADR-022 sensitivity routing — email is owner-private).
- The `EmailExtractStore` is owner-private SQLCipher (mirror `ReactionLedger` construction: `Settings` + `KeyProvider`, `sqlcipher_open(db_path, key.as_hex())`, `paths.scope_dir(settings, OWNER_PRIVATE)`), keyed by `source_ref` (PRIMARY KEY), with a `stored_at` column for TTL prune. It stores the JSON-serialised `StructuredEmailExtract`. → impact: Stop (a non-owner-private store would leak laundered email content).
- `StructuredEmailExtract` field names are the SHARED CONTRACT consumed by R2 (which reads the three flags for the emitted payload) and R6c (which fetches the whole object and maps it to `EventExtract`/`TripExtract`/gift). The field set below is fixed by what the live `comms.py` `_event_extract`/`_trip_extract` build. → impact: Stop (a field-name drift breaks R6c's mapping + R2's flags).
- This spec adds NO emit and NO comms change — it only builds the classifier, the store, and the `fetch` seam. R2 calls the classifier + store on the gmail path and emits; R6c consumes `fetch`. → impact: Low (keeps R5d file-disjoint from R2/R6c so Wave-1 R5d ∥ R1/R3/R4m holds).
- `EmailClassifier` returns `None` (not a raised error) for a non-usable extract or a transient model failure, and LOGS the failure (Fork 1b: log, don't swallow) — the caller (R2) treats `None` as "no emit" but the failure is visible in logs. → impact: Caution (raising would abort the ingest path).

Simplicity check: considered extending `QuarantinedReader`'s schema to emit the structured fields in one call — rejected: `QuarantinedReader` is a shared generic primitive (DR-c, M3 ingestion) and coupling comms-specific fields into it would bloat every consumer's extract; a separate privileged structuring step keeps the untrusted reader generic. Two local calls per signal email is acceptable for a single-user hub.

## Prerequisites
- Specs that must be complete first: none (Wave 1; independent of R1/R3/R4m — gmail-module-internal + new files).
- Environment setup required: none (no new deps — reuses `ModelPort`, `sqlcipher_open`, `KeyProvider`).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/modules/gmail/structured.py` | create | `StructuredEmailExtract` (frozen pydantic) + `EMAIL_DETECTION_SCHEMA` (bounded JSON schema). |
| `src/artemis/modules/gmail/classify.py` | create | `EmailClassifier` (local `ModelPort` + schema → `StructuredEmailExtract | None`; usable-gate; log-not-swallow). |
| `src/artemis/modules/gmail/extract_store.py` | create | `EmailExtractStore` (owner-private SQLCipher; `put(extract)`, `fetch(source_ref) -> StructuredEmailExtract | None`, `prune_older_than(cutoff_iso)`). |
| `tests/test_email_structured_extract.py` | create | classifier maps fields + flags; non-usable/failure → None + logged; store round-trips by source_ref; prune drops stale. |

## Exact changes

### `structured.py`
```python
class StructuredEmailExtract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_ref: str                       # gmail:{message_id}; from trusted caller, not model
    summary: str = Field(max_length=2000)  # capped at the store boundary (matches quarantine cap)
    has_commitment: bool = False
    has_event: bool = False
    has_gift_signal: bool = False
    event_kind: str | None = None         # "flight" | "meeting" | None
    title: str | None = None
    start_datetime: str | None = None
    end_datetime: str | None = None
    location: str | None = None
    description: str | None = None
    attendee_emails: tuple[str, ...] = ()
    origin: str | None = None             # flight
    destination: str | None = None        # flight
    confirmation_ref: str | None = None   # flight
    co_travellers: tuple[str, ...] = ()   # flight
    gift_item: str | None = None
    gift_recipient: str | None = None     # person the gift signal is about (e.g. "Ashley")
```
The gift reaction (R6c) attributes the fact to `gift_recipient` (resolved to a PERSON entity); a `has_gift_signal` with no `gift_recipient` is skipped (can't attribute).
`EMAIL_DETECTION_SCHEMA` = a bounded JSON object covering the model-supplied fields (everything EXCEPT the trusted-caller fields `source_ref` AND `summary`, which the model must NOT supply), `additionalProperties: false`, with length caps; `event_kind` enum `["flight","meeting"]` or omitted; arrays `maxItems` bounded. `summary` is truncated to 2000 chars when the trusted `Extract.summary` is read (defensive — a forged Extract cannot store an unbounded string; `StructuredEmailExtract.summary` also has `max_length=2000`).

### `classify.py`
```python
class EmailClassifier:
    def __init__(self, model: ModelPort, role: str = "responder") -> None: ...
    async def classify(self, extract: Extract) -> StructuredEmailExtract | None:
        if not extract.usable:
            return None
        text = "\n".join([extract.summary, *extract.claims]).strip()
        if not text:
            return None
        try:
            resp = await self._model.complete(
                role=self._role,
                messages=[Message(role="system", content=_DETECT_INSTRUCTION),
                          Message(role="user", content=text)],
                response_schema=EMAIL_DETECTION_SCHEMA,
                max_tokens=512,
            )
            data = json.loads(resp.text)
            return StructuredEmailExtract(
                source_ref=extract.source_url,
                summary=extract.summary[:2000],
                **_coerce(data),
            )
        except Exception:
            logger.warning("email structuring failed for %s", extract.source_url, exc_info=True)  # log, don't swallow
            return None
```
(`_coerce` clamps/normalises model output to the field types AND **strips any `source_ref`/`summary` keys the model returned** before the `**` unpack — those two fields come from the trusted `Extract` only, never model output, and a model-supplied collision would otherwise raise a duplicate-keyword `TypeError`. `exc_info=True` surfaces a `_coerce` bug vs a transient model error in the logs.)

### `extract_store.py`
SQLCipher table `email_extract(source_ref TEXT PRIMARY KEY, payload_json TEXT NOT NULL, stored_at TEXT NOT NULL)`; `put` = `INSERT OR REPLACE` with `stored_at = now_iso()` (`artemis.memory.schema.now_iso` — UTC, zero-padded ISO-8601, the SAME function used by the ledger/repo so the lexicographic TTL compare is correct); `fetch` = SELECT + `StructuredEmailExtract.model_validate_json`; `prune_older_than(cutoff_iso)` = `DELETE WHERE stored_at < ?`. Construction mirrors `ReactionLedger`.

**TTL enforcement call-site (deferred wiring, like R1/R2's producer wiring):** `prune_older_than` is a helper; the actual prune is invoked at app-root bring-up from the heartbeat pre-tick step (alongside the reaction-ledger prune), cutoff `(datetime.now(UTC) - timedelta(days=_STORE_TTL_DAYS)).isoformat()`, `_STORE_TTL_DAYS = 30`. No app-root exists yet (R1 documented this) — flagged for the bring-up plan so the owner-private store cannot grow unbounded.

## Tasks
- [ ] Task 1: Create `structured.py` — `StructuredEmailExtract` + `EMAIL_DETECTION_SCHEMA`. — files: `src/artemis/modules/gmail/structured.py` — done when: the model constructs with `source_ref`+`summary` only (all else defaulted); `extra="forbid"` rejects unknown keys; the schema validates a representative flight + meeting + gift payload.
- [ ] Task 2: Create `classify.py` — `EmailClassifier.classify` returns a populated `StructuredEmailExtract` for a usable extract, `None` (logged, `exc_info=True`) for non-usable/empty/model-failure; `source_ref`/`summary` sourced from the `Extract`, never model output; `_coerce` STRIPS any model-returned `source_ref`/`summary` keys before the `**` unpack. — files: `src/artemis/modules/gmail/classify.py` — done when: a fake `ModelPort` returning a flight JSON yields `event_kind=="flight"` + `start_datetime` set; a model JSON that ALSO returns a `summary`/`source_ref` key does NOT override the trusted `Extract` values (and does not raise); a non-usable `Extract` yields `None` with a logged warning; a model exception yields `None` + log (no raise).
- [ ] Task 3: Create `extract_store.py` — owner-private SQLCipher `EmailExtractStore` with `put`/`fetch`/`prune_older_than`. — files: `src/artemis/modules/gmail/extract_store.py` — done when: `put(extract); fetch(extract.source_ref)` round-trips an equal `StructuredEmailExtract`; `fetch("missing")` is `None`; `prune_older_than(cutoff)` deletes only stale rows.
- [ ] Task 4: Tests. — files: `tests/test_email_structured_extract.py` — done when: `uv run pytest -q tests/test_email_structured_extract.py` passes (classifier field/flag mapping, None-on-non-usable + logged, None-on-failure + logged, store round-trip + prune).

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2, Task 3] | Wave 3: [Task 4]

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/modules/gmail/structured.py`, `src/artemis/modules/gmail/classify.py`, `src/artemis/modules/gmail/extract_store.py`, `tests/test_email_structured_extract.py` |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The four files above, by name. |
| `git commit` | "feat: R5d email structuring step + owner-private quarantined-extract store + fetch seam" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No package installs; the classifier model is injected (local). |

## Specialist Context
### Security
`cross_model_review: true` — first persisted store of laundered email content + a new model call on the email path. Reviewer must confirm: (1) the classifier input is the LAUNDERED summary/claims, never raw body; (2) the model is the LOCAL responder — no cloud egress on the email path; (3) `source_ref`/`summary` come from the trusted `Extract`, never model output (no model-controlled provenance); (4) the store is owner-private SQLCipher and never crosses the privacy wall; (5) non-usable / injection-flagged extracts produce no structured extract (the `usable` gate) and failures are logged, not swallowed.

### Performance
(none — one extra bounded local call per signal email; store is an indexed PK lookup.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/gmail/classify.py` | Docstring: privileged-side structuring over laundered text, local-only, log-not-swallow. |
| Inline | `src/artemis/modules/gmail/extract_store.py` | Docstring: owner-private, source_ref-keyed, TTL'd claim-check store. |
| Reconcile | docs/technical/architecture/data-model.md | Add the new owner-private `email_extract` entity/table (source_ref PK, payload_json, stored_at) to the conceptual model. |
| ADR | docs/technical/adr/ADR-032-reactions-runtime-composition.md | Already amended (§ Email structured-extract layer). No change. |

## Acceptance Criteria
- [ ] `StructuredEmailExtract` contract → verify: constructs with `source_ref`+`summary`, defaults elsewhere; rejects unknown keys; schema validates flight/meeting/gift samples.
- [ ] Classifier maps fields + flags → verify: fake flight JSON → `event_kind=="flight"`, `start_datetime` set, `has_event True`; gift JSON → `has_gift_signal True`, `gift_item` set.
- [ ] Trusted fields not shadowable + capped → verify: a model JSON returning `summary`/`source_ref` keys does not override the trusted `Extract` values; a 3000-char `Extract.summary` is stored truncated to 2000 (no validation error).
- [ ] Classifier fails safe + logs → verify: non-usable `Extract` and a model exception each return `None` with a logged warning (`exc_info=True`, no raise).
- [ ] Store round-trips owner-private by source_ref → verify: `put`/`fetch` equal object; `fetch("missing")` is `None`; `prune_older_than` drops only stale rows.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
