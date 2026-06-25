# Progress: RXN-recipes-comms — PARTIAL (gift_signal parked)

Built by Codex; host-verified: mypy clean (256 files), ruff clean, 717 passed / 2 skipped.

## Built (green, committed)
- `reaction:email_to_task` — A4 inert CaptureService suggestion path
- `reaction:email_to_held_event` — A5/A7 held-event path (flight Trip assembly; no Maps/airport-block
  ownership, that's planning's Trip reaction)
- registry wiring + re-export + tests (routing, dedup, no-raw-body, held events, TripExtract assembly,
  canonical rule shape, and an explicit gift_signal-block test)

## PARKED — gift_signal (Task blocked on an unbuilt prerequisite)
`reaction:gift_signal` cannot be built as written: it needs a **module-initiated fact-push API**
(`source_kind="module"`, `source_ref`, gift-signal category) — the ADR-021 dependency #1 "M4-b module
fact-push amendment". Live code only has `MemoryStore.add_fact(person_id, fact)` (ports/memory.py,
memory/store.py); there is no module-source fact-push with a gift-signal category. Left unregistered,
documented + tested as blocked.

**Decision needed (planning):** build the M4-b module-fact-push amendment (`source_kind="module"` +
gift-signal category on the memory write path), THEN finish `reaction:gift_signal` here. Until then,
RXN-recipes-comms stays in docs/changes/ marked PARTIAL (not archived to done/).
