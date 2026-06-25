# Progress: sensitivity-ground-rules

## Fork (Task 6 — FIN-d enqueue drop) — Files-table under-enumeration

**What the spec says:** Task 6 drops the finance→general-memory enqueue (owner FIN-d Option A,
locked 2026-06-25). Files-to-Change lists only `finance/knowledge.py` + `finance/manifest.py`.

**Why it can't be done as listed:** the `memory_queue` plumbing actually lives across 4 files:
- `finance/knowledge.py` — `push_finance_knowledge` param + `enqueue` call + `MemoryQueuePort` (listed ✓)
- `finance/manifest.py` — threads `memory_queue` into `init_finance_knowledge` (listed ✓)
- `finance/tools.py` — **NOT listed**: `_memory_queue` module global (line 29), `init_finance_knowledge`
  signature (307), `_get_knowledge_handles` return tuple (503), and a 2nd `push_finance_knowledge`
  call inside `finance_knowledge_push` (676-683)
- `tests/test_finance_knowledge.py` — **NOT listed**: ~5 tests assert the OLD behavior
  (memory_queue.records == fact texts, all "sensitive"); they invert under Option A

**Codex correctly blocked** the whole build (touched nothing) rather than touch unlisted files.

**RESOLVED (owner 2026-06-25): expand scope, build it.** Task 6 scope expanded to `tools.py`
+ `tests/test_finance_knowledge.py` (owner-approved). Built green, committed b6ebc10.

## Outcome — COMPLETE @ b6ebc10
Host-verified: full mypy clean (233 files), ruff clean, 621 passed / 2 skipped.

### Deviations / cross-model-review actions (for planning)
- **Files-table correction (owner-approved):** Task 6 FIN-d enqueue drop touched `finance/tools.py`
  + `tests/test_finance_knowledge.py` beyond the spec's 2-file Task-6 list. Mechanical, intent-
  preserving (owner FIN-d Option A already locked).
- **Ambiguity #4 resolved in-build:** added `SensitivityConfig.owner_overrides` field so
  `graduate_to_policy`'s policy.json write round-trips under `extra="forbid"`.
- **Cross-model (Opus) review hardening applied:** `SensitivityReviewItem.text_preview` is now
  hard-capped at 200 chars in `__post_init__` (was unguarded — HIGH privacy finding; spec comment
  intended the cap) + regression test added.

### FLAGGED for planning (NOT changed — spec-acknowledged / low-sev)
- **⚠ Ambiguity #3 (HIGH, spec-acknowledged): bare-date DOB over-fire.** `_DOB_RE` bare branch
  fires on any `DD-MM-YYYY` in flowing text (calendar/finance dates) → over-classifies to
  sensitive. Fail-TOWARD-sensitive (no privacy leak) but routes legit general content off cloud.
  Spec said build-as-written + flag. Planning decision: labelled-only, or a birth-year-range guard.
- **graduate_to_policy keys by `review_id`, not `source_id`** (low) — spec prose said "source_id
  pattern"; stub has no live reader yet. Reconcile key semantics before the owner-review UI is wired.
- **Detector span/strip notes** (low, awareness): `exceeds_masked_tail` uses full-containment span
  check (stricter than spec, fine); `has_full_card_number` strips all separators before Luhn scan
  (could merge adjacent numbers → fail-toward-sensitive). No action.
- **test_fin_d_amendment dead assertion** (low): `FakeMemoryWriteQueue.calls == 0` is trivially
  true (queue never passed — push_finance_knowledge no longer accepts it). Real guard = the param's
  absence. Optional: switch to a signature-inspection assertion.
