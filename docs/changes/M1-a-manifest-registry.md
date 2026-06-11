---
spec: m1-a-manifest-registry
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seam 2) + m0-m1-foundation-brain.md BLOCKs B3, F8 -->

# Spec: M1-a — Module manifest contract (hybrid) + ToolSpec/HookSpec models + registration/auto-export + in-memory RAG-for-tools index

**Identity:** Defines the in-code typed module manifest (Pydantic `ModuleManifest` + `ToolSpec` + `HookSpec` + supporting enums), the build/registration step that auto-exports an indexed JSON form with embedded tool descriptions, and the in-memory cosine tool index (RAG-for-tools) sitting behind the `VectorStore`/`Retriever` ports for later upgrade.
→ why: see docs/technical/architecture/brain.md § "Tool registry — keep all 25 modules' tools OUT of context" + § "Upgradeability — the ports" · docs/technical/architecture/overview.md § "The module contract".

<!-- Split rule: ONE logical phase (the manifest/registry/tool-index subsystem). It creates 4 new src files + 1 test file. This exceeds the ≤3-files guideline; it is a justified atomic exception — the manifest models, the registration/auto-export step, and the in-memory tool index form a single cohesive contract unit that must type-check and round-trip together (a manifest is meaningless without the registry that indexes it, and the index is meaningless without a manifest to index). Flagged per rules. The actual tool implementation (get_current_time) and the consuming Router live in M1-d / M1-b respectively. -->

## Assumptions
- M0-a complete: `src/artemis/` package + `pydantic>=2` + `pydantic-settings` + `mypy --strict` + `pydantic.mypy` plugin configured. → impact: Stop (the manifest models are Pydantic and must pass strict mypy).
- M0-d complete: `src/artemis/ports/` exists exporting `EmbeddingModel`, `VectorStore`, `RetrievedChunk`, `Vector`, `Scope` (Protocols + types). → impact: Stop (the tool index is implemented behind these ports; signatures must match M0-d exactly).
- The tool index for M1's tiny tool count is an **in-memory cosine index** (brute-force dot-product over L2-normalised vectors), wrapped to satisfy the `VectorStore` port so LanceDB swaps in later with no caller change. → impact: Caution (flagged design choice per brain.md "in-memory cosine index is acceptable; behind the VectorStore/Retriever port"; if the port signature differs from what's assumed, adjust the wrapper, not callers).
- `action_risk` is an enum `no-data | read | write | high-stakes` used only as a classification field in M1 (the high-stakes gate that consumes it is a later milestone). → impact: Low (M1 stores it; nothing enforces it yet).
- The auto-export indexed form is JSON written to a per-slot path under the data dir, NOT committed to git (it is a build artifact derived from code). → impact: Caution (export path comes from M0-a `paths.py`; if the chosen path is wrong, fix the path helper call only).
- A `ToolSpec`'s typed args/return schemas are Pydantic model *classes* referenced in code; the auto-export serialises them via `model_json_schema()`. The `callable ref` is an **async** Python callable (`async def`, ADR-016) stored on the in-code ToolSpec and is NOT serialised into the exported JSON (code-only; the export is for retrieval). → impact: Stop (this is the hybrid contract: code carries the callable + types; export carries description + JSON schema for retrieval).

Simplicity check: considered exporting manifests to LanceDB immediately (the eventual store) — rejected for M1; brain.md explicitly permits an in-memory cosine index behind the port for M1's tiny tool count, and LanceDB is an M3/M4 engine not present in M0. The in-memory index behind the `VectorStore` port is the minimum that honours the locked upgrade seam. Considered manifest-as-pure-JSON (no in-code object) — rejected; the locked contract is HYBRID (typed in-code object + auto-exported index), so the in-code Pydantic object is required.

## Prerequisites
- Specs that must be complete first: M0-a (package, config, paths, mypy gate), M0-d (ports: `EmbeddingModel`, `VectorStore`, `RetrievedChunk`, `Vector`, `Scope`).
- Environment setup required: none beyond M0. Fully deterministic; no on-hardware gate (the index is pure Python; embeddings are injected via the `EmbeddingModel` port and stubbed in tests with a fake embedder).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/manifest.py | create | `ModuleManifest`, `ToolSpec`, `HookSpec`, `DataScope`, `Permissions`, `ActionRisk`, `UiSurface` Pydantic models + enums |
| /Users/artemis-build/artemis/src/artemis/registry/__init__.py | create | package marker + re-exports `ToolRegistry`, `register`, `InMemoryToolIndex` |
| /Users/artemis-build/artemis/src/artemis/registry/index.py | create | `InMemoryToolIndex` — cosine `VectorStore` implementation behind the M0-d port |
| /Users/artemis-build/artemis/src/artemis/registry/registry.py | create | `ToolRegistry` (register manifests → embed tool descriptions → index) + `export_index()` auto-export to JSON |
| /Users/artemis-build/artemis/tests/test_manifest_registry.py | create | manifest validation, round-trip export, retrieval-by-cosine, port conformance |

