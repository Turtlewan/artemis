---
spec: R6c-comms-fetch-via-ref
status: ready
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: R6c — Comms reactions fetch-via-ref rework + register `reaction:gift_signal`

**Identity:** Reworks the shipped comms reactions (A4/A5/A7) from read-from-payload to the Fork-1 claim-check pattern: route on the payload flags, then FETCH the laundered `StructuredEmailExtract` via `source_ref` (R5d store) for content. Adds the gift reaction (reads `has_gift_signal`, fetches `gift_item`/`gift_recipient`, writes a general-tagged fact via `MemoryWritePath.add_module_fact`) and registers `reaction:gift_signal`.
<!-- → why: see docs/technical/adr/ADR-032-reactions-runtime-composition.md (§ Amendment: Fork 1 comms fetch-via-ref; Decision 6). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- After R2, the `EMAIL_INGESTED` payload carries ONLY `{message_id, source_ref, has_commitment, has_event, has_gift_signal}`. The shipped comms reactions (`recipes/comms.py`) currently read content fields (`extract_summary`, `commitment_detected`, `event_kind`, `start_datetime`, `attendee_emails`, trip fields) directly from the payload (`comms.py:85-127,219-248`) — those fields are NO LONGER emitted, so all three reactions MUST be reworked to fetch via `source_ref`. → impact: Stop (without the rework the reactions silently never match — the content keys are gone).
- A `fetch_extract: Callable[[str], Awaitable[StructuredEmailExtract | None]]` (R5d `EmailExtractStore.fetch`) is injected into `register_comms_reactions` and threaded into all three reaction partials. Content comes from the fetched extract; the payload is used ONLY for the cheap routing flags + `source_ref`. → impact: Stop.
- `react_commitment_to_task` (A4) routes on `has_commitment`; `react_email_to_held_event` (A5/A7) routes on `has_event`; the gift reaction routes on `has_gift_signal`. A reaction whose flag is false returns `skipped` WITHOUT fetching (cheap). A true flag with a missing/`None` fetched extract also returns `skipped`. → impact: Caution (fetch only when the flag is set keeps the store read off the hot path).
- The A4-inert invariant is preserved: A4 still routes to the inert `CaptureService.suggest_from_text(..., untrusted=True)` only — never a task write. The dispatcher's A4-inert wall (R1/`dispatcher.py`) is unchanged. → impact: Stop.
- `MemoryWritePath.add_module_fact` (R4m) is the gift write seam; the gift reaction passes `sensitivity="general"` EXPLICITLY (Decision 6), `category="gift_signal"`, `relation="interested_in"`, `subject=structured.gift_recipient`, `object=structured.gift_item`, `source_ref=source_ref`. A `has_gift_signal` with no `gift_recipient` or no `gift_item` is skipped (can't attribute). → impact: Stop (the explicit `general` is the only general-tagged module fact; everything else fails closed to sensitive).
- `register_comms_reactions` already accepts `memory: object | None` (currently `del memory`). R6c removes `del memory`, casts it to `MemoryWritePath`, and adds `fetch_extract`. The NEW `reaction:gift_signal` rule binds `EventType.EMAIL_INGESTED`, `tier=ReactionTier.B`, `external_effect=False`, `reaction_ref="reaction:gift_signal"`, `dedup_key_fields=("message_id",)`, appended to the returned tuple (now 3 rules). It is DISTINCT from the pre-existing `TIER_A_BUILTINS` `"gift_signal"` rule (`rulestore.py:129`, bound to `FACT_ADDED → memory.note_gift_signal`) — keep both; do not collide names. → impact: Stop.
- `source_ref` reaches the reaction through `ReactionArgs` (it is a payload scalar, so `_event_from_args` preserves it). → impact: Low.

Simplicity check: the rework deletes the `_event_extract`/`_trip_extract`/`_raw_ref` payload-reading helpers in favour of a single `_event_extract_from_structured(structured)` / `_trip_extract_from_structured(structured)` mapping the fetched object to `EventExtract`/`TripExtract`. Net: fewer payload-key lookups, one fetch, content behind the ref.

## Prerequisites
- Specs that must be complete first: **R5d** (`StructuredEmailExtract` + `EmailExtractStore.fetch`) and **R4m** (`MemoryWritePath.add_module_fact`). Wave 2 (R2 ∥ R6c — file-disjoint: R2 = gmail/calendar, R6c = comms).
- Environment setup required: none.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/reactions/recipes/comms.py` | modify | A4/A5/A7 fetch-via-ref rework; add `react_gift_signal` + `_gift_signal_tool`; `register_comms_reactions` takes `fetch_extract`, casts `memory`, registers `reaction:gift_signal`; update module docstring. |
| `tests/test_reactions_comms.py` | modify | Rework A4/A5/A7 tests to the flag+fetch pattern; add gift-reaction test; assert the 3-rule tuple. |

## Exact changes (`comms.py`)
- Imports: `from artemis.modules.gmail.structured import StructuredEmailExtract`; `from artemis.memory.write_path import MemoryWritePath`; `FetchExtractFn = Callable[[str], Awaitable[StructuredEmailExtract | None]]`.
- Module-level guard (security review — validate the payload-derived store key before lookup): `_SOURCE_REF_RE = re.compile(r"^gmail:[A-Za-z0-9_-]+$")` and `def _valid_source_ref(s: str | None) -> bool: return s is not None and _SOURCE_REF_RE.match(s) is not None`. All three reactions fetch only when `_valid_source_ref(source_ref)`; a malformed ref → `skipped` (guards cross-email attribution from a crafted event).
- A4 `react_commitment_to_task(event, *, capture_service, fetch_extract)`:
  ```python
  if event.event_type is not EventType.EMAIL_INGESTED or not _payload_bool(event, "has_commitment"):
      return ReactionResult(status="skipped", ref=None, undoable=False)
  source_ref = _payload_str(event, "source_ref")
  structured = await fetch_extract(source_ref) if _valid_source_ref(source_ref) else None
  if structured is None or not structured.summary:
      return ReactionResult(status="skipped", ref=None, undoable=False)
  sid = await capture_service.suggest_from_text("email", structured.summary, untrusted=True)
  return ReactionResult(status="suggested", ref=sid, undoable=False)
  ```
- A5/A7 `react_email_to_held_event(event, *, calendar_from_extract_fn, trip_assembler, fetch_extract)`:
  ```python
  if event.event_type is not EventType.EMAIL_INGESTED or not _payload_bool(event, "has_event"):
      return ReactionResult(status="skipped", ref=None, undoable=False)
  source_ref = _payload_str(event, "source_ref")
  structured = await fetch_extract(source_ref) if _valid_source_ref(source_ref) else None
  if structured is None or structured.event_kind not in {"flight", "meeting"}:
      return ReactionResult(status="skipped", ref=None, undoable=False)
  extract = _event_extract_from_structured(structured)   # maps fields; raw_ref=structured.source_ref
  if extract is None:
      return ReactionResult(status="skipped", ref=None, undoable=False)
  if structured.event_kind == "flight":
      trip_assembler.assemble(_trip_extract_from_structured(structured, extract))
  held = await calendar_from_extract_fn(extract, structured.event_kind)
  return ReactionResult(status="held", ref=held.id, undoable=True)
  ```
- NEW gift `react_gift_signal(event, *, memory: MemoryWritePath, fetch_extract)`:
  ```python
  if event.event_type is not EventType.EMAIL_INGESTED or not _payload_bool(event, "has_gift_signal"):
      return ReactionResult(status="skipped", ref=None, undoable=False)
  source_ref = _payload_str(event, "source_ref")
  structured = await fetch_extract(source_ref) if _valid_source_ref(source_ref) else None
  if structured is None or not structured.gift_item or not structured.gift_recipient:
      return ReactionResult(status="skipped", ref=None, undoable=False)
  fact_id = await memory.add_module_fact(
      subject=structured.gift_recipient, relation="interested_in", object_=structured.gift_item,
      category="gift_signal", source_ref=source_ref, sensitivity="general",
  )
  return ReactionResult(status="noted", ref=fact_id, undoable=True)
  ```
- `register_comms_reactions(registry, *, capture_service, calendar_from_extract_fn, trip_assembler, fetch_extract, memory=None)`: remove `del memory`; `mem = cast(MemoryWritePath, memory)`; build the three partials threading `fetch_extract` (and `memory=mem` for gift); register `reaction:gift_signal`; append its `ReactionRule` to the returned tuple. Update the module docstring's "gift-signal intentionally not registered" note → "registered; writes a general-tagged fact via add_module_fact (ADR-032 Decision 6)".

## Tasks
- [ ] Task 1: Rework A4/A5/A7 to flag-route + fetch-via-ref; replace `_event_extract`/`_trip_extract`/`_raw_ref` with `_event_extract_from_structured`/`_trip_extract_from_structured`. — files: `src/artemis/reactions/recipes/comms.py` — done when: A4 routes on `has_commitment`+fetched summary; A5/A7 routes on `has_event`+fetched `event_kind`; neither reads content keys from the payload; A4-inert preserved.
- [ ] Task 2: Add `react_gift_signal` + `_gift_signal_tool`; register `reaction:gift_signal`; thread `fetch_extract`/`memory`. — files: `src/artemis/reactions/recipes/comms.py` — done when: `register_comms_reactions` returns a 3-rule tuple including `reaction:gift_signal` (EMAIL_INGESTED, tier B, external_effect=False); the gift tool is on the registry; `del memory` is gone.
- [ ] Task 3: Tests — files: `tests/test_reactions_comms.py` — done when: (a) A4 with `has_commitment=True` + a fake `fetch_extract` returning a summary calls `suggest_from_text` and returns `suggested`; with `has_commitment` false it skips WITHOUT fetching; (b) A5/A7 with `has_event=True` + fetched flight extract assembles a trip + creates a held event; (c) gift with `has_gift_signal=True` + fetched `gift_item`+`gift_recipient` calls `add_module_fact` once with `category="gift_signal"`, `sensitivity="general"` (passed EXPLICITLY — assert it is the keyword used; this is the ONLY general-tagged write in the module), `relation="interested_in"`, returns `noted`; a `has_gift_signal` with no recipient skips; (d) malformed `source_ref` (e.g. `"evil:1"` or `""`) → `skipped` and `fetch_extract` is NEVER awaited; (e) the returned tuple has 3 rules; `uv run pytest -q tests/test_reactions_comms.py` passes.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3]

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | `src/artemis/reactions/recipes/comms.py`, `tests/test_reactions_comms.py` |
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
| `git add` | `src/artemis/reactions/recipes/comms.py tests/test_reactions_comms.py` |
| `git commit` | "feat: R6c comms fetch-via-ref rework + register reaction:gift_signal (ADR-032 Fork 1 / Decision 6)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No package installs. |

## Specialist Context
### Security
`cross_model_review: true` — reworks live comms reactions to fetch untrusted-derived content behind a ref (Fork-1 claim-check). Reviewer must confirm: (1) reactions read ONLY the routing flags + `source_ref` from the payload, never content; (2) content comes from the owner-private R5d store, never the event; (3) A4 stays inert (suggest only); (4) the gift fact is the ONLY `general`-tagged write, explicit, and skips when it can't attribute a recipient; (5) the fetched extract (owner-private) is not re-emitted onto the bus or leaked into a cloud path.

### Performance
(none — one store fetch per matched reaction, gated behind the flag.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/reactions/recipes/comms.py` | Update module docstring (fetch-via-ref pattern; gift now registered). |
| ADR | docs/technical/adr/ADR-032-reactions-runtime-composition.md | Already amended (Fork 1 + Decision 6). No change. |

## Acceptance Criteria
- [ ] A4 fetch-via-ref → verify: `has_commitment=True` + fetched summary → `suggest_from_text` called, `suggested`; false flag → `skipped` with no fetch; A4 never writes a task.
- [ ] A5/A7 fetch-via-ref → verify: `has_event=True` + fetched flight extract → trip assembled + held event created (`held`); non-flight/meeting → `skipped`.
- [ ] gift reaction → verify: `has_gift_signal=True` + fetched item+recipient → one `add_module_fact(category="gift_signal", sensitivity="general", relation="interested_in")`, `noted`; missing recipient → `skipped`; `sensitivity="general"` is the only general-tagged call in the module.
- [ ] source_ref guard → verify: a malformed/empty `source_ref` returns `skipped` and never awaits `fetch_extract` (cross-email-attribution guard).
- [ ] 3-rule tuple → verify: `register_comms_reactions` returns A4, A5/A7, and `reaction:gift_signal` (EMAIL_INGESTED, tier B, external_effect=False).
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
