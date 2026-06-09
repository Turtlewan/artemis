---
spec: gate-a-action-staging
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: GATE-a — Pending-action staging subsystem (PendingActionStore + ActionStagingService)

**Identity:** The shared backend staging primitive for gated one-off external-effect actions — a `PendingAction` model, an owner-private SQLCipher store, and an `ActionStagingService` that stages, approves (execute-once via ToolRegistry), rejects, and expires pending actions.
→ why: see docs/technical/adr/ADR-012-gated-action-staging.md

<!-- ONE logical phase (the pending-action data model + its store + the service seam). 4 src files + 1 test file. Exceeds the ≤3-files guideline; it is a justified atomic exception — the model, store, and service share one vocabulary (PendingAction/ActionStatus) and must type-check and round-trip together. The service is meaningless without a store; the store is meaningless without a model; none are usable by CAL-b/c without the service. Flagged per rules. -->

## Assumptions
- **M2-b** (`KeyProvider` Protocol with `dek_for_scope(scope: Scope) -> SecretKey`, `is_owner_unlocked() -> bool`, `SecretKey.as_hex() -> str`, `ScopeLockedError`, `OWNER_PRIVATE: Scope = "owner-private"` from `artemis.identity.scope`, `FakeKeyProvider`) is complete. → impact: Stop (PendingActionStore uses these exact symbols)
- **M2-c** (`sqlcipher_open(path: Path, key_hex: str) -> Connection` from `artemis.data.sqlcipher`) is complete. → impact: Stop (PendingActionStore's `_connect` copies the M8-a keyed pattern verbatim)
- **M1-a** (`ToolRegistry.get_tool(fq_name: str) -> ToolSpec`, `ToolSpec.callable_ref: Callable[..., BaseModel]`, `ToolSpec.args_schema: type[BaseModel]` from `artemis.registry`) is complete. → impact: Stop (ActionStagingService.approve dispatches via these exact symbols)
- `staging/` is **shared governance infrastructure**, not a domain module — it ships no `ModuleManifest` and no brain-facing tools. It is a library consumed by CAL-b, CAL-c, and future write-enabled spokes. → impact: Caution (no manifest/registry wiring here; callers register their own)
- The `PendingAction.args` dict is owner-authored intent captured at stage time from validated tool inputs — it never contains raw untrusted external text (the calling tool built it from validated inputs). The store is owner-private SQLCipher (same M2 wall as `SqlCipherTokenStore` in M8-a). → impact: Stop (this is the security boundary — owner-private at rest)
- The on-disk DB path is derived from `paths.scope_dir(settings, OWNER_PRIVATE) / "staging" / "pending_actions.db"`. The vault-path reconciliation to the broker-mounted `/opt/artemis/<slot>/<scope>/vault/` is a one-line adapter deferred to on-hardware integration (identical to M8-a token-store deferral). → impact: Low (off-hardware tests do not care; one-line change on the Mini)
- Real SQLCipher keyed persistence is GATED on-hardware (Task 5), exactly as M2-c and M8-a gate their real SQLCipher tasks. Off-hardware everything is tested with `FakeKeyProvider` + a fake `ToolRegistry`. → impact: Stop (keeps CI-buildable off the Mini)

Simplicity check: considered reusing M7-b `RecipeStore`/`ReviewSurface` for pending actions — rejected: a `PendingAction` is a one-off instance with bound args; conflating it with the recipe abstraction overloads `approve` semantics (promote-template vs execute-instance) and introduces RAG/signing machinery that is meaningless for a single dispatch (ADR-012). The minimum is: a pydantic model + a SQLCipher store + a service that wires them to the ToolRegistry.

## Prerequisites
- Specs that must be complete first: **M2-b** (KeyProvider/SecretKey/ScopeLockedError/OWNER_PRIVATE), **M2-c** (sqlcipher_open), **M1-a** (ToolRegistry/ToolSpec).
- Environment setup required: none beyond M0/M1/M2 for the off-hardware suite. Real SQLCipher keyed persistence is GATED on-hardware (Task 5).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/staging/__init__.py | create | package marker + re-exports |
| /Users/artemis-build/artemis/src/artemis/staging/model.py | create | `PendingAction` frozen Pydantic model + `ActionStatus` enum |
| /Users/artemis-build/artemis/src/artemis/staging/store.py | create | `PendingActionStore` — owner-private SQLCipher, M8-a keyed `_connect` pattern |
| /Users/artemis-build/artemis/src/artemis/staging/service.py | create | `ActionStagingService` — stage/approve/reject/expire_due |
| /Users/artemis-build/artemis/tests/test_action_staging.py | create | model, store (fake key provider), service (fake registry + spy callable), security invariants |

## Tasks

- [ ] Task 1: Define the PendingAction model + ActionStatus enum — files: `/Users/artemis-build/artemis/src/artemis/staging/model.py` — pure Pydantic v2, `mypy --strict`-clean, no I/O:
  - `class ActionStatus(StrEnum)`: `PENDING = "pending"`, `APPROVED = "approved"`, `REJECTED = "rejected"`, `EXPIRED = "expired"`.
  - `class PendingAction(BaseModel)` with `model_config = ConfigDict(frozen=True)`:
    - `id: str` — a UUID4 string generated at stage time (caller supplies; store does not generate)
    - `module: str` — the module name (e.g. `"calendar"`)
    - `tool: str` — the fully-qualified `module.tool` fq_name (e.g. `"calendar.create_event"`)
    - `args: dict[str, object]` — the bound payload; owner-authored, captured at stage time
    - `summary: str` — deterministic plain-language description for the Review screen (no LLM at review time); must be non-empty (model_validator rejects empty string)
    - `action_class: Literal["takes-action"]` — always `"takes-action"` (the gated class per ADR-012 §2)
    - `status: ActionStatus = ActionStatus.PENDING`
    - `created_at: datetime` — UTC; timezone-aware
    - `expires_at: datetime` — UTC; timezone-aware; must be after `created_at` (model_validator rejects inversion)
    - `result: dict[str, object] | None = None` — set after execution on approve; None until then
  - `model_validator` (mode="after"): reject empty `summary`; reject `expires_at <= created_at`.
  — done when: `uv run mypy --strict src` passes; `PendingAction(id="x", module="m", tool="m.t", args={}, summary="s", action_class="takes-action", created_at=now, expires_at=now+1h)` constructs; empty `summary` raises `ValidationError`; `expires_at <= created_at` raises `ValidationError`.

- [ ] Task 2: Implement PendingActionStore (owner-private SQLCipher) — files: `/Users/artemis-build/artemis/src/artemis/staging/store.py` —
  - `class PendingActionStore` constructed with `(settings: Settings, key_provider: KeyProvider)`.
  - `def _db_path(self) -> Path`: `paths.scope_dir(settings, OWNER_PRIVATE) / "staging" / "pending_actions.db"`. Document the vault-path reconciliation deferral (identical to M8-a Assumptions).
  - `def _connect(self) -> Connection`: **copy the M8-a `SqlCipherTokenStore._connect` pattern exactly**:
    - `key = key_provider.dek_for_scope(OWNER_PRIVATE)` — raises `ScopeLockedError` if locked; let it propagate (no catch, no unlock)
    - assign `key.as_hex()` ONLY to a local variable `key_hex` inside `_connect()` — **never** to an instance or module attribute (document: Python GC bounds an immutable str's lifetime; consistent with M8-a security note)
    - `self._db_path().parent.mkdir(parents=True, exist_ok=True)`
    - `conn = sqlcipher_open(self._db_path(), key_hex)`
    - `CREATE TABLE IF NOT EXISTS pending_actions (id TEXT PRIMARY KEY, module TEXT NOT NULL, tool TEXT NOT NULL, args TEXT NOT NULL, summary TEXT NOT NULL, action_class TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, result TEXT)` — `args` and `result` stored as JSON text; datetimes as ISO-8601 UTC strings
    - return `conn`
  - Methods:
    - `def stage(self, action: PendingAction) -> None`: insert the action row (status MUST be PENDING — raise `ValueError` if not); `args` and `result` serialised as `json.dumps`/`json.loads`; datetimes as `.isoformat()`.
    - `def get(self, action_id: str) -> PendingAction`: SELECT by id; raise `KeyError` if absent; deserialise and return.
    - `def list_pending(self) -> list[PendingAction]`: SELECT WHERE status = "pending", ordered by created_at ASC.
    - `def set_status(self, action_id: str, status: ActionStatus, *, result: dict[str, object] | None = None) -> None`: UPDATE status (and result if provided) WHERE id = action_id; raise `KeyError` if absent.
  — done when: `uv run mypy --strict src` passes; a `PendingActionStore` built with `FakeKeyProvider(owner_unlocked=False)` raises `ScopeLockedError` on `stage` and `get`; `stage` then `get` round-trips a `PendingAction` with all fields preserved (off-hardware fake-key test, real SQLCipher gated Task 5).

- [ ] Task 3: Implement ActionStagingService — files: `/Users/artemis-build/artemis/src/artemis/staging/service.py` —
  - `class ActionStagingService` constructed with `(store: PendingActionStore, tool_registry: ToolRegistry, *, default_ttl: timedelta = timedelta(hours=24))`.
  - `def stage(self, module: str, tool: str, args: dict[str, object], summary: str, *, ttl: timedelta | None = None) -> PendingAction`:
    - `effective_ttl = ttl if ttl is not None else self.default_ttl`
    - `now = datetime.now(tz=timezone.utc)`
    - `action = PendingAction(id=str(uuid4()), module=module, tool=tool, args=args, summary=summary, action_class="takes-action", status=ActionStatus.PENDING, created_at=now, expires_at=now + effective_ttl)`
    - `store.stage(action)`
    - return `action`
  - `def approve(self, action_id: str) -> PendingAction`:
    - `action = store.get(action_id)` — raises `KeyError` if absent
    - if `action.status != ActionStatus.PENDING`: raise `ValueError(f"Cannot approve action {action_id}: status is {action.status}")`
    - **Expiry check BEFORE dispatch**: if `datetime.now(tz=timezone.utc) >= action.expires_at`: call `store.set_status(action_id, ActionStatus.EXPIRED)` and raise `ValueError(f"Action {action_id} has expired and cannot be approved")`
    - `tool_spec = tool_registry.get_tool(action.tool)` — raises `KeyError` if the tool is not registered; let it propagate
    - `validated_args = tool_spec.args_schema.model_validate(action.args)` — re-validates args against the tool schema; raises `ValidationError` on mismatch (do NOT catch — let it propagate; a mismatched args payload is a hard error)
    - `result_obj = tool_spec.callable_ref(validated_args)` — dispatch ONCE; raises `ScopeLockedError` if the vault is locked during dispatch; let it propagate (no catch)
    - `result_dict = result_obj.model_dump()` — serialise the result to a plain dict
    - `store.set_status(action_id, ActionStatus.APPROVED, result=result_dict)`
    - return `store.get(action_id)` — return the updated action
    - **No second dispatch path exists**: the only route to `callable_ref` is through `tool_registry.get_tool(tool).callable_ref` (the same ToolRegistry path the brain uses per ADR-012 §3). There is no fallback, no retry, no alternate dispatch.
  - `def reject(self, action_id: str) -> PendingAction`:
    - `action = store.get(action_id)` — raises `KeyError` if absent
    - if `action.status != ActionStatus.PENDING`: raise `ValueError(f"Cannot reject action {action_id}: status is {action.status}")`
    - `store.set_status(action_id, ActionStatus.REJECTED)`
    - return `store.get(action_id)`
  - `def expire_due(self, now: datetime) -> list[PendingAction]`:
    - fetch all `store.list_pending()`
    - for each where `now >= action.expires_at`: `store.set_status(action.id, ActionStatus.EXPIRED)` — **never dispatch, never call callable_ref**
    - return the list of actions that were expired (for logging/telemetry)
  — done when: `uv run mypy --strict src` passes; stage→approve dispatches the spy callable EXACTLY ONCE and returns APPROVED with the result; stage→reject returns REJECTED; stage→approve on an already-approved action raises `ValueError`; stage then `expire_due(expires_at + 1s)` marks it EXPIRED and approve on it raises `ValueError`; approve with a locked vault (FakeKeyProvider that raises `ScopeLockedError` from `callable_ref`) propagates `ScopeLockedError`; approve re-validates args (a mismatched args dict raises `ValidationError`).

- [ ] Task 4: Package surface — files: `/Users/artemis-build/artemis/src/artemis/staging/__init__.py` — re-export `PendingAction`, `ActionStatus`, `PendingActionStore`, `ActionStagingService` with `__all__`. — done when: `uv run python -c "from artemis.staging import PendingAction, ActionStatus, PendingActionStore, ActionStagingService"` exits 0.

- [ ] Task 5: Write tests (off-hardware, fakes only) — files: `/Users/artemis-build/artemis/tests/test_action_staging.py` — typed pytest with `FakeKeyProvider` (from `artemis.identity.key_provider`), a `FakeToolSpec` + `FakeToolRegistry` (minimal: `get_tool(fq_name)` returns a `FakeToolSpec` whose `args_schema` is a trivial Pydantic model and whose `callable_ref` is a spy callable tracking invocation count + returning a minimal result model), and a `PendingActionStore` built over a real SQLite file in `tmp_path` (using `FakeKeyProvider(owner_unlocked=True)` with a fake `dek_for_scope` that returns a `SecretKey`; **real SQLCipher keyed round-trip is GATED on-hardware**):
  - **model**: `PendingAction` constructs with all fields; `summary=""` raises `ValidationError`; `expires_at <= created_at` raises `ValidationError`; frozen (mutation raises).
  - **store locked**: `PendingActionStore(settings, FakeKeyProvider(owner_unlocked=False))` raises `ScopeLockedError` on `stage` and `get`.
  - **store round-trip** (fake key, real SQLite file): `stage` then `get` returns an identical `PendingAction` (all fields including datetimes timezone-aware, args dict preserved); `list_pending` returns staged PENDING action; `set_status(APPROVED, result={...})` updates; `get` reflects the new status and result.
  - **service stage**: `ActionStagingService.stage("cal", "cal.create_event", {"title": "T"}, "Create event T")` returns a `PendingAction` with `status=PENDING`, `tool="cal.create_event"`, `action_class="takes-action"`, `id` is a non-empty string, `expires_at == created_at + default_ttl`.
  - **service approve — dispatch-once**: approve a PENDING action → spy callable invoked EXACTLY ONCE (assert `spy.call_count == 1`); returned action has `status=APPROVED` and `result` non-None. Call approve a second time → raises `ValueError` (already APPROVED, not dispatched again — assert spy still `call_count == 1`).
  - **service approve — re-validates args**: stage an action with `args={"title": "T"}`; override the fake tool spec's `args_schema` with a model that requires an `int` field; approve → raises `ValidationError` (spy never called).
  - **service approve — expiry before dispatch**: stage with `ttl=timedelta(seconds=1)`; advance `now` by 2 seconds; `expire_due(now)` returns the action; approve → raises `ValueError` (expired); spy call_count == 0 (never dispatched).
  - **service approve — ScopeLockedError propagates**: spy callable raises `ScopeLockedError`; approve → raises `ScopeLockedError`; action status remains PENDING (no partial state update — verify via `store.get`).
  - **service reject**: stage then reject → status is REJECTED; approve after reject → raises `ValueError`.
  - **service expire_due**: stage two actions; `expire_due` with `now > expires_at` → both EXPIRED; `list_pending()` is empty; approve on either raises `ValueError`; spy never called.
  - **args never contain untrusted text**: (documentation + inline comment test) — assert that `PendingAction.args` is a plain `dict` (i.e., not a string carrying raw external text); a staged action whose args come from a validated Pydantic model's `.model_dump()` only contains Python-native types (strings/ints/floats/bools/None/list/dict) — document this as the invariant and assert `isinstance(action.args, dict)`.
  — done when: `uv run pytest -q tests/test_action_staging.py` passes AND `uv run mypy --strict src tests/test_action_staging.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] Task 6 (GATED — on-hardware): Real SQLCipher keyed persistence of `pending_actions.db` — files: (uses Tasks 2–3) — on the Mini with the SQLCipher binding installed + broker running + vault unlocked via MockProver proof: stage an action, confirm the DB is real SQLCipher (correct key opens, wrong key fails), approve it (callable_ref dispatches once), confirm result is persisted, confirm expired actions are never dispatched. — done when: verified on the Mini and recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/staging/__init__.py, /Users/artemis-build/artemis/src/artemis/staging/model.py, /Users/artemis-build/artemis/src/artemis/staging/store.py, /Users/artemis-build/artemis/src/artemis/staging/service.py, /Users/artemis-build/artemis/tests/test_action_staging.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_action_staging.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_action_staging.py` | Test gate (fakes only; no network, no SQLCipher in CI) |
| `uv run python -c "from artemis.staging import PendingAction, ActionStatus, PendingActionStore, ActionStagingService"` | Package-surface smoke |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/staging/**, tests/test_action_staging.py |
| `git commit` | "feat: GATE-a pending-action staging (PendingActionStore + ActionStagingService)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` / `ARTEMIS_DATA_ROOT` / `ARTEMIS_SLOT` | Settings + per-scope staging DB path resolution (M0-a) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure local; deterministic fakes off-hardware; no new deps |

## Specialist Context
### Security
Load-bearing invariants the build MUST honour (per ADR-012 §3 + apex-security self-review):
- **`approve` executes exactly once**: the only dispatch path is `tool_registry.get_tool(tool).callable_ref(validated_args)` inside a single `approve` call. No fallback, no retry. The `ValueError` guard on non-PENDING status prevents double-dispatch.
- **Args re-validated before dispatch**: `tool_spec.args_schema.model_validate(action.args)` runs inside `approve` before `callable_ref` is called. A mismatched args payload raises `ValidationError` — the dispatch never occurs.
- **Vault-locked → dispatch refused**: `ScopeLockedError` from `callable_ref` or from `store._connect` (via `dek_for_scope`) propagates unwrapped. There is no catch, no silent fallback.
- **Expired actions never execute**: the expiry check (`now >= expires_at`) runs before the `tool_registry` lookup. `expire_due` marks stale PENDING rows EXPIRED and never calls `callable_ref`.
- **`args` are owner-private at rest**: stored as JSON in the SQLCipher `pending_actions.db`, opened only with the broker-delivered owner DEK via `dek_for_scope(OWNER_PRIVATE)`. The `key.as_hex()` hex string is local to `_connect()` and never assigned to an instance attribute.
- **No untrusted external text enters execution**: `PendingAction.args` is a plain dict built by the calling tool from validated Pydantic model inputs — the gated tool never copies raw external content into args. This is a naming/documentation contract (assert `isinstance(action.args, dict)` in tests; document in `stage` docstring).
- **`PendingAction` is frozen**: immutability prevents status from being overwritten outside of `store.set_status`. All status transitions go through the store.

### Performance
`PendingActionStore._connect()` opens the SQLCipher file fresh per call (consistent with M8-a `SqlCipherTokenStore`). The broker DEK cache (M2-c session window) means `dek_for_scope` does not re-hit the enclave per call. The pending-actions table is expected to be small (a handful of in-flight actions at any time); no indexing complexity needed in M1.

### Accessibility
(none — no frontend; the Review screen surface is a later CLIENT-b/e spec)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/staging/model.py, store.py, service.py | Type + docstring all exports; document the execute-once invariant, the re-validation contract, the `ScopeLockedError` propagation, the expiry-before-dispatch guard, and the `key.as_hex()` local-only rule |

## Acceptance Criteria
- [ ] `uv run mypy --strict src tests/test_action_staging.py` → verify: exit 0.
- [ ] `uv run pytest -q tests/test_action_staging.py` → verify: model validation (empty summary, expired expiry rejects), store locked→`ScopeLockedError`, store round-trip (all fields preserved), service stage returns PENDING action, approve dispatches spy EXACTLY ONCE → APPROVED, second approve raises `ValueError` (spy still 1 call), re-validation failure raises `ValidationError` (spy 0 calls), expiry-before-dispatch raises `ValueError` (spy 0 calls), `ScopeLockedError` from callable propagates + status stays PENDING, reject→REJECTED, approve-after-reject raises `ValueError`, `expire_due` marks past-expiry rows EXPIRED + approve raises `ValueError` + spy 0 calls — all pass.
- [ ] `uv run python -c "from artemis.staging import PendingAction, ActionStatus, PendingActionStore, ActionStagingService"` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Real SQLCipher keyed persistence: stage→approve round-trip with correct DEK works; wrong key fails to open; expired action not dispatched → verify recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
