"""Deterministic faithfulness floor for the main answer path.

Model-free. Catches (i) thin/empty retrieval (forces a [MATERIAL GAP] notice)
and (ii) hallucinated citations (a cited [chunk_id] absent from the provided
context). It does NOT catch confident uncited fabrication - that is the
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
    "invent a citation - instead tag that part of your answer with "
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
    """Chunks at/above the relevance bar - the evidence actually in the prompt."""
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
