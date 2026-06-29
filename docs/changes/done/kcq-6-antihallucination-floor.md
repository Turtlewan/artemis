---
status: ready
coder_effort: medium
cross_model_review: true
---
# kcq-6-antihallucination-floor

**Identity:** Deterministic, always-on faithfulness floor on the main answer path (`brain._rag_messages` + `respond`): gap-tag on empty/thin retrieval + cite-inline instruction + post-gen citation-presence validation — NO extra model call. Design: `docs/findings/anti-hallucination-answer-layer-design-2026-06-29.md` (Decision C1, cheap floor only; the model-driven claim-audit + cross-doc contradiction tier is Mac-parked, OUT of scope). Wave KCQ spec **6 of 6**. Shares `brain._rag_messages` / the `respond` path with **kcq-4** and **kcq-5** — build kcq-4 → kcq-5 → kcq-6 **serially** (do not parallelise; merge conflicts on the same two methods).

**Scope honesty (state in code comments, do not drift):** this floor catches **(i)** thin/empty evidence (forces a `[MATERIAL GAP]` notice) and **(ii)** invalid/hallucinated citations (a cited `[chunk_id]` not in the provided context). It does **NOT** catch confident *uncited* fabrication — that is the Mac model-audit tier, out of scope here.

## Files to change

1. `src/artemis/untrusted/citation_check.py` — **create**. Self-contained, model-free validator (instruction constants + gap detector + citation-presence parser + combined `audit_answer`).
2. `src/artemis/brain.py` — **modify**. Inject the cite/gap instruction + force the gap notice in `_rag_messages`; run `audit_answer` post-generation in `respond` and surface notices on `BrainResponse`.
3. `tests/test_citation_check.py` — **create**. Unit tests for the validator in isolation + the two `_rag_messages`/`respond` hooks.

(`src/artemis/untrusted/__init__.py` exports are optional — import directly from `artemis.untrusted.citation_check` in `brain.py`; do not expand `__all__` unless a test needs it.)

## Exact changes

### 1. `src/artemis/untrusted/citation_check.py` (new)

Mirror `spotlight.py` style (module docstring, `from __future__ import annotations`, a module-level instruction constant, small pure functions).

```python
"""Deterministic faithfulness floor for the main answer path.

Model-free. Catches (i) thin/empty retrieval (forces a [MATERIAL GAP] notice)
and (ii) hallucinated citations (a cited [chunk_id] absent from the provided
context). It does NOT catch confident uncited fabrication — that is the
Mac-parked model-audit tier (design doc Decision C1, heavy tier).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from artemis.ports.types import Fact, RetrievedChunk

# Appended to the RAG system prompt. Tells the model to cite inline and to
# self-tag gaps; the answer layer does not rely on the model honouring this
# (gap-tagging + citation-presence are enforced deterministically below).
CITE_INSTRUCTION = (
    "Cite the supporting context inline using its [chunk_id] tag immediately "
    "after each claim it supports. Use only chunk_ids that appear in the "
    "Retrieved context above. If the context does not support a claim, do not "
    "invent a citation — instead tag that part of your answer with "
    "[MATERIAL GAP] to flag the missing support."
)

# Deterministic notice forced into the prompt (and the response) when retrieval
# is empty/thin, so the gap does not depend on the model admitting it.
MATERIAL_GAP_NOTICE = "[MATERIAL GAP] no supporting context retrieved"

# Primary floor is count/empty. min_score additionally drops chunks whose
# relevance score is below the bar ("thin"); default keeps all non-negative
# scores so existing retrieval behaviour is unchanged.
DEFAULT_MIN_SCORE = 0.0

# Matches a single [token] with no nested brackets/newlines; the MATERIAL GAP
# sentinel is filtered out so it is never mistaken for a citation.
_CITATION_RE = re.compile(r"\[([^\[\]\n]+)\]")
_GAP_SENTINEL = "MATERIAL GAP"


def usable_chunks(
    chunks: tuple[RetrievedChunk, ...], *, min_score: float = DEFAULT_MIN_SCORE
) -> tuple[RetrievedChunk, ...]:
    """Chunks at/above the relevance bar — the evidence actually in the prompt."""
    return tuple(c for c in chunks if c.score >= min_score)


def has_material_gap(
    chunks: tuple[RetrievedChunk, ...],
    facts: tuple[Fact, ...],
    *,
    min_score: float = DEFAULT_MIN_SCORE,
) -> bool:
    """True when no usable chunk AND no fact backs the answer."""
    return not usable_chunks(chunks, min_score=min_score) and not facts


def invalid_citations(answer_text: str, present_ids: frozenset[str]) -> tuple[str, ...]:
    """[chunk_id] tokens cited in the answer that are not in present_ids.

    The MATERIAL GAP sentinel is excluded. Order-stable, de-duplicated.
    """
    seen: list[str] = []
    for match in _CITATION_RE.finditer(answer_text):
        token = match.group(1).strip()
        if token == _GAP_SENTINEL or token in present_ids:
            continue
        if token not in seen:
            seen.append(token)
    return tuple(seen)


@dataclass(frozen=True)
class FaithfulnessReport:
    material_gap: bool
    invalid_citations: tuple[str, ...]

    def notices(self) -> list[str]:
        """Human-readable deterministic warnings (empty when clean)."""
        out: list[str] = []
        if self.material_gap:
            out.append(MATERIAL_GAP_NOTICE)
        if self.invalid_citations:
            out.append(
                "[CITATION WARNING] cited context not provided: "
                + ", ".join(self.invalid_citations)
            )
        return out


def audit_answer(
    answer_text: str,
    chunks: tuple[RetrievedChunk, ...],
    facts: tuple[Fact, ...],
    *,
    min_score: float = DEFAULT_MIN_SCORE,
) -> FaithfulnessReport:
    """Run both deterministic checks over a generated answer.

    present_ids are the usable chunk_ids that were actually placed in the
    prompt, so a citation to anything else is flagged as hallucinated.
    """
    usable = usable_chunks(chunks, min_score=min_score)
    present_ids = frozenset(c.chunk.chunk_id for c in usable)
    return FaithfulnessReport(
        material_gap=has_material_gap(chunks, facts, min_score=min_score),
        invalid_citations=invalid_citations(answer_text, present_ids),
    )
```

