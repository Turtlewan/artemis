# Brief: CAL-d — knowledge push + memory extraction + untrusted-content quarantine

- **For:** AFK Deep Details drafting · **autonomy_level:** L2 · **token_profile:** balanced
- **review_domains:** security, ai-systems  _(security: external invite text is THE injection vector — the quarantine chokepoint is the critical control; ai-systems: the dual-LLM quarantine usage + the fact-extraction prompt + grounding)_
- **Read first:** `docs/briefs/CAL-shared.md` · `docs/technical/modules/calendar.md` §F,§Security · DR-a (`artemis.untrusted`) · M3-a (`Connector`/`IngestPipeline`) · M4-b (`MemoryWritePath`/`build_write_path`) · M2
- **Build order:** after CAL-c (uses CAL-a cache + the `externally_authored` tag; consumed by CAL-c's briefing/prep hooks — if CAL-c ships first, its render-paths call CAL-d's helper once it lands; sequence so CAL-d's `quarantine_event_text` exists before any hook renders external text, OR CAL-c hooks defer rendering external text until CAL-d — drafter notes the ordering).

## Intent
The brain-integration layer: push past-meeting summaries to the **knowledge layer**, extract standing
facts to **memory** (A.U.D.N.), and the **`artemis.untrusted` quarantine** of externally-authored event
text — the single chokepoint (shared decision 4) protecting every path event text reaches the LLM.

## Scope / files (proposed — drafter finalises)
- `src/artemis/modules/calendar/untrusted.py` — `quarantine_event_text(event)` over DR-a (spotlight + dual-LLM quarantine) applied to externally-authored fields; trusted passthrough for self-created
- `knowledge.py` — `Connector` impl pushing past-meeting summaries → `IngestPipeline.ingest` (M3-a)
- `memory.py` — extract standing facts (recurring 1:1s, key contacts) → `MemoryWritePath`/`build_write_path` (M4-b) via A.U.D.N.
- `manifest.py` (**modify** if any new tool surfaces; else integration-only)
- `tests/test_calendar_integration.py`

## Resolved decisions (from CAL-shared — bind)
- Untrusted chokepoint at the **LLM-prompt boundary**: externally-authored (organizer/creator ≠ owner, the CAL-a flag) → through DR-a before any LLM prompt. Self-created = trusted.
- CAL-d **owns `quarantine_event_text`**; CAL-c's briefing/prep hooks call it before rendering external text. ⚠️ Security-review focus: confirm the chokepoint covers EVERY path external event text reaches the model — including the brain's direct rendering of a CAL-a read-tool result. If that path bypasses the helper, **flag it** (the brain may need to apply quarantine on calendar tool outputs, or read tools must return pre-quarantined text for LLM-facing fields).
- Knowledge push: past-meeting summaries only (not raw external text un-quarantined). Memory: standing facts via A.U.D.N., cardinality-aware (M4-b).
- All of this is Tier-1 (owner-private, needs unlock).

## Tasks (concern layers)
1. `quarantine_event_text` over DR-a (spotlight + quarantined-LLM extract; toolless reader; schema-validated) applied to title/description/location/attendee-display-names of externally-authored events.
2. Knowledge `Connector` → push past-meeting summaries to `IngestPipeline.ingest` (M3-a) with provenance/locator.
3. Memory extraction → standing facts via `MemoryWritePath`/`build_write_path` (M4-b), A.U.D.N., cardinality-aware.
4. Wire CAL-c's briefing/prep render paths through `quarantine_event_text`.
5. Tests (fakes): self-created text bypasses quarantine; external text is quarantined (a poisoned invite title cannot reach a tool/escape the schema); knowledge push idempotent; memory extraction emits cardinality-correct facts; locked → `ScopeLockedError`.
6. (GATED on-hardware) real DR-a quarantine on a real external invite; real knowledge/memory writes.

## Acceptance shape
mypy --strict + ruff clean; pytest proves external-text quarantine (injection cannot escape), trusted passthrough, idempotent knowledge push, cardinality-correct memory facts, locked-store; gated on-hardware = real quarantine + writes.

## Out of scope / deferred
Read/write/overlay/hooks (CAL-a/b/c); the full CaMeL data-plane (DR-a deferred); learned preferences; Maps/travel.
