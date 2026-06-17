# Cross-Module Contracts (FROZEN)

_Single source of truth for every interface that crosses a spec/module boundary. Every spec binds to
the shapes defined here; where a spec disagrees, **this doc wins** and the spec is amended to match.
Produced by the corpus-remediation Wave 0A (see `docs/findings/sweep-2026-06-10/REMEDIATION-PLAN.md`).
Architectural *why* lives in ADR-012 (GATE) and ADR-013 (cross-module links) — not here._

**Status:** FROZEN 2026-06-11 · incorporates Decision-Gate D1–D4 · async amendments ADR-015 (Seam 1)
+ ADR-016 (Seams 2 + 3, 2026-06-12). Changing a contract here is an ADR-level event, not a per-spec edit.

Legend: **Producer** = the one spec that defines the symbol. **Consumers** = specs that bind to it.
**Δ** = the conformance change required (what the amendment pass applies).

---

## Seam 1 — LLM `ModelPort` / `ModelResponse`  (Decision D2)

**Producer:** M0-d (`src/artemis/ports/`). **Consumers:** M1-b, DR-a, DR-c, M7-a2, M3-d, all LLM callers.

```python
class Usage(BaseModel):                    # defined here (was referenced-but-unspecified)
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ModelResponse(BaseModel):
    text: str
    finish_reason: str
    usage: Usage
    origin: Literal["local", "cloud"]      # D2 — egress provenance; OBS logs it, M7-a2 reads it
    model_id: str                          # D2 — concrete model that served the call

class ModelPort(Protocol):
    async def complete(                    # ASYNC — resolves the sync/await fiction (see Δ)
        self, *, role: str, messages: Sequence[Message],
        response_schema: dict | None = None,   # constrained decoding (Outlines); NO tools param
        temperature: float = 0.7,              # D2 — DR-c needs it; harmless default elsewhere
        max_tokens: int | None = None,         # D2
        stream: bool = False,
    ) -> ModelResponse: ...
    def complete_stream(                   # streaming split out (clean typing vs bool-overloaded return)
        self, *, role: str, messages: Sequence[Message], temperature: float = 0.7,
    ) -> AsyncIterator[str]: ...
```

**Δ:**
- M0-d: `def complete` → **`async def complete`** (M7-a2/DR-a/M1-b all `await` it; brain loop + SSE + quarantine are async). Add `origin`/`model_id` to `ModelResponse`; add `temperature`/`max_tokens`.
- **No `tools`/`tool_choice` parameter on `complete`** — DR-a's toolless-quarantine guarantee is load-bearing on this (DR-a even runtime-introspects the signature). Do not add one.
- M1-b's `respond_stream` calls `complete_stream` (not `complete(stream=True)` with a union return).

**Async port surface (ADR-015) — amended 2026-06-11.** Network-I/O port methods are `async`; local-disk/DB
and cached-value methods stay sync. The full async set across `src/artemis/ports/`:
- **Async:** `ModelPort.complete` (above) · `ModelPort.embed` · `EmbeddingModel.embed_documents` · `EmbeddingModel.embed_query` · `Reranker.rerank` ·
  `Retriever.retrieve` · `MemoryStore.{recall, inject_context, add_fact, update_fact}` (all embed).
- **Sync:** `VectorStore.*` (local LanceDB) · `EmbeddingModel.dimension` (cached int) ·
  `MemoryStore.delete_fact` (tombstone, no embed) · `Router.route` · all voice ports.
- **Consumer Δ:** every caller of these now `await`s them, and any method that calls one becomes `async`.
  In particular `MemoryStore.recall`/`inject_context`/`add_fact`/`update_fact` being async makes their
  callers async (M4-b write path, M4-c-1 recall + Brain memory-injection, M4-d-2, M1-a tool retrieve,
  M1-b router embed, M3-a/M3-d ingestion embed, M7-a1 recipe-store embed). `Retriever.retrieve` async
  resolves the M3-c agentic-loop seam: the `agentic_fn` seam is an **async** `Callable[..., Awaitable[list[RetrievedChunk]]]`,
  and `AdaptiveRetriever.retrieve` `await`s it (M3-b/M3-c).

---

## Seam 2 — ToolRegistry / `callable_ref` / tool-name convention  (Decision D1)

