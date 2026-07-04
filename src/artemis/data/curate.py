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
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, field_validator

from artemis.data.store import DataStore, Record
from artemis.expiry import evict_expired
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
        if decision.op == "save" and not decision.domain and not decision.referent:
            _log.warning("curate_extract_degraded reason=empty_domain op=save")
            return _NONE
        return decision


# --- Trusted curated write (ADR-048 #3): owner-typed or copied-from-sanitized -> BYPASSES the
# ingest quarantine. IngestService.save_row is NEVER called here; content is stored VERBATIM. ---

_CURATED_KIND = "note"
# Pinned literal: DataStore.has_foreign_source's `own_source` default must match this exactly --
# it is what marks a row as curated (vs synced) for the synced-domain guard.
_CURATED_SOURCE = "curate"
# fetched_at on a curated row = created/last-updated timestamp (owner-created rows have no fetch).
# Safe: has_foreign_source keeps curated rows out of synced domains, so this can never fake-fresh
# a stale sync.

# Referent state: the last read's ordered rows, held per session, TTL-evicted (mirrors invoke.py).
_RESULTS_TTL_SECONDS = 900.0
_RESULTS_MAX_ENTRIES = 128

_CONFIRM_SAVE = "Saved to {domain}."
_CONFIRM_FORGET = "Forgotten."
_NOT_FOUND = "I couldn't find what you're referring to -- nothing changed."
_AMBIGUOUS = "Multiple matches -- be more specific; nothing changed."
# Steers to a curated home (calibration showed reminder-saves target the synced calendar).
_SYNCED_READONLY = "{domain} is synced read-only -- try 'add a task' instead."
_SAVE_WHERE = "Save it where? -- e.g. 'save the second one to notes'."

# Ordinal words the referent resolver understands (deterministic, in code -- not a model call).
# "one" is deliberately excluded: it is the referent noun ("the second one", "the dentist one"),
# never an ordinal here.
_ORDINALS: dict[str, int] = {
    "first": 0,
    "1st": 0,
    "second": 1,
    "2nd": 1,
    "third": 2,
    "3rd": 2,
    "fourth": 3,
    "4th": 3,
    "fifth": 4,
    "5th": 4,
    "sixth": 5,
    "6th": 5,
    "seventh": 6,
    "7th": 6,
    "eighth": 7,
    "8th": 7,
    "ninth": 8,
    "9th": 8,
    "tenth": 9,
    "10th": 9,
}
# Referent filler words dropped before fuzzy content matching.
_REFERENT_STOPWORDS: frozenset[str] = frozenset(
    {"the", "a", "an", "one", "ones", "that", "this", "it", "please", "my", "of", "to"}
)


class CurateOutcome(BaseModel):
    """Result of a trusted curated write. `ok` False means nothing was written; `reply` is the
    owner-facing confirmation or honest 'couldn't find it'."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    reply: str


@dataclass
class ReadResults:
    """The ordered rows of the last successful local read, held per session for referent
    resolution. `created_at` (monotonic) drives TTL eviction via expiry.py."""

    rows: tuple[Record, ...]
    created_at: float = field(default_factory=time.monotonic)


def stash_results(store: dict[str, ReadResults], session_key: str, rows: Sequence[Record]) -> None:
    """Hold this session's last-read rows for referent resolution (lazy TTL/size eviction).
    Rows are stashed payload-STRIPPED (review FLAG 4): only sanitized_text is ever copied out, so
    the stash must not retain raw payloads at rest either."""
    evict_expired(store, ttl_seconds=_RESULTS_TTL_SECONDS, max_entries=_RESULTS_MAX_ENTRIES)
    store[session_key] = ReadResults(rows=tuple(replace(row, payload={}) for row in rows))


def stashed_rows(store: dict[str, ReadResults], session_key: str) -> tuple[Record, ...]:
    """The session's last-read rows, or () if none held."""
    entry = store.get(session_key)
    return entry.rows if entry is not None else ()