### 2. `src/artemis/brain.py`

**a. `BrainResponse.__init__`** (currently `(self, text, path, tool_used=None, escalated=False, held_back=None)`, lines ~61-73) — add a deterministic-notice field, additive and defaulted so all existing constructions are unaffected:

```python
        held_back: list[HeldBackItem] | None = None,
        notices: list[str] | None = None,
    ) -> None:
        ...
        self.held_back = held_back or []
        self.notices = notices or []
```

**b. `_rag_messages`** (lines ~388-416) — import the new module alongside spotlight, append `CITE_INSTRUCTION` to `system_parts`, filter chunks through `usable_chunks`, and force the gap notice when retrieval is thin/empty:

- At the top: `from artemis.untrusted.citation_check import (CITE_INSTRUCTION, MATERIAL_GAP_NOTICE, has_material_gap, usable_chunks)`.
- Replace the chunk loop's `chunks` iteration with `usable = usable_chunks(chunks)`; build the `[chunk_id] text` block from `usable` (keep the existing spotlight call on the joined raw block). Guard with `if usable:` instead of `if chunks:`.
- After the `if usable:` / fact block, **append `CITE_INSTRUCTION` to `system_parts`** whenever any block exists (so the model is always told to cite when context is present).
- If `has_material_gap(chunks, facts)` is true: append `MATERIAL_GAP_NOTICE` to `blocks` (so even the no-context turn returns a `system` message stating the gap) and still append `CITE_INSTRUCTION` to `system_parts`. This replaces the current early `return [Message(role="user", content=request_text)]` for the empty case — the gap turn must now carry a system message. Keep the plain user-only return ONLY when there is genuinely nothing to say (there is no longer such a case once the gap notice is forced, so the `if not blocks` branch can be removed or left as dead-safe fallback returning the user message).

Resulting `combined_system` ordering: spotlight instruction (if chunks) → `CITE_INSTRUCTION` → blocks (retrieved context / fact block / gap notice). Preserve the existing `"\n\n".join(...)` joining.

**c. `respond`** (lines ~378-386) — hook the post-generation audit:

```python
        messages = self._rag_messages(
            request_text, decision.context.cloud_safe_chunks, decision.context.cloud_safe_facts
        )
        result = await self._model.complete(role=decision.role, messages=messages)
        from artemis.untrusted.citation_check import audit_answer

        report = audit_answer(
            result.text,
            decision.context.cloud_safe_chunks,
            decision.context.cloud_safe_facts,
        )
        notices = report.notices()
        text = result.text
        for notice in notices:
            if notice not in text:
                text = f"{text}\n\n{notice}"
        return BrainResponse(
            text=text,
            path="local",
            held_back=list(decision.context.held_back),
            notices=notices,
        )
```

Notices append only when non-empty (clean cited answers are byte-for-byte unchanged); `if notice not in text` avoids double-appending a gap the model already self-tagged.

## Acceptance criteria

1. **Validator: empty retrieval → material gap.** `audit_answer("anything", (), ())` returns `material_gap=True`; its `notices()` contains `MATERIAL_GAP_NOTICE` → verify in `test_citation_check.py`.
2. **Validator: hallucinated citation flagged.** With one chunk `chunk_id="c1"`, `audit_answer("Claim [c1]. Other [c2].", (chunk_c1,), ())` returns `invalid_citations == ("c2",)` and `material_gap=False`; `[MATERIAL GAP]` text in an answer is NOT treated as a citation → verify.
3. **Validator: clean cited answer passes.** `audit_answer("Claim [c1].", (chunk_c1,), ())` returns `material_gap=False`, `invalid_citations=()`, `notices()==[]` → verify.
4. **`_rag_messages` forces the gap.** Calling `Brain._rag_messages(req, (), ())` returns a `system` message whose content contains `MATERIAL_GAP_NOTICE` and `CITE_INSTRUCTION` → verify.
5. **`_rag_messages` injects cite instruction when context present.** With one usable chunk, the system content contains both `SPOTLIGHT_INSTRUCTION`-derived text and `CITE_INSTRUCTION`, and the `[chunk_id]` block → verify.
6. **`respond` surfaces notices.** A `Brain` wired with a `FakeModelPort` returning `"See [ghost]."` and a single retrieved chunk `c1` yields `BrainResponse.notices` containing the citation warning for `ghost`, and the warning is appended to `.text`; a fake returning `"See [c1]."` yields `notices == []` and unchanged text → verify (model `complete` is fake, no network).
7. **No regression.** Full suite green (clean answers with present chunks are unchanged).

## Commands to run

```bash
uv run pytest -q tests/test_citation_check.py
uv run mypy
uv run pytest -q
```