**Producer:** M1-a. **Consumers:** every module manifest + GATE-a.

- `ToolSpec.name` is **bare** (`"create_event"`). The registry id is `f"{manifest.name}.{tool.name}"` (`"calendar.create_event"`). `stage(tool=...)`, `get_tool(...)` use the **fq id**.
- `callable_ref: Callable[..., Awaitable[BaseModel]]` — **ASYNC (ADR-016)**: an `async def` taking one validated Pydantic args model and returning a Pydantic result model (so `result.model_dump()` always works; GATE-a relies on this). Both dispatch sites `await` it.
- **D1 — execute-only twins:** a gated tool `X` registers a sibling `X_execute` callable that performs the raw effect with **no classification**. `X_execute` is registered **for staging-dispatch only — it is NOT included in `retrieve_tools()` / the brain's tool-selection surface** (the model must never call the ungated write directly).

**Δ:** every spec that writes `ToolSpec(name="calendar.create_event")` → bare name + one sentence: *"`ToolSpec.name` is bare; `module.tool` is the registry id used by `stage()`/`get_tool()`."* (Fixes B9 double-prefix, F12, the M8/CAL tool-name drift.)

**Uniform async tool-dispatch (ADR-016) — amended 2026-06-12.** `callable_ref` is `Callable[..., Awaitable[BaseModel]]`; **every** tool callable (front-door, `_execute` twin, read-only, and no-I/O alike) is `async def`. Rationale: every tool funnels through one uniform dispatch site in each consumer, so a single signature is simpler and `mypy --strict`-enforceable (a heterogeneous sync/async union would force `inspect.isawaitable` branching mypy can't check). A no-I/O body is still `async def` for signature uniformity but contains no `await`.
- **Producer (M1-a):** `ToolSpec.callable_ref: Callable[..., Awaitable[BaseModel]]`; `get_tool`'s synthetic-`ToolSpec` wrapper for `_execute` twins wraps an async callable. Export unaffected (`callable_ref` never serialised).
- **Dispatch Δ:** M1-b `respond`: `await spec.callable_ref(args_model)`. GATE-a `approve`: see Seam 3 (now `async def`, awaits the twin). Every spoke tool callable + `_execute` twin → `async def`: M1-d (time), M4-d-2 (`memory.resolve_entity` — **flips its "stays sync" LINT note to async**), CAL-a/b/c/d, M8-b1/b2, M8-d-a/b/c1/c2 (incl. `accept_with_graduation` → `async def` awaiting `RecipeStore.write`; removes the M8-d-c2 `LINT-DEFER`).
- **Stays sync inside async bodies:** SQLCipher reads/writes, `ActionStagingService.stage`/`set_status_conditional`, `EntityRepository` DB lookups. (Test fake/spy callables also become `async def`.)

---

## Seam 3 — GATE / `ActionStagingService` / `PendingActionStore`  (Decisions D1, D4; ADR-012)

**Producer:** GATE-a. **Consumers:** GATE-b, CAL-b, CAL-c, all future write-spokes.

```python
class ActionStagingService:
    def stage(self, module, tool, args, summary, *, ttl=None) -> PendingAction: ...   # tool = FRONT-DOOR fq id
    async def approve(self, action_id) -> PendingAction: ...   # ASYNC (ADR-016) — awaits the async _execute twin
    def reject(self, action_id) -> PendingAction: ...          # sync — no dispatch
    def expire_due(self, now) -> list[PendingAction]: ...      # sync — no dispatch
    def list_pending(self) -> list[PendingAction]: ...      # B2 — ADD; calls expire_due(now) first (U2), delegates store.list_pending()
```

**D1 approval-execution (fixes B1):**
- `PendingAction.tool` stores the **front-door** id (e.g. `"calendar.create_event"`) — what the owner sees in Review.
- `approve()` (now **`async def`**, ADR-016) maps front-door → **`{tool}_execute`** and dispatches the twin via `await get_tool(f"{action.tool}_execute").callable_ref(validated_args)`. The twin does the raw write with **no re-classification** → the loop is broken.
- **Execute-once / at-most-once (U1) via an intermediate `EXECUTING` state** (refined 2026-06-11 after the Wave-0B pilot found the recovery hole): `ActionStatus` gains **`EXECUTING`**. `approve()` order: validate args → conditional flip **`PENDING→EXECUTING`** (`UPDATE ... WHERE id=? AND status='pending'`, rowcount 0 → already taken, raise) → **`await`** dispatch the `_execute` twin → on success **`EXECUTING→APPROVED`** (store result) → on transient failure (`ScopeLockedError` / vault re-lock mid-dispatch) **revert `EXECUTING→PENDING`** so the owner can re-approve. (The conditional `set_status_conditional` flips stay sync SQLCipher inside the async method.) A crash mid-dispatch leaves the action visibly `EXECUTING` (recoverable), **never** silently `APPROVED`-but-unexecuted. Required for threadpool routes (U7). *(ADR-012 §3 should carry this clarifying note.)*

**Δ:** GATE-a add `list_pending()` + the `_execute` mapping + conditional-update. GATE-b fix route param ordering (`request: Request` before defaulted `Depends` params — B3; same fix in CLIENT-b). CAL-b/c register `_execute` twins for each gated tool and stop expecting `approve` to re-run the gated entrypoint.

---

## Seam 4 — `CalendarClient` (full read + write surface) + cache + prefs

**Producer:** CAL-a (`modules/calendar/client.py`). **Consumers:** CAL-b, CAL-c, CAL-d.

Read (exists): `list_calendars`, `list_events`, `get_event`, `query_free_busy`.
**Write (ADD — ONE canonical signature set, resolves B5/B6 three-incompatible-shapes):**
```python
def create_event(self, *, summary, start, end, description=None, location=None,
                 attendees=(), calendar_id, recurrence=(), reminders=None, send_updates="all") -> dict: ...
def update_event(self, event_id, changes: dict, *, recurrence_scope, send_updates="all") -> dict: ...
def move_event(self, event_id, *, new_start, new_end, recurrence_scope, send_updates="all") -> dict: ...
def cancel_event(self, event_id, *, recurrence_scope, send_updates="all") -> None: ...
def respond_to_invite(self, event_id, response) -> dict: ...
def add_attendees(self, event_id, attendee_emails, *, send_updates="all") -> dict: ...
def remove_attendees(self, event_id, attendee_emails, *, send_updates="all") -> dict: ...
def quick_add(self, text, calendar_id) -> dict: ...
def set_reminders(self, event_id, reminders) -> dict: ...
```
`FakeCalendarClient` + `GoogleCalendarClient` implement all of the above (fixes F5). **No `delete_event`** — use `cancel_event`.

**Naming / behaviour (Δ):**
- Canonical names: **`CalPrefs`** (not `CalendarPrefs`), field **`default_write_calendar`**, **`EventCacheStore`** (not `CalendarCache`). CAL-b/c amended to these (fixes B4).
- `EventCacheStore.invalidate(event_id, calendar_id) -> None` — **ADD** (CAL-b/c call it; PK is `(event_id, calendar_id)` so both args required).
- `CalPrefs.owner_email: str | None`; `None`/`""` → **GATED failsafe** in `classify` (fixes F2 `None.lower()`).
- Incremental sync passes **`show_deleted=True`** (consistent across the syncToken sequence) so cancellations propagate (fixes B11).
- One canonical email-comparison helper (lowercase+strip), owned by CAL-b, reused by CAL-d (U5).
- `quick_add` is **always-AUTO** (Google quickAdd cannot create attendees from text — pending R4 confirm) — resolves the execute-before-classify bug (B10).
- `CalendarClient` write methods + the gate/classify path are **in CAL-b's Files to Change** (client.py extended there).

---

## Seam 5 — Heartbeat hook contract  (Decision D3)

**Producer:** M6-a (`HookSpec`, runner) + M6-b (`TemplateRegistry`). **Consumers:** M6-c, CAL-c, CAL-d, Gmail/Productivity hooks.

- `check_ref: Callable[[], HookResult]` — **SYNCHRONOUS**, zero-arg. Returns `HookResult{hit, payload, dedup_value}`.
- **`pre_tick_steps: list[Callable[[], Awaitable[None]]]`** — async pre-flight, **owned and awaited by M6-a's runner** before each `tick()` (degrade-don't-crash). The composition root collects every module's pre-flight callable. **This is the ONE place untrusted text is laundered** (D3): a pre-flight step runs the quarantine and writes laundered safe claims; the sync `check_ref` reads those. (Fixes the M6-a/M6-c seam fiction + B12.)
- **Hook payload = IDs + timestamps + scalar counts ONLY** — never titles/snippets/bodies (privacy). Quarantined extracts expose `extract_summary`/`extract_claims` fields explicitly.
- **Template registration:** each `needs_llm=False` hook registers its ntfy template with the M6-b `TemplateRegistry` via an explicit `register_template(name, template)` call in `hooks.py` (fixes F4 — templates currently dropped on the floor).

