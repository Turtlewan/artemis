# curate-write-referent — trusted curated write + referent resolution + ask wiring (curated machinery, spec 2 of 3)

**Identity:** The curated write engine — a thin **trusted** write path (`op=save` → `store.upsert` VERBATIM, no ingest quarantine; `op=forget` → `store.delete`), per-session **referent** state (the last read's ordered rows, TTL-evicted) with ordinal + fuzzy resolution, and the `ask_routes` wiring that runs the extractor (spec 1) BEFORE the read short-circuit. ADR-048 (#3, #6) · design note `docs/v2/curated-domains-machinery.md` (machinery parts 2+3). **Consumes spec 1:** `CurateExtractor.extract`, `CurateDecision`, `has_curate_verb` (in `curate.py`) and `DataStore.domains()` are treated as EXISTING.

**Live haiku calibration of the built spec-1 extractor ran 2026-07-04 — 22/24 (findings: `docs/findings/curate-extract-calibration-2026-07-04.md`). Both fails root-caused to spec 1's empty-domain→degrade rule collapsing LEGITIMATE referent utterances ("save the second one", "forget what i said about the plumber") to `op=none` — the domain is rightly unknown at extraction time. Fixed HERE: Task 3a amends the spec-1 degrade rule (degrade only on `op=save` with BOTH domain and referent empty); `apply_curate` handles the two newly-reachable states (unscoped forget; referent-save with no stated target).**

**Dual domain review (apex-security + apex-data) ran 2026-07-04 — 2 BLOCKs + 4 FLAGs, all folded below; no open BLOCKs.** Rulings now in the spec: (1) ambiguous no-referent forget REFUSES (query `limit=2`, delete only on exactly-one match); (2) a **synced-domain guard** — `DataStore.has_foreign_source` — makes `apply_curate` refuse BOTH save and forget on any domain holding rows from a non-`curate` source (closes freshness-ceiling masking, commingled query results, and forget-then-resurrect-on-next-sync); (3) domain-label normalization moves into `DataStore.upsert` — the single chokepoint NO write path (ingest included) can bypass; (4) the referent stash holds payload-STRIPPED records; (5) **`fetched_at` semantics for curated rows:** `fetched_at` = created/last-updated timestamp for owner-created rows (no fetch exists) — safe now that the synced-domain guard prevents commingling with synced domains.

> **Split-rule deviation (flagged for reviewer):** this spec touches **7 files** (5 production + 2 tests), over the ≤3-files / ≤4-with-tests house target. The feature legitimately spans five production seams that must move together — the store chokepoint + synced-domain guard (`store.py`), the write engine (`curate.py`), the read seam that must expose the rows a read answered from (`read.py`), the ask wiring (`ask_routes.py`), and one line of app-state init (`app.py`) — plus two correctly-homed test files (data-layer unit + api wiring). Splitting further would ship a half-wired dead path. No task exceeds a single logical phase.

## Files to change
| Op | Path |
|----|------|
| modify | `src/artemis/data/store.py` |
| modify | `src/artemis/data/read.py` |
| modify | `src/artemis/data/curate.py` |
| modify | `src/artemis/api/app.py` |
| modify | `src/artemis/api/ask_routes.py` |
| create | `tests/data/test_curate_write.py` |
| modify | `tests/api/test_ask_routes.py` |

## Exact changes

### Task 1 — `src/artemis/data/store.py` (modify): normalization chokepoint + synced-domain guard
**a.** Normalize the domain label inside `upsert` itself — the single chokepoint no write path (ingest, curate, fetcher) can bypass, so labels cannot fragment (ADR-048 #5; review FLAG 3). Replace the start of `upsert` and use the normalized value in the params tuple:
```python
    def upsert(self, record: Record) -> None:
        """Insert, or on (domain,kind,key) conflict update feed fields only -- owner_fields survive.
        The domain label is normalized (strip+lower) HERE -- the one chokepoint every write path
        goes through, so labels cannot fragment (ADR-048 #5)."""
        domain = record.domain.strip().lower()
        self._conn.execute(
            "INSERT INTO records"
            " (domain, kind, key, payload, sanitized_text, source, fetched_at, owner_fields)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(domain, kind, key) DO UPDATE SET"
            "  payload=excluded.payload, sanitized_text=excluded.sanitized_text,"
            "  source=excluded.source, fetched_at=excluded.fetched_at",
            (
                domain,
                record.kind,
                record.key,
                json.dumps(record.payload),
                record.sanitized_text,
                record.source,
                record.fetched_at,
                json.dumps(record.owner_fields),
            ),
        )
        self._conn.commit()
```

**b.** Add the synced-domain guard primitive after `domains()` (spec 1 placed `domains()` after `latest_fetched_at`):
```python
    def has_foreign_source(self, domain: str, *, own_source: str = "curate") -> bool:
        """True iff `domain` holds any row written by a non-curate source -- the synced-domain
        guard (review BLOCK 2): curated CRUD must refuse such domains. A curated fetched_at=now()
        in a synced domain would fake-fresh a stale sync; a forget would silently resurrect on
        the next sync."""
        row = self._conn.execute(
            "SELECT 1 FROM records WHERE domain=? AND source != ? LIMIT 1", (domain, own_source)
        ).fetchone()
        return row is not None
```
No other changes to the file.

### Task 2 — `src/artemis/data/read.py` (modify): expose the answered rows on `ReadResult`
The referent needs the exact ordered rows a read answered from. Add them to the read result (the only clean seam — the read already holds them). `Record` is already imported.

**a.** Replace the `ReadResult` class:
```python
class ReadResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    domain: str
    answer: str
    rows: tuple[Record, ...] = ()
```
(`arbitrary_types_allowed=True` lets the frozen model hold the stdlib-dataclass `Record` by identity — no revalidation/copy of the row contents.)

**b.** In `ReadService.read`, carry the rows into the result. Change the final return only:
```python
        answer = await self._phrase(text, rows)
        if answer is None:
            return None
        return ReadResult(domain=spec.domain, answer=answer, rows=tuple(rows))
```
No other change to `read.py` (existing callers read `.answer`/`.domain`; the new field defaults to `()`).

### Task 3 — `src/artemis/data/curate.py` (modify): trusted write + referent + per-session results state

**a. Amend the spec-1 degrade rule in `CurateExtractor.extract` (calibration fix).** The built spec-1 code ends `extract` with:
```python
        if decision.op != "none" and not decision.domain:
            _log.warning("curate_extract_degraded reason=empty_domain op=%s", decision.op)
            return _NONE
        return decision
```
Replace with — degrade on empty domain ONLY when `op=save` AND `referent` is also empty; `op=forget` passes through with an empty domain, and `op=save` with a non-empty referent passes through with an empty domain (`apply_curate` handles both, below):
```python
        if decision.op == "save" and not decision.domain and not decision.referent:
            _log.warning("curate_extract_degraded reason=empty_domain op=save")
            return _NONE
        return decision
```

**b. Append the write engine + referent machinery.** Add these imports to the existing import block:
```python
import time
from collections.abc import Callable, Sequence  # Sequence already imported; add Callable
from dataclasses import dataclass, field, replace
from uuid import uuid4

from artemis.data.store import DataStore, Record
from artemis.expiry import evict_expired
```

Then append:
```python
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
    "first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "sixth": 5, "6th": 5,
    "seventh": 6, "7th": 6, "eighth": 7, "8th": 7, "ninth": 8, "9th": 8,
    "tenth": 9, "10th": 9,
}
# Referent filler words dropped before fuzzy content matching.
_REFERENT_STOPWORDS: frozenset[str] = frozenset(
    {"the", "a", "an", "one", "ones", "that", "this", "it", "please", "my", "of", "to"}
)


class CurateOutcome(BaseModel):
    """Result of a trusted curated write. `ok` False -> nothing was written; `reply` is the
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
    store[session_key] = ReadResults(rows=tuple(replace(r, payload={}) for r in rows))


def stashed_rows(store: dict[str, ReadResults], session_key: str) -> tuple[Record, ...]:
    """The session's last-read rows, or () if none held."""
    entry = store.get(session_key)
    return entry.rows if entry is not None else ()


def resolve_referent(referent: str, rows: Sequence[Record]) -> Record | None:
    """Resolve an owner pointer ('the second one' / 'the dentist one' / 'that') against the last
    read's ordered rows. Ordinals/digits resolve deterministically by position; otherwise a fuzzy
    match on content words against each row's sanitized_text, resolving only when EXACTLY one row
    matches (ambiguous or no match -> None). A bare filler pointer ('that') resolves iff there is
    exactly one row."""
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
    content = [t for t in tokens if t not in _REFERENT_STOPWORDS]
    if not content:
        return rows[0] if len(rows) == 1 else None
    matches = [r for r in rows if any(c in r.sanitized_text.lower() for c in content)]
    return matches[0] if len(matches) == 1 else None


def apply_curate(
    decision: CurateDecision,
    *,
    store: DataStore,
    last_rows: Sequence[Record],
    now: Callable[[], float] = time.time,
    new_key: Callable[[], str] = lambda: uuid4().hex,
) -> CurateOutcome:
    """Execute a curate decision as a TRUSTED write. op=save -> upsert verbatim; op=forget ->
    delete. Domain label is normalized (strip+lower) here before the guard query (upsert normalizes
    again -- the chokepoint; this copy keeps the guard + reply consistent). Refuses BOTH ops on a
    domain holding non-curate-source rows (synced-domain guard, review BLOCK 2). An empty domain is
    a legitimate extracted state post-calibration: forget resolves via referent/cross-domain search;
    a save with no stated target refuses honestly. op=none is a no-op guard (the caller never
    routes it here)."""
    domain = decision.domain.strip().lower()
    if decision.op == "none":
        return CurateOutcome(ok=False, reply=_NOT_FOUND)
    if decision.op == "forget":
        # Forget is domain-optional: the referent branch resolves against the stash (guarding the
        # RESOLVED row's domain); the content branch searches the stated domain, or ALL live
        # domains when none was stated.
        return _apply_forget(decision, domain, store, last_rows)
    if not domain:
        # save with a referent but no stated target domain (calibration fix): never guess -- refuse.
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
        content = row.sanitized_text  # copy the SANITIZED text only -- never the raw payload
    else:
        content = decision.content.strip()
    if not content:
        return CurateOutcome(ok=False, reply=_NOT_FOUND)
    store.upsert(
        Record(
            domain=domain,
            kind=_CURATED_KIND,
            key=new_key(),
            payload={},  # curated rows carry no raw payload; sanitized_text is the content
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
        # The resolved row may live in a DIFFERENT domain than decision.domain (stashed read rows
        # keep their origin domain) -- re-apply the synced-domain guard to the row's own domain.
        if store.has_foreign_source(row.domain):
            return CurateOutcome(ok=False, reply=_SYNCED_READONLY.format(domain=row.domain))
        store.delete(row.domain, row.kind, row.key)
        return CurateOutcome(ok=True, reply=_CONFIRM_FORGET)
    target = decision.content.strip()
    if not target:
        return CurateOutcome(ok=False, reply=_NOT_FOUND)
    # Unambiguous-or-refuse (review BLOCK 1, mirrors resolve_referent's contract): collect up to
    # TWO matches and delete only when exactly one row matches -- never delete the newest of
    # several. An empty domain (calibration fix) searches ALL live domains under the same contract.
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
```

### Task 4 — `src/artemis/api/app.py` (modify): init per-session referent state
Directly after `app.state.invokes = {}` (line 131), add:
```python
    app.state.last_results = {}  # session_key -> curate.ReadResults (last read's rows; referent)
```
No import change (dict literal). Nothing else in `app.py` changes.

### Task 5 — `src/artemis/api/ask_routes.py` (modify): wire curate BEFORE the read short-circuit
**a.** Add the import (below the existing `from artemis.data.store import DataStore`):
```python
from artemis.data.curate import (
    CurateExtractor,
    ReadResults,
    apply_curate,
    stash_results,
    stashed_rows,
)
```

**b.** Add three dependency providers next to `_read_service` / `_invokes`:
```python
def _data_store(request: Request) -> DataStore:
    store: DataStore = request.app.state.data_store
    return store


def _curate_extractor(request: Request) -> CurateExtractor:
    del request
    # Dedicated Haiku-capable claude_code port -- same rationale as `_intent` (never the shared
    # codex-primary router, which would reach an unknown "haiku" model and degrade every call).
    return CurateExtractor(ModelClient(ClaudeCodeProvider(), model_default="haiku"))


def _last_results(request: Request) -> dict[str, ReadResults]:
    results: dict[str, ReadResults] = request.app.state.last_results
    return results
```

**c.** In `_invoke_or_routed_answer`, add four keyword-only params and insert the curate check FIRST, then stash rows after a successful read. Replace the signature + the leading read block:
```python
async def _invoke_or_routed_answer(
    *,
    read_service: ReadService,
    selector: CapabilitySelector,
    capability_store: FileCapabilityStore,
    invokes: dict[str, InvokeState],
    model: ModelPort,
    intent_router: IntentRouter,
    secrets: SecretStorePort,
    text: str,
    data_store: DataStore,
    curate: CurateExtractor,
    last_results: dict[str, ReadResults],
    session_key: str,
) -> AskResponse:
    # Curated-write check FIRST (ADR-048 #4): one gated haiku call only on likely-writes (the
    # extractor's own prefilter makes reads free); op=none falls through to the read path unchanged.
    decision = await curate.extract(text, existing_domains=data_store.domains())
    if decision.op != "none":
        outcome = apply_curate(
            decision, store=data_store, last_rows=stashed_rows(last_results, session_key)
        )
        return AskResponse(text=outcome.reply, path="curate", tool_used=None, escalated=False)

    try:
        local = await read_service.read(text)
    except Exception:
        local = None
    if local is not None:
        stash_results(last_results, session_key, local.rows)  # hold rows for a later referent
        return AskResponse(text=local.answer, path="local_read", tool_used=None, escalated=False)
```
(The rest of `_invoke_or_routed_answer` — selector/invoke/routed-answer — is unchanged. `curate.extract` degrades to `op=none` internally and never raises, so it needs no try/except.)

**d.** Thread the new dependencies through both endpoints. In `ask`, rename `_principal` → `principal`, add the deps, and pass them:
```python
@router.post("/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    principal: Principal = Depends(require_session),
    model: ModelPort = Depends(_router),
    intent_router: IntentRouter = Depends(_intent),
    selector: CapabilitySelector = Depends(_selector),
    capability_store: FileCapabilityStore = Depends(_capability_store),
    invokes: dict[str, InvokeState] = Depends(_invokes),
    secrets: SecretStorePort = Depends(_secrets),
    read_service: ReadService = Depends(_read_service),
    data_store: DataStore = Depends(_data_store),
    curate: CurateExtractor = Depends(_curate_extractor),
    last_results: dict[str, ReadResults] = Depends(_last_results),
) -> AskResponse:
    return await _invoke_or_routed_answer(
        read_service=read_service,
        selector=selector,
        capability_store=capability_store,
        invokes=invokes,
        model=model,
        intent_router=intent_router,
        secrets=secrets,
        text=req.text,
        data_store=data_store,
        curate=curate,
        last_results=last_results,
        session_key=principal.device_id,
    )
```
Apply the identical change to `ask_stream` (rename `_principal` → `principal`, add the same three `Depends`, and pass `data_store=/curate=/last_results=/session_key=principal.device_id` into its `_invoke_or_routed_answer` call).

### Task 6 — `tests/data/test_curate_write.py` (create): unit tests (hermetic)
Reuse the `FakePhraser`/`_seed` idioms from `tests/data/test_read.py` and the `FakeModel` shape from `tests/data/test_curate.py`. In-memory `DataStore()`; async tests are plain `async def` (`asyncio_mode = "auto"`). Build `CurateDecision` directly for write-unit tests; use `CurateDecision.model_construct(...)` where a test must inject a NON-normalized domain (bypassing the validator) to prove the write-boundary normalization.

Helper for building rows (mirror `_seed`):
```python
def _row(**over: object) -> Record:
    base = dict(
        domain="calendar", kind="event", key="e1", payload={"secret": "PAYLOAD_ONLY"},
        sanitized_text="Dentist at 3pm", source="today-calendar", fetched_at=100.0, owner_fields={},
    )
    base.update(over)
    return Record(**base)  # type: ignore[arg-type]
```

**Curated-row seeding note:** any row seeded as *curated* MUST use `source="curate"` — the `_row` default (`source="today-calendar"`) is a FOREIGN source and trips the synced-domain guard (that is what tests 14–16 assert deliberately).

Tests:
1. `test_save_verbatim_bypasses_quarantine` — `apply_curate(CurateDecision(op="save", domain="tasks", content="renew passport by Friday"), store=store, last_rows=(), now=lambda: 1.0)` → `outcome.ok` and `outcome.reply == "Saved to tasks."`; `store.query(domain="tasks")` has one row with `sanitized_text == "renew passport by Friday"` (unrephrased), `payload == {}`, `source == "curate"`, `kind == "note"`. (No `IngestService` import anywhere in the module — assert by absence in review; the row content proves verbatim.)
2. `test_save_domain_normalized_at_write_boundary` — `apply_curate(CurateDecision.model_construct(op="save", domain="  Tasks ", content="x", referent=""), store=store, last_rows=())` → stored row's `domain == "tasks"` and reply `"Saved to tasks."`.
3. `test_save_empty_content_no_write` — `CurateDecision(op="save", domain="tasks", content="")` (no referent) → `not outcome.ok`, reply == `_NOT_FOUND`, `store.query(domain="tasks") == []`.
4. `test_forget_by_content_deletes_match` — seed ONE curated row `store.upsert(_row(domain="tasks", kind="note", key="k1", sanitized_text="buy milk", payload={}, source="curate"))`; `apply_curate(CurateDecision(op="forget", domain="tasks", content="milk"), store=store, last_rows=())` → `outcome.ok`, reply `"Forgotten."`, `store.query(domain="tasks") == []`.
5. `test_forget_no_match_no_write` — empty store, forget content `"nope"` → `not outcome.ok`, reply `_NOT_FOUND`.
6. `test_resolve_ordinal` — `rows = [_row(key="a"), _row(key="b"), _row(key="c")]`; `resolve_referent("the second one", rows).key == "b"`; `"the first"` → `"a"`; `"the 3rd one"` → `"c"`; `"the fifth one"` → `None` (out of range).
7. `test_resolve_fuzzy_unambiguous` — `rows = [_row(key="d", sanitized_text="Dentist at 3pm"), _row(key="g", sanitized_text="Gym session")]`; `resolve_referent("the dentist one", rows).key == "d"`; `"the yoga one"` → `None`; ambiguous (`[_row(sanitized_text="Team meeting"), _row(sanitized_text="1:1 meeting")]`, referent `"the meeting one"`) → `None`.
8. `test_resolve_bare_pointer_single_row` — `resolve_referent("that", [_row(key="only")]).key == "only"`; with two rows → `None`.
9. `test_save_referent_copies_sanitized_not_payload` — `last_rows = (_row(sanitized_text="Dentist at 3pm", payload={"secret": "PAYLOAD_ONLY"}),)`; `apply_curate(CurateDecision(op="save", domain="tasks", referent="the dentist one"), store=store, last_rows=last_rows, now=lambda: 1.0)` → new `tasks` row `sanitized_text == "Dentist at 3pm"`, `payload == {}` (marker absent).
10. `test_save_referent_unresolved_no_write` — `last_rows = (_row(sanitized_text="Dentist at 3pm"),)`; referent `"the plumber one"` → `not outcome.ok`, reply `_NOT_FOUND`, `store.query(domain="tasks") == []`.
11. `test_forget_referent_deletes_exact_row` — seed a CURATED row `store.upsert(_row(domain="tasks", kind="note", key="k1", sanitized_text="buy milk", payload={}, source="curate"))`; `last_rows = (store.get("tasks","note","k1"),)`; `apply_curate(CurateDecision(op="forget", domain="tasks", referent="that"), store=store, last_rows=last_rows)` → `outcome.ok`, `store.get("tasks","note","k1") is None`.
12. `test_stash_strips_payload` — `state: dict[str, ReadResults] = {}`; `stash_results(state, "dev", (_row(payload={"secret": "PAYLOAD_ONLY"}),))`; `stashed_rows(state, "dev")` has len 1, `[0].payload == {}` (stripped at stash time), `[0].sanitized_text == "Dentist at 3pm"` (preserved); `stashed_rows(state, "other") == ()`.
13. `test_read_exposes_rows` — seed `_seed(store)` (calendar row), `svc = ReadService(store, phraser=FakePhraser(), now=lambda: 100.0)`; `result = await svc.read("what's on my calendar")`; `result is not None`, `len(result.rows) == 1`, `result.rows[0].sanitized_text == "Standup at 9am on 2026-08-22"`.
14. `test_forget_ambiguous_content_refuses` — seed TWO curated rows matching "milk" (`_row(domain="tasks", kind="note", key="k1", sanitized_text="buy milk", payload={}, source="curate")` and `key="k2", sanitized_text="milk the feedback"`); `apply_curate(CurateDecision(op="forget", domain="tasks", content="milk"), store=store, last_rows=())` → `not outcome.ok`, reply == `_AMBIGUOUS`, and `len(store.query(domain="tasks")) == 2` (BOTH rows still present — nothing deleted).
15. `test_save_into_synced_domain_refused` — seed `store.upsert(_row(domain="calendar", key="e1", source="calendar-sync"))`; `apply_curate(CurateDecision(op="save", domain="calendar", content="fake event"), store=store, last_rows=())` → `not outcome.ok`, reply == `"calendar is synced read-only -- try 'add a task' instead."` (steers to a curated home), `len(store.query(domain="calendar")) == 1` (no write).
16. `test_forget_referent_synced_row_refused` — seed `store.upsert(_row(domain="calendar", key="e1", source="calendar-sync"))`; `last_rows = (store.get("calendar","event","e1"),)`; `apply_curate(CurateDecision(op="forget", domain="calendar", referent="that"), store=store, last_rows=last_rows)` → `not outcome.ok`, reply mentions synced read-only, `store.get("calendar","event","e1") is not None` (row survives).
17. `test_upsert_normalizes_domain_chokepoint` — `store.upsert(_row(domain="  Tasks ", kind="note", key="k1", source="curate"))` → `len(store.query(domain="tasks")) == 1` and `store.domains() == ["tasks"]` (normalized at the store chokepoint, no fragment label).
18. `test_extract_referent_save_empty_domain_passes_through` — reuse the extract-level `FakeModel` idiom (`tests/data/test_curate.py`): `FakeModel(reply={"op": "save", "domain": "", "content": "", "referent": "the second one"})`; `extract("save the second one", existing_domains=["tasks"])` → `op == "save"`, `referent == "the second one"` (NO degrade — calibration fix).
19. `test_extract_forget_empty_domain_passes_through` — `FakeModel(reply={"op": "forget", "domain": "", "content": "the plumber thing", "referent": ""})`; `extract("forget what i said about the plumber", existing_domains=["tasks"])` → `op == "forget"` (passes through with empty domain).
20. `test_extract_plain_save_empty_domain_still_degrades` — `FakeModel(reply={"op": "save", "domain": "", "content": "x", "referent": ""})` → `op == "none"` (spec 1's `test_empty_domain_save_degrades_to_none` covers the same contract and still passes unchanged).
21. `test_forget_unscoped_cross_domain_exactly_one` — seed curated rows in TWO domains: `_row(domain="tasks", kind="note", key="k1", sanitized_text="buy milk", payload={}, source="curate")` and `_row(domain="notes", kind="note", key="n1", sanitized_text="call the plumber", payload={}, source="curate")`; `apply_curate(CurateDecision(op="forget", domain="", content="plumber"), store=store, last_rows=())` → `outcome.ok`, reply `"Forgotten."`, `store.query(domain="notes") == []`, `len(store.query(domain="tasks")) == 1` (untouched).
22. `test_forget_unscoped_ambiguous_across_domains_refuses` — seed one "milk" row in `tasks` AND one in `notes` (both `source="curate"`); `apply_curate(CurateDecision(op="forget", domain="", content="milk"), store=store, last_rows=())` → `not outcome.ok`, reply == `_AMBIGUOUS`, both rows still present.
23. `test_referent_save_no_target_refused` — `apply_curate(CurateDecision(op="save", domain="", content="", referent="the second one"), store=store, last_rows=(_row(), _row(key="e2")))` → `not outcome.ok`, reply == `_SAVE_WHERE` ("Save it where? ..."), `store.domains() == []` (nothing written anywhere).

### Task 7 — `tests/api/test_ask_routes.py` (modify): wiring tests (hermetic)
Reuse the file's existing harness (`client_for`, `FixedIntentRouter`, `FixedSelector`, `_no_match`, `MutableSecretStore`, `Principal` override). Add a helper that builds a client with a scripted curate extractor over a shared store, plus a fake extractor model returning a fixed JSON decision (mirror `tests/data/test_curate.py`'s `FakeModel`). Override `ask_routes._curate_extractor` to return `CurateExtractor(FakeCurateModel(reply=...))`; reach the store via `app.state.data_store`.

```python
class FakeCurateModel:  # returns one scripted CurateDecision JSON
    def __init__(self, reply: dict[str, str]) -> None:
        self._reply = reply

    async def complete(self, *, messages, model=None, response_schema=None,
                       temperature=0.7, max_tokens=None):
        return ModelResponse(text=json.dumps(self._reply), model_id=model or "fake",
                             structured=None, finish_reason="stop",
                             usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2))
```

Tests:
1. `test_curate_save_writes_and_confirms` — build app (`create_app(model=FakeModel("unused"))`), override `require_session`, `_intent`→`FixedIntentRouter("plain_ask")`, `_selector`→no-match, and `_curate_extractor`→`CurateExtractor(FakeCurateModel({"op":"save","domain":"tasks","content":"renew passport","referent":""}))`. `POST /app/ask {"text":"add a task: renew passport"}` → 200, `json["text"] == "Saved to tasks."`, `json["path"] == "curate"`; `app.state.data_store.query(domain="tasks")` has one row `sanitized_text == "renew passport"`.
2. `test_curate_none_falls_through_to_ask` — `_curate_extractor` scripted `{"op":"none",...}` (or a text with no curate verb so the prefilter fires zero calls), `_intent`→`plain_ask`, `model=FakeModel("plain answer")`. `POST` a non-write text → `json["path"] in {"codex","local"}` and `json["text"] == "plain answer"` (normal path intact; no write).
3. `test_curate_runs_before_read` — utterance contains a read keyword AND a save verb (`"add my calendar note: buy milk"`); `_curate_extractor` scripted save (`domain="tasks"`). Even with a seeded fresh `calendar` store row, response `path == "curate"` (NOT `local_read`) — proves the curate check precedes the read short-circuit.
4. `test_curate_unresolved_referent_no_write` — fresh app (empty `last_results`); `_curate_extractor` scripted `{"op":"save","domain":"tasks","content":"","referent":"the second one"}`. `POST` → `json["text"]` == the couldn't-find message, `json["path"] == "curate"`, `app.state.data_store.query(domain="tasks") == []`.
5. `test_read_then_referent_save_end_to_end` — override `_read_service` with a real `ReadService` over the app's `data_store` seeded with two fresh `calendar` rows + a `FakePhraser`, `now` within freshness. First `POST` a read (`"what's on my calendar"`) → `path == "local_read"` (this stashes rows). Then `POST` a save whose `_curate_extractor` is scripted `{"op":"save","domain":"tasks","referent":"the second one","content":""}` (reuse the same `TestClient` so `app.state.last_results` persists) → `json["text"] == "Saved to tasks."`; the saved `tasks` row's `sanitized_text` equals the second seeded calendar row's `sanitized_text`. (Requires per-test `_curate_extractor` swap between the two calls, e.g. reassign `app.dependency_overrides[ask_routes._curate_extractor]` before the second POST.)

## Acceptance criteria
1. `op=save` writes VERBATIM via `store.upsert` with `payload={}`, `source="curate"` (pinned literal), no quarantine/`IngestService`. → `test_save_verbatim_bypasses_quarantine`
2. `DataStore.upsert` normalizes the domain label (strip+lower) — the chokepoint for ALL write paths. → `test_upsert_normalizes_domain_chokepoint`
3. `apply_curate` also normalizes before its guard/reply, independent of the extractor validator. → `test_save_domain_normalized_at_write_boundary`
4. `op=forget` with content deletes ONLY on an exactly-one match; two or more matches → refusal ("multiple matches"), NOTHING deleted; no match → no write, honest reply. → `test_forget_by_content_deletes_match`, `test_forget_ambiguous_content_refuses`, `test_forget_no_match_no_write`
5. Synced-domain guard: `DataStore.has_foreign_source` is True for a domain with any non-`curate`-source row; `apply_curate` refuses BOTH save and forget on such domains (no write) — including a referent-forget whose RESOLVED row lives in a synced domain — and the refusal reply steers to a curated home ("try 'add a task' instead"). → `test_save_into_synced_domain_refused`, `test_forget_referent_synced_row_refused`
6. Amended extract degrade rule (calibration fix): empty domain degrades to `op=none` ONLY for `op=save` with an empty referent; `op=forget` and referent-saves pass through with an empty domain. → `test_extract_referent_save_empty_domain_passes_through`, `test_extract_forget_empty_domain_passes_through`, `test_extract_plain_save_empty_domain_still_degrades`
7. Unscoped forget (empty domain): content search runs across ALL live domains under the same exactly-one-match-or-refuse contract; the resolved row's domain is still synced-guarded. → `test_forget_unscoped_cross_domain_exactly_one`, `test_forget_unscoped_ambiguous_across_domains_refuses`
8. A referent-save with no stated target domain refuses honestly ("Save it where? ..."), writes nothing. → `test_referent_save_no_target_refused`
9. Ordinal referents resolve deterministically by position (in-range only). → `test_resolve_ordinal`
10. Fuzzy referents resolve only on an unambiguous single content match; ambiguous/none → `None`. → `test_resolve_fuzzy_unambiguous`, `test_resolve_bare_pointer_single_row`
11. A save-by-referent copies the resolved row's `sanitized_text` only — never the raw payload. → `test_save_referent_copies_sanitized_not_payload`
12. A referent that resolves nothing → no write, honest "couldn't find it"; a resolved curated row is deleted exactly. → `test_save_referent_unresolved_no_write`, `test_forget_referent_deletes_exact_row`
13. Per-session results state stashes the last read's rows payload-STRIPPED; unknown session → `()`. → `test_stash_strips_payload`
14. `ReadResult` exposes the ordered rows a read answered from. → `test_read_exposes_rows`
15. The ask route runs the curate check BEFORE the read short-circuit; `op=save`/`forget` → trusted write + `path="curate"` confirmation; `op=none` → existing flow untouched. → `test_curate_save_writes_and_confirms`, `test_curate_runs_before_read`, `test_curate_none_falls_through_to_ask`
16. A referent save wired end-to-end: a prior read stashes rows, a following referent save copies the resolved row. → `test_read_then_referent_save_end_to_end`
17. An unresolved referent through the route writes nothing and replies honestly. → `test_curate_unresolved_referent_no_write`
18. Whole-project gates clean (commands below); all new code passes `mypy --strict`.

## Commands to run
```
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q
```