## Tasks
- [ ] Task 1: Define the manifest + tool/hook models — files: `/Users/artemis-build/artemis/src/artemis/manifest.py` — pure Pydantic v2, `mypy --strict`-clean, no I/O. Define:
  - `class ActionRisk(StrEnum)`: members `NO_DATA = "no-data"`, `READ = "read"`, `WRITE = "write"`, `HIGH_STAKES = "high-stakes"`.
  - `class DataScope(StrEnum)`: `OWNER_PRIVATE = "owner-private"`, `GUEST_VISIBLE = "guest-visible"`, `SHARED = "shared"`.
  - (F8) `class Capability(StrEnum)` is **dropped** — it was defined and never used (`Permissions` uses plain bool fields). Remove it; do not create dead code.
  - `class Permissions(BaseModel)`: `owner: bool = True`, `guest: bool = False` (per-capability allow flags; minimal M1 form — owner allowed, guest denied by default).
  - `class ToolSpec(BaseModel)` with `model_config = ConfigDict(arbitrary_types_allowed=True)`: fields `name: str` (**BARE name only** — e.g. `"get_current_time"`, never `"time.get_current_time"`; Seam 2: `ToolSpec.name` is bare; the registry id is `f"{manifest.name}.{tool.name}"` used by `stage()`/`get_tool()`), `description: str`, `args_schema: type[BaseModel]`, `return_schema: type[BaseModel]`, `callable_ref: Callable[..., Awaitable[BaseModel]]` (Seam 2 / ADR-016: an `async def` taking ONE validated Pydantic args model and returning a Pydantic result model so `result.model_dump()` always works; GATE-a relies on this. Import `Awaitable` from `collections.abc` and `Callable` from `collections.abc`), `action_risk: ActionRisk`. Add a method `args_json_schema(self) -> dict[str, object]` returning `self.args_schema.model_json_schema()` and `return_json_schema(self)` likewise.
  - `class HookSpec(BaseModel)`: `name: str`, `interval_seconds: int | None = None`, `cron: str | None = None`, `urgency: Literal["low","normal","high"] = "normal"`, `needs_llm: bool = False`, `dedup_key: str | None = None`, `check_ref: Callable[[], bool]` (deterministic check; `arbitrary_types_allowed`). M1 modules may declare an empty `proactive_hooks` list.
  - `class UiSurface(BaseModel)`: `kind: Literal["none","card","page"] = "none"`, `title: str | None = None` (optional descriptor; defaults to `none` in M1).
  - `class ModuleManifest(BaseModel)` with `arbitrary_types_allowed`: `name: str`, `version: str`, `description: str`, `tools: list[ToolSpec] = []`, `data_scope: DataScope`, `permissions: Permissions = Permissions()`, `proactive_hooks: list[HookSpec] = []`, `ui: UiSurface = UiSurface()`. Add a `model_validator` ensuring `name` is a non-empty slug (`^[a-z][a-z0-9_]*$`) and tool names are unique within the manifest.
  — done when: `uv run mypy --strict src` passes and `ModuleManifest(name="m", version="0.1.0", description="d", data_scope=DataScope.OWNER_PRIVATE)` constructs with empty tools/hooks.

- [ ] Task 2: Implement the in-memory cosine tool index behind the VectorStore port — files: `/Users/artemis-build/artemis/src/artemis/registry/index.py` — `class InMemoryToolIndex` structurally satisfying `artemis.ports.VectorStore` (do NOT subclass — Protocol/structural; add `# satisfies artemis.ports.VectorStore` comment + a static type-assertion in the test). Internal storage: a list of `(scope, id, vector, metadata)` tuples. `add(self, scope, ids, vectors, metadata) -> None` stores entries (L2-normalises each vector on insert; reject mismatched lengths with `ValueError`). `search(self, scope, query, k) -> list[RetrievedChunk]` computes cosine via dot-product of the L2-normalised query against stored vectors *filtered to the matching scope*, returns the top-`k` as `RetrievedChunk` (build a minimal `Chunk` from the stored id + metadata `text`; score = cosine). Pure stdlib `math`/list comprehensions — NO numpy dependency in M1. — done when: `uv run mypy --strict src` passes; a static `_check: VectorStore = InMemoryToolIndex()` line type-checks (asserted in test).

