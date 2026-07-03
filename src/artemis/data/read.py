"""Native read path for the local data spine (ADR-046 #4).

An ask over a synced domain = an in-process store query + ONE small phrasing call (haiku-class):
no isolate, no per-read quarantine (data was sanitized once at ingest). Domain resolution is
deterministic (a keyword registry), NOT a model call. Target ~2-4s.

Security boundary: the phraser sees ONLY `Record.sanitized_text` (sanitized at ingest), never the
raw `payload` (structured, unsanitized) — that would reintroduce the injection the ingest
quarantine removed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from artemis.data.store import DataStore, Record
from artemis.ports.model import ModelPort
from artemis.types import Message

_log = logging.getLogger(__name__)

_PHRASER_SYSTEM = (
    "You are Artemis answering the owner from their own local data. You are given the owner's "
    "question and a list of stored records (already sanitized). Answer conversationally using ONLY "
    "these records; do not invent facts. If none are relevant, say you don't have anything "
    "matching. Keep it concise. Return only the required JSON."
)

_PHRASE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class _Phrased(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str


class DomainSpec(BaseModel):
    """A synced domain the read path can answer from. `keywords` route an ask to this domain;
    `freshness_s` is the max age of stored data still answered locally (older -> live path)."""

    model_config = ConfigDict(frozen=True)

    domain: str
    keywords: tuple[str, ...]
    limit: int = 50
    freshness_s: float = 900.0


class ReadResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    domain: str
    answer: str


# The synced-domain registry. A new synced domain adds an entry here (freshness config joins in
# Wave 2). Calendar is the first synced domain.
DEFAULT_DOMAINS: tuple[DomainSpec, ...] = (
    DomainSpec(
        domain="calendar",
        keywords=(
            "calendar",
            "schedule",
            "agenda",
            "meeting",
            "meetings",
            "event",
            "events",
            "appointment",
        ),
    ),
)


class ReadService:
    """Answer an ask from local synced data, or decline (None) to fall through to the ask path."""

    def __init__(
        self,
        store: DataStore,
        *,
        phraser: ModelPort,
        domains: Sequence[DomainSpec] = DEFAULT_DOMAINS,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._phraser = phraser
        self._domains = tuple(domains)
        self._now = now

    def resolve_domain(self, text: str) -> DomainSpec | None:
        lowered = text.lower()
        for spec in self._domains:
            if any(kw in lowered for kw in spec.keywords):
                return spec
        return None

    async def read(self, text: str) -> ReadResult | None:
        """Answer from local synced data, or None to fall through to the normal ask path.

        None when: no domain keyword matches, the domain has no stored rows, or the phrasing call
        fails (degrade to the normal path rather than return a wrong local answer)."""
        spec = self.resolve_domain(text)
        if spec is None:
            return None
        latest = self._store.latest_fetched_at(spec.domain)
        if latest is None or (self._now() - latest) > spec.freshness_s:
            # empty or stale -> fall through to the live path (don't answer from stale local data)
            return None
        rows = self._store.query(domain=spec.domain, limit=spec.limit)
        if not rows:
            return None
        answer = await self._phrase(text, rows)
        if answer is None:
            return None
        return ReadResult(domain=spec.domain, answer=answer)

    async def _phrase(self, text: str, rows: Sequence[Record]) -> str | None:
        records = _render_rows(rows)  # sanitized_text ONLY — never raw payload
        try:
            response = await self._phraser.complete(
                messages=[
                    Message(role="system", content=_PHRASER_SYSTEM),
                    Message(role="user", content=f"QUESTION: {text}\n\nRECORDS:\n{records}"),
                ],
                model="haiku",
                response_schema=_PHRASE_SCHEMA,
            )
            answer = _Phrased.model_validate_json(response.text).answer.strip()
            return answer or None
        except Exception:
            _log.warning("read_phrase_degraded domain_rows=%d", len(rows))
            return None


def _render_rows(rows: Sequence[Record]) -> str:
    return "\n".join(f"- [{r.kind}] {r.sanitized_text}" for r in rows)