**Δ:** CAL-d moves its `await quarantine_event_text(...)` out of `check_ref` into a `pre_tick_steps` callable (fixes B12). M6-a formally defines + awaits `pre_tick_steps` (today M6-c assumes a seam M6-a doesn't expose). Name the hook→template registration call.

---

## Seam 6 — Memory entity backbone  (ADR-013)

**Producer:** M4-d-1 (data layer) + M4-d-2 (write-path + tool). **Consumers:** Finance, Health, Comms, Travel, Productivity, any person/place/goal-linking spoke.

```python
class EntityType(StrEnum): PERSON="person"; PLACE="place"; GOAL="goal"
@dataclass(frozen=True) class EntityRef: module: str; entity_id: str   # ADR-013 D2 logical pointer; memory-homed → module=="memory"
def person_fact_key(*, external_ref: str | None, name: str) -> str     # ADR-013 D1 canonical person pointer
# EntityRepository(conn, person_id): resolve_or_create_entity / resolve_alias / add_alias /
#   list_aliases / get_entity / list_entities / merge_entities
# facts.subject_entity_id: nullable FK, POPULATED by M4-d-2 (A.U.D.N. write path)
```
- Cross-module person reference = **`person_fact_key`**, never an ad-hoc name string.
- Cross-module entity reference = **`EntityRef{module, entity_id}`**, resolved via the `memory.resolve_entity` tool (M4-d-2, ToolRegistry-registered) — **never a cross-store join** (ADR-013 D2).
- PLACE entities are created on demand by their owning spoke (Maps/Travel→Place).
- **GOAL entities (D3, 2026-06-11): created EAGERLY by Productivity** — `create_project` calls `EntityRepository.resolve_or_create_entity(name=project.title, EntityType.GOAL)` with `entity_id = f"goal:{project_id}"`, so every project is always cross-module-linkable (owner chose always-linkable over lazy/noise-minimised).

---

## Seam 7 — Untrusted-content / quarantine boundary  (`artemis.untrusted`)

**Producer:** DR-a. **Consumers:** DR-c (first), M3-a ingestion, M8-b1/b2 (Gmail), CAL-d. Folds the ADR-013 follow-up (replace per-module re-implementations with this one helper).

```python
# from artemis.untrusted import spotlight, QuarantinedReader, Extract, EXTRACTION_SCHEMA, QuarantineError
class QuarantinedReader:
    def __init__(self, model: ModelPort, role: str): ...      # raises QuarantineError if model.complete exposes tools, or role empty
    async def read(self, *, raw_content, source_url, source_domain, query) -> Extract: ...
# Extract: { summary: str (≤2000), claims: list[str] (≤20×≤500), flagged_injection: bool,
#            parse_failed: bool, source_url, source_domain }   # provenance is CALLER-supplied, not model-provided
```
**Invariant (fixes the theme-3 leaks):** the privileged side consumes **only** the `Extract` — raw subject/snippet/body **never** reaches a privileged model or a hook payload. M8-b1 tool returns + M8-b2 urgency payload + M6-c `held.json` must carry extracts/ids, **not** raw text.

---

## Seam 8 — Ingestion `Connector` + `GmailApiPort`  (M3-a)

**Producer:** M3-a (`Connector`/`Source`/`RawItem`/`IngestPipeline`); M8-b1 (`GmailApiPort`). **Consumers:** Gmail connectors, CAL-d knowledge connector.

```python
class Connector(Protocol):
    def fetch(self, source: Source) -> Iterable[RawItem]: ...
# RawItem{ raw_bytes: bytes|None, text: str|None, mime, source_id, origin_uri, fetched_at }
# IngestPipeline(connector_for: Callable[[Source], Connector], parser, embedder, store_for, is_unlocked)
```
- **Connector registration (fixes F7):** `IngestPipeline` dispatches via `connector_for(source)` keyed on `source.kind`. Every connector (Gmail body/attachment, `CalendarKnowledgeConnector`) is wired into `connector_for` at the composition root — name the wiring explicitly in each connector's spec.

```python
class GmailApiPort(Protocol):
    def list_message_ids(self, *, q, page_token) -> tuple[list[str], str | None]: ...
    def get_message(self, message_id, *, fmt: Literal["full","metadata"]) -> Mapping[str, object]: ...
    def list_history(self, *, start_history_id, page_token) -> tuple[list[Mapping], str | None]: ...
    def get_attachment(self, *, message_id, attachment_id) -> bytes: ...
    def current_history_id(self) -> str: ...
    def get_thread(self, thread_id) -> Mapping[str, object]: ...        # ADD — M8-b2 needs it
    def list_threads(self, *, q, page_token) -> tuple[list[str], str | None]: ...   # ADD — M8-b2 needs it
```
**Δ:** M8-b1 adds `get_thread`/`list_threads` to `GmailApiPort` + `GmailClient` + `FakeGmailApi` (the b1 `tools.py` already exposes thread tools that need them).

---

## Seam 9 — Visual-doc `PageImage`  (M3-a / M3-d)

**Producer:** **UNASSIGNED — must be pinned.** M3-d consumes `PageImage`; no spec produces it.
**Δ:** define `PageImage` (page-render bytes + page index + source ref) in **M3-a** (carried on `RawItem`/`Document` for visual sources) and have M3-d consume it. Resolve in the M3 conformance amendment; confirm against the Docling pipeline research (Wave 3) since page-image extraction is Docling's job.

---

## Seam 10 — Per-scope storage layout & encryption (Decision D4)

**Producer:** M0-a (`paths.scope_dir`) + M2-a (`VolumeMount`) + M2-b (`ScopedStore`). **Consumers:** every per-scope store (M3 LanceDB, M4 memory, GATE, modules, OBS). FileVault (device full-disk) is always underneath.

- `paths.scope_dir(scope)` = `<data_root>/<slot>/<scope>/` — the **parent**. SQLCipher DBs (memory, GATE, modules, telemetry) live **directly here**, encrypted by SQLCipher with the owner-gated DEK. **No encrypted-volume layer on the SQLite stores** (avoids double-encryption; FileVault + SQLCipher suffice).
- `scope_dir(scope)/vault/` = a per-scope **APFS encrypted volume** mounted on owner-unlock (M2-a), holding **only LanceDB** (the knowledge vectors SQLCipher can't reach). Gives the vectors an owner-gated key + "vanishing when locked". M3's `store_for(scope)` points here.
- M2-a `VolumeMount` is scoped to the `vault/` (LanceDB) volume only; lock must unmount it (close LanceDB handles first). M2-b opens SQLCipher at `scope_dir` directly (the B3 path-mismatch is resolved by this split).

## Conformance amendment index (Wave 0B — one per area, AFK-parallel)

Each area's amendment applies the Δ rows above for the specs it owns; work-lists are the BLOCK
sections of the matching per-area sweep report.

| Area | Seams touched | Sweep report |
|------|---------------|--------------|
| M0-M1 foundation/brain | 1, 2 | m0-m1-foundation-brain.md |
| M2 / OBS / DR | 7 | m2-obs-dr-security.md |
| M3-M4 knowledge/memory | 6, 8, 9 | m3-m4-knowledge-memory.md |
| M5-M6 voice/heartbeat | 5 | m5-m6-voice-heartbeat.md |
| M7 / CAP | 1 | m7-cap-teacher-distill.md |
| Calendar + GATE | 2, 3, 4, 5 | cal-gate.md |
| Gmail | 7, 8 | m8-gmail.md |
| Productivity | 3, 5, 6 | m8-productivity.md |
| CLIENT | 3 (B3) | client.md |

ADR amendments: **ADR-012** (GATE `_execute` path / execute-once) · **ADR-013** note (no change to
decisions; reference `contracts.md` Seam 6) · **ADR-015** (async port surface — Seam 1) · **ADR-016**
(uniform async tool-dispatch — Seams 2 + 3; `callable_ref` and `approve` are async).