- [ ] Task 3: Implement the registry + auto-export — files: `/Users/artemis-build/artemis/src/artemis/registry/registry.py` — `class ToolRegistry` constructed with an `EmbeddingModel` (M0-d port) + a `VectorStore` (default `InMemoryToolIndex`). Methods:
  - `register(self, manifest: ModuleManifest) -> None`: **LAZY — must NOT embed or touch the `EmbeddingModel`/network at registration time.** (Stays SYNC — no port call: `register` only queues; the embed happens on first retrieval.) Store the manifest under `manifest.name`; append each `ToolSpec` to an internal pending list of `(fq_id, tool)` entries to be embedded on first retrieval (the **registry id** = `f"{manifest.name}.{tool.name}"` — Seam 2; the `ToolSpec.name` field is bare). Reject a duplicate module name with `ValueError`. The first `retrieve_tools`/`retrieve_tools_scored` call drains the pending list: for each pending `ToolSpec`, `await self.embedder.embed(...)` `f"{tool.name}: {tool.description}"` via the `EmbeddingModel` (batch all pending entries in one `await embed([...])` pass for efficiency) and `add()` it to the index under a synthetic scope `"tools"` with id `f"{manifest.name}.{tool.name}"` and metadata `{"text": tool.description, "module": manifest.name, "tool": tool.name, "action_risk": tool.action_risk}`; subsequent retrievals only embed entries registered since the last drain. This keeps `ToolRegistry` construction + `register()` network-free (consumed by M1-c `compose_brain`). (D1) If any `ToolSpec` has `action_risk` of `WRITE` or `HIGH_STAKES`, also register a sibling callable `{fq_id}_execute` in an internal `_execute_callables` dict — this is the dispatch-only twin used by `ActionStagingService.approve()` to perform the raw write with no re-classification; the `_execute` twin is NOT included in `retrieve_tools()` results (the model must never call the ungated write directly).
  - `async def retrieve_tools(self, query: str, k: int = 3) -> list[str]`: ASYNC (drains the pending list + `await self.embedder.embed(query)` — ADR-015: `EmbeddingModel.embed` is async). `await` the embed of the query, `search()` the index (scope `"tools"`; `VectorStore.search` STAYS sync), return the list of `module.tool` fq ids (the relevant handful — keeps all tools OUT of model context). **Does NOT return `_execute`-twin ids.**
  - `async def retrieve_tools_scored(self, query: str, k: int = 3) -> list[tuple[str, float]]`: ASYNC (same drain + `await self.embedder.embed(query)`). Same as `retrieve_tools` but returns `(fq_id, cosine_score)` pairs. (B3: M1-b Task 1 needs the top cosine score to threshold routing; adding this method here avoids M1-b having to re-search the index or touch registry internals that are not in its Files to Change.)
  - `get_tool(self, fq_name: str) -> ToolSpec`: resolve a `module.tool` fq id back to its in-code `ToolSpec` (the callable lives here; the index only holds descriptions). Raise `KeyError` if absent. Also accepts `f"{fq_name}_execute"` to retrieve an execute-twin callable (returns a synthetic `ToolSpec` wrapping the twin callable — which is `async def` per ADR-016, matching the `callable_ref` type).
  - `export_index(self, path: Path) -> None`: write the **auto-exported indexed form** as JSON — a list of `{module, version, data_scope, tool, description, args_schema, return_schema, action_risk}` objects (schemas via `model_json_schema()`; the callable is NOT serialised). Create parent dirs; write atomically (temp file + `os.replace`).
  - `manifests(self) -> dict[str, ModuleManifest]`: read-only accessor.
  Add `def default_registry() -> ToolRegistry` that returns an empty registry given an injected embedder (caller supplies it; no global singleton with a live model in M1). — done when: `uv run mypy --strict src` passes.

- [ ] Task 4: Wire the export path + package surface — files: `/Users/artemis-build/artemis/src/artemis/registry/__init__.py` — re-export `ToolRegistry`, `InMemoryToolIndex`, `default_registry`, with `__all__`. Add a typed helper `tool_index_path(s: Settings) -> Path` returning `paths.slot_root(s) / "tool_index.json"` (uses M0-a `paths.slot_root`; the export is a per-slot build artifact, not committed). — done when: `uv run python -c "from artemis.registry import ToolRegistry, InMemoryToolIndex, default_registry, tool_index_path"` exits 0.

