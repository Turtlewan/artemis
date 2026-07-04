"""Curated-write extraction for the local data spine (ADR-048).

A cheap verb prefilter (word-boundary) gates ONE haiku-class extraction that turns an owner
utterance into a curate decision: {op: save|forget|none, domain, content, referent}. op=none means
"not a curated write" -- the caller falls through to the normal ask path. Reads never pay the
model call. Dead until consumed: spec 2 (curate-write + referent) wires this into the ask route.

Trust boundary (ADR-048 #3): curated content is owner-typed -- extraction is routing, not
sanitization. `content` is the owner's words verbatim; the write path (spec 2) stores it verbatim.
Nothing here runs the ingest quarantine.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from artemis.ports.model import ModelPort
from artemis.types import Message

Op = Literal["save", "forget", "none"]

_log = logging.getLogger(__name__)

# Verbs that suggest a curated write (ADR-048 #4). Prefilter only -- the extraction decides; a
# non-write use of a verb costs one cheap call, a miss costs nothing (reads stay free).
CURATE_VERBS: tuple[str, ...] = ("save", "note", "remember", "add", "forget", "log", "track")

_SYSTEM = (
    "You extract a curated-write decision from one owner message for Artemis. Return only JSON "
    "matching the schema. op=save when the owner tells you to store/save/track/log an item; "
    "op=forget when they tell you to remove a stored item; op=none for anything else (questions, "
    "chat, requests to fetch or build something). domain is a short lowercase label for where the "
    "item belongs. REUSE one of the EXISTING DOMAINS when the item fits one semantically (a to-do "
    "belongs in an existing 'tasks'); invent a new label only when nothing existing fits. content "
    "is the owner's item text VERBATIM -- never rephrase, summarize, or correct it. referent is "
    "the owner's pointer to a previous result ('the second one', 'the dentist one', 'that') when "
    "the message points at one instead of typing content; else empty."
)


class CurateDecision(BaseModel):
    """One extracted curate decision. op=none -> not a curated write; caller falls through."""

    model_config = ConfigDict(frozen=True)

    op: Op
    domain: str = ""
    content: str = ""
    referent: str = ""

    @field_validator("domain")
    @classmethod
    def _normalize_domain(cls, value: str) -> str:
        return value.strip().lower()


_CURATE_SCHEMA: dict[str, Any] = CurateDecision.model_json_schema()

_NONE = CurateDecision(op="none")


def has_curate_verb(text: str) -> bool:
    """Cheap prefilter: True iff the utterance contains a curate verb as a whole word."""
    words = set(re.findall(r"[a-z']+", text.lower()))
    return any(verb in words for verb in CURATE_VERBS)


class CurateExtractor:
    """Turn an owner utterance into a curate decision via one gated haiku-class call."""

    def __init__(self, model: ModelPort) -> None:
        self._model = model

    async def extract(self, text: str, *, existing_domains: Sequence[str]) -> CurateDecision:
        """Return the curate decision for ``text``.

        op=none with NO model call when the prefilter does not fire; op=none (degrade, fall
        through) when the extraction call fails."""
        if not has_curate_verb(text):
            return _NONE
        domains = ", ".join(sorted(existing_domains)) or "(none yet)"
        try:
            response = await self._model.complete(
                messages=[
                    Message(role="system", content=_SYSTEM),
                    Message(
                        role="user",
                        content=f"EXISTING DOMAINS: {domains}\n\nMESSAGE: {text}",
                    ),
                ],
                model="haiku",
                response_schema=_CURATE_SCHEMA,
                temperature=0.0,
                max_tokens=1000,
            )
            decision = CurateDecision.model_validate_json(response.text)
        except Exception as exc:
            _log.warning("curate_extract_degraded reason=%s", type(exc).__name__)
            return _NONE
        if decision.op != "none" and not decision.domain:
            _log.warning("curate_extract_degraded reason=empty_domain op=%s", decision.op)
            return _NONE
        return decision
