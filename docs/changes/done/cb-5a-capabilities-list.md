---
slice: capability-build
status: ready
coder_effort: low
depends_on: cb-2-build-endpoints
---

# CB-5a — Brain `/app/capabilities` list endpoint (data half)

**Identity:** The data half of CB-5. Adds `FileCapabilityStore.list()` + a session-gated `GET /app/capabilities` returning every promoted capability, so the map (CB-5b, deferred) has a source of capability nodes. Brain only — no gateway command, no TS wrapper, no map rendering (those pair with the node visual in CB-5b, which is blocked on a display-design decision). Depends on CB-2 (the store is already wired onto `app.state` at the real data root).

## Files to change

1. `src/artemis/capabilities/store.py` — **modify**: add `list()`.
2. `src/artemis/api/app.py` — **modify**: expose the capability store on `app.state` (so the read route doesn't reach through the forge).
3. `src/artemis/api/capability_routes.py` — **modify**: `CapabilitySummary`/`CapabilitiesList` DTOs + `GET /app/capabilities`.
4. `tests/test_capability_store.py` — **modify**: `list()` unit test.
5. `tests/test_api_capabilities.py` — **modify**: endpoint tests (empty + populated + session-gated).

One cohesive brain read-path (one phase); the extra files are the wiring + the two existing test homes.

## Exact changes

### 1. `src/artemis/capabilities/store.py`

Add a method on `FileCapabilityStore` (mirror `retrieve`'s glob + `_read_skill`; deterministic order):
```python
    def list(self) -> list[Skill]:
        """Every promoted capability in the library, sorted by name."""
        skills = [self._read_skill(path) for path in self._library.glob("*/SKILL.md")]
        return sorted(skills, key=lambda skill: skill.name)
```

### 2. `src/artemis/api/app.py`

Refactor the forge wiring so the store is constructed once and exposed (the route reads it directly; listing is a store read, not a forge op):
```python
    capability_store = FileCapabilityStore(resolved_data_dir / "capabilities")
    app.state.capability_store = capability_store
    app.state.forge = CapabilityForge(app.state.model, capability_store, resolved_sandbox)
    app.state.builds = {}  # build_id -> capability_routes.BuildState (in-memory, interim)
```

### 3. `src/artemis/api/capability_routes.py`

Add the DTOs (near the others):
```python
class CapabilitySummary(BaseModel):
    name: str
    description: str
    version: int
    uses: list[str]
    secrets: list[str]


class CapabilitiesList(BaseModel):
    capabilities: list[CapabilitySummary]
```

Add a store accessor + the route:
```python
def _store(request: Request) -> FileCapabilityStore:
    store: FileCapabilityStore = request.app.state.capability_store
    return store


@router.get("", response_model=CapabilitiesList)
async def list_capabilities(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> CapabilitiesList:
    skills = _store(request).list()
    return CapabilitiesList(
        capabilities=[
            CapabilitySummary(
                name=s.name,
                description=s.description,
                version=s.version,
                uses=s.uses,
                secrets=s.secrets,
            )
            for s in skills
        ]
    )
```
Add the import: `from artemis.capabilities.store import FileCapabilityStore`. (Router prefix is `/app/capabilities`, so `@router.get("")` serves `GET /app/capabilities`.)

### 4. `tests/test_capability_store.py`

Add a test: stage + promote two drafts (or use the store's existing helpers as the other tests do), then `store.list()` returns both, sorted by name; an empty store returns `[]`.

### 5. `tests/test_api_capabilities.py`

Using the existing `_client` harness:
- `GET /app/capabilities` on a fresh store → `{"capabilities": []}`.
- After driving `propose → build → promote` (or seeding the store directly), `GET /app/capabilities` includes the promoted capability with its `name`/`description`/`version`/`uses`/`secrets`.
- `GET /app/capabilities` without a session → 401.

## Acceptance criteria

1. `store.list()` returns all library capabilities sorted by name (empty → `[]`) → `test_capability_store.py`.
2. `GET /app/capabilities` returns the typed list (empty and populated) and is session-gated (401) → `test_api_capabilities.py`.
3. Whole project green: `uv run mypy` clean and `uv run pytest -q` all pass.

## Commands to run

```bash
uv run --no-sync ruff format src/artemis/capabilities/store.py src/artemis/api/app.py src/artemis/api/capability_routes.py tests/test_capability_store.py tests/test_api_capabilities.py
uv run --no-sync ruff check src/artemis/capabilities/store.py src/artemis/api/app.py src/artemis/api/capability_routes.py
uv run --no-sync mypy
uv run --no-sync pytest -q
```