- [ ] Task 5: Write the manifest+registry tests — files: `/Users/artemis-build/artemis/tests/test_manifest_registry.py` — typed pytest with a `FakeEmbedder` implementing the `EmbeddingModel` port (deterministic: maps each input string to a small fixed-dimension vector via a hash-based bag-of-words so semantically-close strings score higher; `async def embed(self, texts)` — ADR-015: `EmbeddingModel.embed` is async; `dimension` property STAYS sync, returns the fixed dim). Async tests use `@pytest.mark.anyio` (NOTE: no async test runner config exists in the spec set yet — coding mode must ensure `anyio`/`pytest-anyio` or `pytest-asyncio` is available and an `anyio_backend`/`asyncio_mode` is configured; flag if absent). Tests:
  - manifest validation (sync): a bad `name` ("Bad Name") raises `ValidationError`; duplicate tool names in one manifest raise `ValidationError`.
  - port conformance (sync): `_check: VectorStore = InMemoryToolIndex()` (type-level, validated by mypy in the recipe) and `index.search` returns at most `k` results filtered by scope.
  - register + retrieve (`async def`, `@pytest.mark.anyio`): register a manifest with two tools whose descriptions are clearly different ("get the current time" vs "send an email"); `await registry.retrieve_tools("what time is it", k=1)` returns the time tool's fq id (Seam 2: fq id = `f"{manifest.name}.{tool.name}"`; `ToolSpec.name` is bare). Assert `retrieve_tools` returns NO `_execute`-twin ids.
  - `retrieve_tools_scored` (`async def`, `@pytest.mark.anyio`): `await registry.retrieve_tools_scored("what time is it", k=1)` returns a list of `(fq_id, float)` tuples; the top score is > 0.0. (B3: M1-b uses this to threshold routing without re-searching the index.)
  - get_tool (sync): `get_tool("<module>.<tool>")` returns the original `ToolSpec` with its callable intact (`callable(spec.callable_ref) is True`); unknown id raises `KeyError`.
  - export round-trip (sync): `export_index(tmp_path/"idx.json")` writes valid JSON; reloading it yields one object per tool with `description`, `args_schema`, `action_risk` keys and NO `callable_ref` key.
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_manifest_registry.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/manifest.py, /Users/artemis-build/artemis/src/artemis/registry/__init__.py, /Users/artemis-build/artemis/src/artemis/registry/index.py, /Users/artemis-build/artemis/src/artemis/registry/registry.py, /Users/artemis-build/artemis/tests/test_manifest_registry.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_manifest_registry.py` | Type gate (load-bearing for the typed contract) |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/manifest.py, src/artemis/registry/**, tests/test_manifest_registry.py |
| `git commit` | "feat: M1-a module manifest contract + tool registry + in-memory RAG-for-tools index" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | Pure in-process; export path derived from Settings, no env read here |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No new dependencies (stdlib math only; numpy deliberately avoided in M1) |

## Specialist Context
### Security
The manifest carries `data_scope` + `permissions` (owner/guest) and each `ToolSpec` carries `action_risk` — the typed fields the crypto wall + high-stakes gate consume in later milestones. M1 only *stores* them; nothing enforces scope/risk yet (single-owner stub). The exported index contains tool *descriptions + JSON schemas only* — never the callable, never owner data. [FLAG apex-security at M2/M5: enforce `permissions` + `action_risk` at dispatch once guests + the high-stakes ladder exist.]

### Performance
Keeping all tools OUT of the model context is the brain.md frugality core; `retrieve_tools` returns only the top-`k` (default 3). In-memory cosine is O(n) over a handful of tools in M1 — negligible; the `VectorStore` port lets LanceDB ANN replace it at corpus scale with no caller change.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/manifest.py, src/artemis/registry/*.py | Type + docstring all exports; document the hybrid contract (code = callable+types; export = description+schema) |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_manifest_registry.py` → verify: exit 0, no errors (incl. the `VectorStore = InMemoryToolIndex()` structural assertion).
- [ ] Run `uv run python -c "from artemis.manifest import ModuleManifest, ToolSpec, HookSpec, ActionRisk, DataScope; m=ModuleManifest(name='demo', version='0.1.0', description='d', data_scope=DataScope.OWNER_PRIVATE); print(m.name, len(m.tools))"` → verify: prints `demo 0`.
- [ ] Run `uv run pytest -q tests/test_manifest_registry.py` → verify: all tests pass (manifest validation, cosine retrieve returns the time tool's fq id with bare ToolSpec.name, `retrieve_tools_scored` returns scored pairs, export round-trip has no `callable_ref` key, `retrieve_tools` returns no `_execute`-twin ids).
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_
