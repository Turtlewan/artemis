# data-read — native local read path (Wave 1b)

**Identity:** The native read path — an ask over a synced domain = an in-process store query + ONE
small phrasing call (haiku-class), no isolate, no per-read quarantine (data was sanitized once at
ingest). ADR-046 #4 · design note `docs/v2/local-data-spine.md`. Depends on `data-store` (Wave 0).

**Domain resolution is deterministic (a keyword registry), NOT a model call** — ADR-046 #4 budgets
exactly one model call, for phrasing. **Security boundary:** the phraser sees ONLY `sanitized_text`
(sanitized at ingest), NEVER the raw `payload` (structured, unsanitized) — feeding raw payload to an
LLM would bypass the ingest quarantine (ADR-046 #3). Dead-until-consumed: the ask-route wiring goes
live in Wave 2 *with* the calendar fetcher (so the local-read path activates exactly when the store
has synced data). This spec adds the `ReadService` module + tests only.

## Files to change
| Op | Path |
|----|------|
| create | `src/artemis/data/read.py` |
| create | `tests/data/test_read.py` |

## Exact changes

### Task 1 — `src/artemis/data/read.py` (create)
Full module:

```python
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
    """A synced domain the read path can answer from. `keywords` route an ask to this domain."""

    model_config = ConfigDict(frozen=True)

    domain: str
    keywords: tuple[str, ...]
    limit: int = 50


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
```

### Task 2 — `tests/data/test_read.py` (create)
Fake phraser mirrors the `FakeReader` in `tests/data/test_ingest.py` (records calls; configurable
answer / raises; builds `ModelResponse`/`Usage` the same way). Cover every criterion:

```python
import json
from collections.abc import Sequence

from artemis.data.read import DEFAULT_DOMAINS, DomainSpec, ReadService
from artemis.data.store import DataStore, Record
from artemis.types import Message, ModelResponse, Usage


class FakePhraser:
    def __init__(self, *, answer: str = "You have Standup at 9am.", raises: Exception | None = None) -> None:
        self._answer = answer
        self._raises = raises
        self.calls: list[list[Message]] = []
        self.models: list[str | None] = []

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append(list(messages))
        self.models.append(model)
        if self._raises is not None:
            raise self._raises
        return ModelResponse(
            text=json.dumps({"answer": self._answer}),
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def _seed(store: DataStore, **over: object) -> None:
    base = dict(
        domain="calendar", kind="event", key="e1", payload={"secret_marker": "PAYLOAD_ONLY"},
        sanitized_text="Standup at 9am on 2026-08-22", source="today-calendar", fetched_at=100.0,
        owner_fields={},
    )
    base.update(over)
    store.upsert(Record(**base))  # type: ignore[arg-type]


def test_resolve_domain() -> None:
    svc = ReadService(DataStore(), phraser=FakePhraser())
    assert svc.resolve_domain("what's on my CALENDAR today").domain == "calendar"  # type: ignore[union-attr]
    assert svc.resolve_domain("any meetings tomorrow?").domain == "calendar"  # type: ignore[union-attr]
    assert svc.resolve_domain("what's the weather") is None


async def test_read_no_domain_match_returns_none() -> None:
    svc = ReadService(DataStore(), phraser=FakePhraser())
    assert await svc.read("what's the weather in Tokyo") is None


async def test_read_empty_store_returns_none() -> None:
    svc = ReadService(DataStore(), phraser=FakePhraser())
    assert await svc.read("what's on my calendar") is None  # domain matched but no rows


async def test_read_phrases_from_rows() -> None:
    store = DataStore()
    _seed(store)
    phraser = FakePhraser(answer="You have Standup at 9am.")
    svc = ReadService(store, phraser=phraser)
    result = await svc.read("what's on my calendar")
    assert result is not None
    assert result.domain == "calendar"
    assert result.answer == "You have Standup at 9am."
    assert phraser.models == ["haiku"]


async def test_phraser_sees_sanitized_text_not_payload() -> None:
    store = DataStore()
    _seed(store)  # payload has secret_marker=PAYLOAD_ONLY; sanitized_text does not
    phraser = FakePhraser()
    svc = ReadService(store, phraser=phraser)
    await svc.read("what's on my calendar")
    user_content = phraser.calls[0][1].content
    assert "Standup at 9am on 2026-08-22" in user_content  # sanitized_text is present
    assert "PAYLOAD_ONLY" not in user_content  # raw payload is NOT fed to the LLM


async def test_phraser_failure_returns_none() -> None:
    store = DataStore()
    _seed(store)
    svc = ReadService(store, phraser=FakePhraser(raises=RuntimeError("down")))
    assert await svc.read("what's on my calendar") is None  # degrade to fall-through


def test_default_domains_include_calendar() -> None:
    assert any(d.domain == "calendar" for d in DEFAULT_DOMAINS)
```

Note: match the async-test convention of the repo's other async tests (under `asyncio_mode = "auto"`
plain `async def test_...` is collected; add `@pytest.mark.asyncio` only if the sibling data tests use
it). Confirm `Usage` field names against `src/artemis/types.py` (Wave 1a used
`prompt_tokens`/`completion_tokens`/`total_tokens`).

## Acceptance criteria
1. `resolve_domain` matches a domain by keyword case-insensitively; returns `None` for an unrelated ask. → `test_resolve_domain`
2. `read` returns `None` when no domain keyword matches (fall through). → `test_read_no_domain_match_returns_none`
3. `read` returns `None` when the domain matches but the store has no rows (fall through). → `test_read_empty_store_returns_none`
4. `read` queries the store and phrases the rows, returning `ReadResult(domain, answer)` with `model="haiku"`. → `test_read_phrases_from_rows`
5. The phraser prompt contains `sanitized_text` but NOT the raw `payload` (injection boundary). → `test_phraser_sees_sanitized_text_not_payload`
6. A phrasing-call failure makes `read` return `None` (degrade, don't answer wrongly). → `test_phraser_failure_returns_none`
7. `DEFAULT_DOMAINS` includes `calendar`. → `test_default_domains_include_calendar`
8. Whole-project `uv run mypy src/` clean (strict) and `uv run ruff check` clean.

## Commands to run
```
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -q tests/data/
uv run pytest -q
```
