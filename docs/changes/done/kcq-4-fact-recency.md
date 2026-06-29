---
status: ready
coder_effort: low
cross_model_review: false
---
# kcq-4-fact-recency

**Identity:** Surface temporal provenance on injected memory facts — `render_inject_block` appends each fact's `valid_at` date ("as of {date}") plus a deterministic "still current" tag, and `_rag_messages` adds a recency-weighing instruction. KCQ wave spec 4 of 6. Design: `docs/findings/supersession-recency-grounding-design-2026-06-29.md` (Decision B1 = facts-active + passive-everywhere). Shares `brain._rag_messages` with kcq-5 and kcq-6 → these three must be built **serially (any order)**, never in parallel.

## Files to change
- `src/artemis/memory/store.py` (modify) — `render_inject_block`: append date + "still current" tag per fact line.
- `src/artemis/brain.py` (modify) — add module-level `FACT_RECENCY_INSTRUCTION` constant; append it to `system_parts` in `_rag_messages` when the fact block is non-empty.
- `tests/test_memory_inject_recall.py` (modify) — update `test_render_inject_block`; add a `_rag_messages` recency-instruction test.

## Exact changes

### 1. `src/artemis/memory/store.py` — `render_inject_block`
The facts passed here come from `inject_context`, which returns current (tx-open) rows — so they are current **by construction**; render that as a literal tag (no new store query). `Fact.valid_at` is a `datetime` (see `src/artemis/ports/types.py` line 123). Use its date component only (compact).

Replace the current body (lines ~124–130):

```python
def render_inject_block(facts: Sequence[Fact]) -> str:
    """Render injected owner facts as a compact system-prompt block.

    Each line carries the fact's ``valid_at`` date and a deterministic
    "still current" tag — facts arrive from ``inject_context`` (tx-open
    rows), so they are current by construction.
    """
    if not facts:
        return ""
    lines = []
    for fact in facts:
        as_of = fact.valid_at.date().isoformat()
        lines.append(
            f"- {fact.subject} {fact.relation} {fact.object} "
            f"(as of {as_of}, still current)"
        )
    return "Known facts about the owner:\n" + "\n".join(lines)
```

Rendered line example: `- owner lives_in Paris (as of 2026-06-24, still current)`.

### 2. `src/artemis/brain.py` — recency instruction
Add a module-level constant near the other module constants (top of file, after imports):

```python
FACT_RECENCY_INSTRUCTION = (
    "Weigh recency: each owner fact is tagged with the date it became valid "
    "and whether it is still current. Prefer current information and note "
    "when a fact may be dated."
)
```

In `_rag_messages` (the fact-block branch, ~lines 405–407), append the instruction to `system_parts` when the block is non-empty:

```python
        fact_block = render_inject_block(facts)
        if fact_block:
            system_parts.append(FACT_RECENCY_INSTRUCTION)
            blocks.append(fact_block)
```

(The dates/tags themselves are injected deterministically by `render_inject_block`; only the weighing is left to the model. The `brain.respond` early-injection path at ~line 317 still gets the deterministic dates via `render_inject_block` — no change needed there.)

### 3. `tests/test_memory_inject_recall.py`

Update `test_render_inject_block` (the `fact` is dated `2026-06-24`):

```python
def test_render_inject_block() -> None:
    fact = Fact(
        "f1",
        OWNER_PERSON_ID,
        "owner",
        "lives_in",
        "Paris",
        0.9,
        datetime(2026, 6, 24, tzinfo=UTC),
    )

    assert render_inject_block([]) == ""
    block = render_inject_block([fact])
    assert "Known facts about the owner:" in block
    assert "- owner lives_in Paris (as of 2026-06-24, still current)" in block
```

Add a new test asserting `_rag_messages` carries the instruction + deterministic date:

```python
def test_rag_messages_includes_recency_instruction() -> None:
    model = RecordingModelPort()
    brain = _brain(model, owner_person_id=OWNER_PERSON_ID)
    fact = Fact(
        "f1",
        OWNER_PERSON_ID,
        "owner",
        "lives_in",
        "Paris",
        0.9,
        datetime(2026, 6, 24, tzinfo=UTC),
    )

    messages = brain._rag_messages("hi", (), (fact,))

    system = next(m.content for m in messages if m.role == "system")
    assert "recency" in system.lower()
    assert "as of 2026-06-24, still current" in system
```

## Acceptance criteria
1. `render_inject_block([fact])` returns a line ending `(as of 2026-06-24, still current)` → `uv run pytest -q tests/test_memory_inject_recall.py::test_render_inject_block` passes.
2. `_rag_messages` system message contains the recency instruction + deterministic date → `uv run pytest -q tests/test_memory_inject_recall.py::test_rag_messages_includes_recency_instruction` passes.
3. No regression in existing memory/brain tests (the `test_brain_injects_system_message_when_memory_enabled` substring `"owner lives_in Paris"` still matches the new line) → `uv run pytest -q tests/test_memory_inject_recall.py` passes.
4. Types clean → `uv run mypy` reports no new errors.

## Commands to run
```
uv run pytest -q tests/test_memory_inject_recall.py
uv run mypy
uv run pytest -q
```
