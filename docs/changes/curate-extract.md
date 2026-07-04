# curate-extract — curated-write extraction (curated machinery, spec 1 of 3)

**Identity:** The curate-extractor — a cheap verb prefilter gating ONE haiku-class extraction that
turns an owner utterance into `{op: save|forget|none, domain, content, referent}`, plus the live
domain list primitive `DataStore.domains()` it consumes. ADR-048 · design note
`docs/v2/curated-domains-machinery.md`. **Dead until consumed:** NO wiring into `ask_routes` here —
spec 2 (`curate-write + referent`) wires the extractor in with the trusted write. This spec adds the
`curate.py` module + `store.domains()` + tests only.

**Anti-fragmentation (ADR-048 #5):** the extraction prompt receives the live domain list and
instructs label REUSE when an existing domain fits semantically. **Verbatim rule (ADR-048 #3):**
extraction is routing, not sanitization — `content` carries the owner's words unrephrased; nothing
in this module runs the ingest quarantine. **Prefilter is word-boundary, not substring** ("what's my
address" must not fire on `add`; "check my notebook" must not fire on `note`). Degrade rule (house
idiom, matches `IntentRouter.classify`): extraction-call failure → `op=none` (fall through), never
an exception out.

## Files to change
| Op | Path |
|----|------|
| modify | `src/artemis/data/store.py` |
| create | `src/artemis/data/curate.py` |
| create | `tests/data/test_curate.py` |

(`domains()` is tested in `tests/data/test_curate.py` — its consumer context — to keep this spec at
3 files; do not also modify `tests/data/test_store.py`.)

## Exact changes

### Task 1 — `src/artemis/data/store.py` (modify): add `domains()`
Insert after `latest_fetched_at` (before `delete`):

```python
    def domains(self) -> list[str]:
        """Distinct domain labels present in the store -- the live domain list (ADR-048 #2).
        A domain exists iff it has rows; there is no registry."""
        rows = self._conn.execute("SELECT DISTINCT domain FROM records ORDER BY domain").fetchall()
        return [cast(str, row[0]) for row in rows]
```

No other changes to the file (`cast` is already imported).

### Task 2 — `src/artemis/data/curate.py` (create)
Full module:

```python
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
```

Note: the extractor takes `existing_domains` as a parameter (it does not hold a `DataStore`) — the
spec-2 caller fetches `store.domains()` at each ask. Keeps this module store-independent and the
tests hermetic.

**Review notes folded (2026-07-04, apex-security + apex-ai-systems — no BLOCKs):**
- `op=save|forget` with an empty `domain` is an invalid extracted state → degrades to `op=none`
  (never reaches spec 2's trusted writer).
- `max_tokens=1000` (raised from 300): `content` is verbatim and may be long (dictated notes);
  the budget is a tunable — a save exceeding it fails schema-validation and degrades to `op=none`
  (accepted v1 behavior).
- `CURATE_VERBS` is a v1 seed list, expected to grow from observed prefilter false-negatives.
- **Contract carried to spec 2/3:** domain-label normalization (strip+lower) must ALSO be enforced
  at the store-write boundary — the extractor's validator alone cannot prevent label fragmentation
  from other write paths.
- **Required follow-up before spec 2 wires this live:** a small golden-set calibration of the
  extractor on real haiku (borderline save-vs-none utterances) — webtool-eval precedent.

### Task 3 — `tests/data/test_curate.py` (create)
Fake model mirrors `FakePhraser` in `tests/data/test_read.py` (records calls/models; configurable
JSON reply / raises; builds `ModelResponse`/`Usage` the same way — confirm field names against
`src/artemis/types.py`). Async tests are plain `async def` (`asyncio_mode = "auto"`).

Cover every criterion below; sketch:

```python
import json
from collections.abc import Sequence

from artemis.data.curate import CURATE_VERBS, CurateDecision, CurateExtractor, has_curate_verb
from artemis.data.store import DataStore, Record
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    def __init__(self, *, reply: dict[str, str] | None = None, raises: Exception | None = None) -> None:
        self._reply = reply or {"op": "none", "domain": "", "content": "", "referent": ""}
        self._raises = raises
        self.calls: list[list[Message]] = []
        self.models: list[str | None] = []

    async def complete(self, *, messages, model=None, response_schema=None, temperature=0.7, max_tokens=None):
        self.calls.append(list(messages))
        self.models.append(model)
        if self._raises is not None:
            raise self._raises
        return ModelResponse(text=json.dumps(self._reply), model_id=model or "fake", structured=None,
                             finish_reason="stop", usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2))


SAVE_REPLY = {"op": "save", "domain": "tasks", "content": "renew passport by Friday", "referent": ""}
```

Tests:
1. `test_prefilter_word_boundary` — `has_curate_verb("add a task: renew passport")` is True;
   `has_curate_verb("what's my address")` and `has_curate_verb("check my notebook")` and
   `has_curate_verb("what's on my calendar")` are False. Also assert `CURATE_VERBS` is exactly the
   ADR-048 #4 set.
2. `test_extract_no_verb_skips_model_call` — `extract("what's the weather", existing_domains=[])`
   returns `op == "none"` and `FakeModel.calls == []` (zero model calls).
3. `test_extract_save` — with `FakeModel(reply=SAVE_REPLY)`,
   `extract("add a task: renew passport by Friday", existing_domains=["calendar"])` returns the
   decision verbatim (`op=save`, `domain="tasks"`, content unrephrased) and `models == ["haiku"]`.
4. `test_prompt_carries_live_domains_and_reuse_rule` — after an extract with
   `existing_domains=["calendar", "tasks"]`: user message contains `"calendar, tasks"` and the
   raw utterance; system message contains `"REUSE"` and `"VERBATIM"`. With `existing_domains=[]`
   the user message contains `"(none yet)"`.
5. `test_extract_model_failure_degrades_to_none` — `FakeModel(raises=RuntimeError("down"))` →
   `op == "none"` (no exception).
6. `test_domain_label_normalized` — reply with `"domain": "  Tasks "` → decision `domain == "tasks"`.
7. `test_store_domains_live_list` — `DataStore()` (in-memory): `domains() == []`; after upserting
   two `tasks` rows and one `calendar` row (reuse the `Record` seeding shape from
   `tests/data/test_read.py`), `domains() == ["calendar", "tasks"]` (distinct, sorted).
8. `test_empty_domain_save_degrades_to_none` — `FakeModel(reply={"op": "save", "domain": "",
   "content": "x", "referent": ""})` → decision `op == "none"`.

## Acceptance criteria
1. `has_curate_verb` fires on whole words only, case-insensitively; `CURATE_VERBS` = save/note/remember/add/forget/log/track. → `test_prefilter_word_boundary`
2. No curate verb → `op=none` with ZERO model calls (reads stay free). → `test_extract_no_verb_skips_model_call`
3. A save utterance extracts via one `model="haiku"` call, content verbatim. → `test_extract_save`
4. The prompt carries the live domain list + the label-REUSE + VERBATIM instructions; empty list renders `(none yet)`. → `test_prompt_carries_live_domains_and_reuse_rule`
5. Extraction-call failure degrades to `op=none`, never raises. → `test_extract_model_failure_degrades_to_none`
6. `domain` labels are normalized (strip + lowercase). → `test_domain_label_normalized`
7. `DataStore.domains()` returns the distinct, sorted live domain list; `[]` on an empty store. → `test_store_domains_live_list`
8. `op=save|forget` with an empty `domain` degrades to `op=none`. → `test_empty_domain_save_degrades_to_none`
9. Whole-project gates clean (commands below).

## Commands to run
```
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q
```