def resolve_referent(referent: str, rows: Sequence[Record]) -> Record | None:
    """Resolve an owner pointer against the last read's ordered rows.

    Ordinals/digits resolve deterministically by position. Otherwise, fuzzy content matching
    resolves only when exactly one row matches. Ambiguous or no match returns None.
    """
    if not rows:
        return None
    tokens = re.findall(r"[a-z0-9]+", referent.lower())
    if not tokens:
        return None
    for tok in tokens:
        if tok in _ORDINALS:
            idx = _ORDINALS[tok]
            return rows[idx] if 0 <= idx < len(rows) else None
        if tok.isdigit():
            idx = int(tok) - 1
            return rows[idx] if 0 <= idx < len(rows) else None
    content = [tok for tok in tokens if tok not in _REFERENT_STOPWORDS]
    if not content:
        return rows[0] if len(rows) == 1 else None
    matches = [row for row in rows if any(tok in row.sanitized_text.lower() for tok in content)]
    return matches[0] if len(matches) == 1 else None


def apply_curate(
    decision: CurateDecision,
    *,
    store: DataStore,
    last_rows: Sequence[Record],
    now: Callable[[], float] = time.time,
    new_key: Callable[[], str] = lambda: uuid4().hex,
) -> CurateOutcome:
    """Execute a curate decision as a trusted write."""
    domain = decision.domain.strip().lower()
    if decision.op == "none":
        return CurateOutcome(ok=False, reply=_NOT_FOUND)
    if decision.op == "forget":
        return _apply_forget(decision, domain, store, last_rows)
    if not domain:
        return CurateOutcome(ok=False, reply=_SAVE_WHERE)
    if store.has_foreign_source(domain):
        return CurateOutcome(ok=False, reply=_SYNCED_READONLY.format(domain=domain))
    return _apply_save(decision, domain, store, last_rows, now, new_key)


def _apply_save(
    decision: CurateDecision,
    domain: str,
    store: DataStore,
    last_rows: Sequence[Record],
    now: Callable[[], float],
    new_key: Callable[[], str],
) -> CurateOutcome:
    if decision.referent:
        row = resolve_referent(decision.referent, last_rows)
        if row is None:
            return CurateOutcome(ok=False, reply=_NOT_FOUND)
        content = row.sanitized_text
    else:
        content = decision.content.strip()
    if not content:
        return CurateOutcome(ok=False, reply=_NOT_FOUND)
    store.upsert(
        Record(
            domain=domain,
            kind=_CURATED_KIND,
            key=new_key(),
            payload={},
            sanitized_text=content,
            source=_CURATED_SOURCE,
            fetched_at=now(),
        )
    )
    return CurateOutcome(ok=True, reply=_CONFIRM_SAVE.format(domain=domain))


def _apply_forget(
    decision: CurateDecision,
    domain: str,
    store: DataStore,
    last_rows: Sequence[Record],
) -> CurateOutcome:
    if decision.referent:
        row = resolve_referent(decision.referent, last_rows)
        if row is None:
            return CurateOutcome(ok=False, reply=_NOT_FOUND)
        if store.has_foreign_source(row.domain):
            return CurateOutcome(ok=False, reply=_SYNCED_READONLY.format(domain=row.domain))
        store.delete(row.domain, row.kind, row.key)
        return CurateOutcome(ok=True, reply=_CONFIRM_FORGET)
    target = decision.content.strip()
    if not target:
        return CurateOutcome(ok=False, reply=_NOT_FOUND)
    domains = [domain] if domain else store.domains()
    matches: list[Record] = []
    for candidate in domains:
        matches.extend(store.query(domain=candidate, text=target, limit=2))
        if len(matches) > 1:
            return CurateOutcome(ok=False, reply=_AMBIGUOUS)
    if not matches:
        return CurateOutcome(ok=False, reply=_NOT_FOUND)
    row = matches[0]
    if store.has_foreign_source(row.domain):
        return CurateOutcome(ok=False, reply=_SYNCED_READONLY.format(domain=row.domain))
    store.delete(row.domain, row.kind, row.key)
    return CurateOutcome(ok=True, reply=_CONFIRM_FORGET)
