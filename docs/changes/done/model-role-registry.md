---
spec: model-role-registry
status: draft
token_profile: lean
autonomy_level: L3
coder_tier: codex
---

# Spec: model-role-registry — roles in code, models in config (BRAIN, part 1 of 2)

**Identity:** Add a `ModelRoleRegistry` (config in the data dir) mapping the nine runtime roles
(`loop_driver`, `selector`, `extractor`, `phraser`, `judge`, `reader`, `synth`, `memory`,
`forge_author`) → (provider, model), resolve each hardcoded model call site through `for_role(role)`
so a binding edit takes effect without restart, and enforce the role invariants on write. Defaults
reproduce today's de-facto haiku/router assignments (zero behavior change).
→ why: docs/technical/adr/ADR-049-model-role-registry.md (#1 roles-in-code, #3 invariants, #5 interchangeable providers).

Security review 2026-07-04: 2 BLOCKs folded (no-tools provider eligibility on write; fail-closed
load path). No open BLOCKs.

Rulings applied (planning, 2026-07-04): today's intent-classify + capability-selection sites bind to
the distinct `selector` role (default claude_code/haiku) — NOT `loop_driver`, so a future
driver-tier upgrade never silently raises per-selection cost. `loop_driver`, `judge`, `memory` are
inert placeholders (sensible defaults, no call site); the agent-loop arc binds them. FOLLOW-UP
(tracked for full ADR-049 #1 coverage): CLI (`src/artemis/app.py:96`) + reachout
(`web_tool.py:293,300-301`) composition roots stay hardcoded here — they migrate in part 2 or the
loop arc, whichever touches them first.

<!-- SPLIT NOTICE (per house rule >3 files / >2 phases; ADR-049 consequence: "brain: registry +
resolution + metering + endpoint"). This is drafted as TWO specs. THIS spec = part 1 (registry +
resolution + migration). Part 2 = `model-role-metering` (SQLite per-role meter + metered wrapper in
`for_role` + session-gated GET/PUT /app/models). Part 2 is FLAGGED, not drafted here — see the
"Deferred to part 2" section for the endpoint contract stub + the clean seam. Draft part 2 after
this builds green. -->

## Files to change
| # | File | Op | What |
|---|------|----|------|
| 1 | `src/artemis/model/roles.py` | create | `ModelRoleRegistry`, `RoleBinding`, `RoleConstraints`, `_RoleConstrainedPort`, defaults + invariant validation + `for_role`. |
| 2 | `src/artemis/api/app.py` | modify | Construct the registry on `app.state.model_roles`; migrate ingest reader + capability selector + capability forge. |
| 3 | `src/artemis/api/ask_routes.py` | modify | Migrate `_intent` / `_quarantine_reader` / `_read_service` phraser / `_curate_extractor` to `for_role`. |
| 4 | `src/artemis/capabilities/select.py` | modify | `build_capability_selector` takes an injected `model`; drop the per-call `model="haiku"` literal + now-orphan imports. |
| 5 | `src/artemis/intent.py` | modify | Drop the per-call `model="haiku"` literal (binding drives the model). |
| 6 | `src/artemis/data/curate.py` | modify | Drop the per-call `model="haiku"` literal. |
| 7 | `src/artemis/data/read.py` | modify | Drop the per-call `model="haiku"` literal. |
| 8 | `tests/test_model_roles.py` | create | Hermetic registry tests (validation, persistence, resolution-without-restart, constraint enforcement). |

## Exact changes

### Task 1 — `src/artemis/model/roles.py` (create)

Roles, providers, fixed per-role constraints, and de-facto defaults. `synth` binds to the
subscription-first `QuotaAwareRouter` (provider sentinel `"router"`); all other roles bind to a
single provider.

```python
"""Model-role registry: runtime code requests a ROLE; config maps role -> (provider, model).

ADR-049. Roles in code, models in config. Safety posture rides the role (reader=no-tools, bindable
only to providers with a verified no-tools invocation path; extractor/judge=temperature 0; judge
binding must differ from loop_driver). Resolution reads the current binding on every for_role()
call, so an owner edit takes effect without a restart. The load path fails closed: malformed or
invariant-violating persisted entries are dropped (logged) and the role falls back to its default —
for_role never raises because of persisted-file content.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from artemis.model.anthropic_provider import AnthropicAPIProvider
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.model.codex_provider import CodexProvider, RawProvider
from artemis.model.ollama_provider import OllamaProvider
from artemis.ports.model import ModelPort
from artemis.types import Message, ModelResponse

ROLES: tuple[str, ...] = (
    "loop_driver",
    "selector",
    "extractor",
    "phraser",
    "judge",
    "reader",
    "synth",
    "memory",
    "forge_author",
)
# "router" is the subscription-first QuotaAwareRouter chain (synth + forge_author). Others = single ports.
PROVIDERS: tuple[str, ...] = ("claude_code", "codex", "anthropic_api", "ollama", "router")
_ROUTER_ROLES: frozenset[str] = frozenset({"synth", "forge_author"})

_FORCE_TEMP_ZERO: frozenset[str] = frozenset({"extractor", "judge"})
_NO_TOOLS: frozenset[str] = frozenset({"reader"})
# Providers a no_tools role (reader) may bind to. claude_code hardcodes `--tools ""`; ollama has no
# tool machinery at all. codex is EXCLUDED: its `--sandbox read-only` is a filesystem posture, not
# no-tools — codex becomes eligible only when a verified no-tools invocation path exists.
_NO_TOOLS_PROVIDERS: frozenset[str] = frozenset({"claude_code", "ollama"})

_log = logging.getLogger(__name__)


class RoleRegistryError(ValueError):
    """Raised when a proposed binding violates a role invariant (ADR-049 #3)."""


@dataclass(frozen=True)
class RoleBinding:
    provider: str  # one of PROVIDERS
    model: str  # provider model id; ignored when provider == "router"


@dataclass(frozen=True)
class RoleConstraints:
    """Fixed, non-editable posture a swap cannot drop (ADR-049 #3)."""

    no_tools: bool
    temperature: float | None  # forced temperature; None = pass caller's through


def constraints_for(role: str) -> RoleConstraints:
    return RoleConstraints(
        no_tools=role in _NO_TOOLS,
        temperature=0.0 if role in _FORCE_TEMP_ZERO else None,
    )


# De-facto assignments as of ADR-049 (2026-07-04). selector = the haiku intent-classify +
# capability-selection sites; reader/phraser/extractor = the haiku dedicated ports; synth +
# forge_author = the shared codex-first router (forge_author = CapabilityForge propose/build
# authoring, which today implicitly rides app.state.model). loop_driver + judge + memory have NO
# current call site — inert placeholders (judge default satisfies judge != loop_driver); the
# agent-loop arc binds them (planning ruling 2026-07-04).
_DEFAULTS: dict[str, RoleBinding] = {
    "loop_driver": RoleBinding("claude_code", "haiku"),
    "selector": RoleBinding("claude_code", "haiku"),
    "extractor": RoleBinding("claude_code", "haiku"),
    "phraser": RoleBinding("claude_code", "haiku"),
    "reader": RoleBinding("claude_code", "haiku"),
    "synth": RoleBinding("router", ""),
    "judge": RoleBinding("claude_code", "sonnet"),
    "memory": RoleBinding("claude_code", "haiku"),
    "forge_author": RoleBinding("router", ""),
}


class _RoleConstrainedPort:
    """Wrap a ModelPort so a role's fixed temperature cannot be dropped by a binding swap.

    (Current providers discard `temperature` through ModelClient; this makes the guarantee hold the
    moment a temperature-honoring provider is bound. Satisfies ModelPort structurally.)
    """

    def __init__(self, inner: ModelPort, *, force_temperature: float | None) -> None:
        self._inner = inner
        self._force_temperature = force_temperature

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        temp = self._force_temperature if self._force_temperature is not None else temperature
        return await self._inner.complete(
            messages=messages,
            model=model,
            response_schema=response_schema,
            temperature=temp,
            max_tokens=max_tokens,
        )


ProviderFactory = Mapping[str, Callable[[], RawProvider]]


class ModelRoleRegistry:
    """Persisted role->binding map with call-time resolution and on-write invariant validation."""

    def __init__(
        self,
        path: Path,
        *,
        router_factory: Callable[[], ModelPort],
        anthropic_api_key: str | None = None,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self._path = path
        self._router_factory = router_factory
        self._provider_factory: ProviderFactory = provider_factory or {
            "claude_code": lambda: ClaudeCodeProvider(),
            "codex": lambda: CodexProvider(),
            "anthropic_api": lambda: AnthropicAPIProvider(api_key=anthropic_api_key),
            "ollama": lambda: OllamaProvider(),
        }

    # --- read -----------------------------------------------------------------
    def bindings(self) -> dict[str, RoleBinding]:
        """Defaults merged with SANITIZED persisted overrides (fresh read = no-restart resolution).

        Fail-closed: each persisted entry re-runs the same validation as put(); invalid entries
        are dropped (logged) and the role keeps its default. Never raises on file content.
        """
        merged = dict(_DEFAULTS)
        merged.update(self._sanitized_overrides())
        # Cross-role invariant re-checked after merge (a hand-edited file bypasses put()).
        if merged["judge"] == merged["loop_driver"]:
            _log.warning("model_roles: dropping judge override (equals loop_driver)")
            merged["judge"] = _DEFAULTS["judge"]
            if merged["judge"] == merged["loop_driver"]:
                _log.warning("model_roles: dropping loop_driver override (judge collision)")
                merged["loop_driver"] = _DEFAULTS["loop_driver"]
        return merged

    def get(self, role: str) -> RoleBinding:
        if role not in ROLES:
            raise RoleRegistryError(f"unknown role: {role!r}")
        return self.bindings()[role]

    def constraints(self, role: str) -> RoleConstraints:
        if role not in ROLES:
            raise RoleRegistryError(f"unknown role: {role!r}")
        return constraints_for(role)

    # --- write ----------------------------------------------------------------
    def put(self, role: str, binding: RoleBinding) -> None:
        self._validate(role, binding)
        overrides = {
            r: {"provider": b.provider, "model": b.model}
            for r, b in self._sanitized_overrides().items()
        }
        overrides[role] = {"provider": binding.provider, "model": binding.model}
        self._write_overrides(overrides)

    def _validate_entry(self, role: str, binding: RoleBinding) -> None:
        """Per-entry rules — shared by put() and the fail-closed load path."""
        if role not in ROLES:
            raise RoleRegistryError(f"unknown role: {role!r}")
        if binding.provider not in PROVIDERS:
            raise RoleRegistryError(f"unknown provider: {binding.provider!r}")
        if binding.provider == "router" and role not in _ROUTER_ROLES:
            raise RoleRegistryError("provider 'router' is only valid for synth / forge_author")
        if constraints_for(role).no_tools and binding.provider not in _NO_TOOLS_PROVIDERS:
            raise RoleRegistryError(
                f"role {role!r} requires a no-tools provider "
                f"({sorted(_NO_TOOLS_PROVIDERS)}); {binding.provider!r} has no verified "
                "no-tools invocation path"
            )

    def _validate(self, role: str, binding: RoleBinding) -> None:
        self._validate_entry(role, binding)
        # Evaluator independence: after applying, judge must differ from loop_driver (ADR-049 #3).
        proposed = self.bindings()
        proposed[role] = binding
        if proposed["judge"] == proposed["loop_driver"]:
            raise RoleRegistryError("judge binding must differ from loop_driver binding")

    # --- resolve --------------------------------------------------------------
    def for_role(self, role: str) -> ModelPort:
        binding = self.get(role)
        if binding.provider == "router":
            return self._router_factory()
        factory = self._provider_factory.get(binding.provider)
        if factory is None:
            raise RoleRegistryError(f"no provider factory for {binding.provider!r}")
        client = ModelClient(factory(), model_default=binding.model)
        return _RoleConstrainedPort(client, force_temperature=constraints_for(role).temperature)

    # --- persistence (JSON, atomic; stores only non-default overrides) --------
    def _sanitized_overrides(self) -> dict[str, RoleBinding]:
        """Persisted entries that pass the same per-entry rules as put(); the rest are dropped."""
        valid: dict[str, RoleBinding] = {}
        for role, entry in self._load_raw().items():
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("provider"), str)
                or not isinstance(entry.get("model"), str)
            ):
                _log.warning("model_roles: dropping malformed override for %r", role)
                continue
            binding = RoleBinding(provider=entry["provider"], model=entry["model"])
            try:
                self._validate_entry(role, binding)
            except RoleRegistryError as exc:
                _log.warning("model_roles: dropping invalid override for %r (%s)", role, exc)
                continue
            valid[role] = binding
        return valid

    def _load_raw(self) -> dict[str, object]:
        """Raw persisted JSON; unreadable/corrupt/non-object file -> {} (defaults), never raises."""
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            _log.warning("model_roles: persisted file unreadable — falling back to defaults")
            return {}
        return data if isinstance(data, dict) else {}

    def _write_overrides(self, overrides: dict[str, dict[str, str]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".model_roles.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(overrides, fh, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise
```

### Task 2 — `src/artemis/api/app.py` (modify)

**a.** Add import near the other model imports (line ~30):
```python
from artemis.model.roles import ModelRoleRegistry
```

**b.** In `create_app`, immediately AFTER `app.state.model = ... build_model_router()` (line ~111):
```python
    app.state.model_roles = ModelRoleRegistry(
        resolved_data_dir / "model_roles.json",
        router_factory=lambda: app.state.model,
    )
```

**c.** In `_build_sync`, replace the ingest reader construction (line ~60):
```python
# from:
    reader = ModelClient(ClaudeCodeProvider(), model_default="haiku")
# to:
    reader = app.state.model_roles.for_role("reader")
```

**d.** Replace the capability selector construction (line ~129):
```python
# from:
    app.state.capability_selector = build_capability_selector(capability_store)
# to:
    app.state.capability_selector = build_capability_selector(
        capability_store, model=app.state.model_roles.for_role("selector")
    )
```

**e.** Migrate the capability forge construction (line ~127) — today it rides `app.state.model` (the
router) implicitly; make the binding explicit:
```python
# from:
    app.state.forge = CapabilityForge(app.state.model, capability_store, resolved_sandbox)
# to:
    app.state.forge = CapabilityForge(
        app.state.model_roles.for_role("forge_author"), capability_store, resolved_sandbox
    )
```
`forge_author` defaults to `router`, so `for_role` returns the same `QuotaAwareRouter` the forge uses
today (zero behavior change). No invariant applies (it is not a reader; sandbox verify remains the
safety net for authored code).

**f.** Remove the now-unused `ClaudeCodeProvider` / `ModelClient` imports (lines 30-31) IF the grep
below confirms no other use remains in this file. `build_capability_selector` stays imported.

### Task 3 — `src/artemis/api/ask_routes.py` (modify)

Migrate the four dependency providers to the registry. Each reads `request.app.state.model_roles`.

```python
def _intent(request: Request) -> IntentRouter:
    return IntentRouter(request.app.state.model_roles.for_role("selector"))


def _quarantine_reader(request: Request) -> ModelPort:
    return request.app.state.model_roles.for_role("reader")


def _read_service(request: Request) -> ReadService:
    store: DataStore = request.app.state.data_store
    return ReadService(store, phraser=request.app.state.model_roles.for_role("phraser"))


def _curate_extractor(request: Request) -> CurateExtractor:
    return CurateExtractor(request.app.state.model_roles.for_role("extractor"))
```

Notes: drop the `del request` lines in `_quarantine_reader` and `_curate_extractor` (they now use
`request`). Remove the now-orphan `ClaudeCodeProvider` and `ModelClient` imports (lines 27-28) —
confirm no other use with the grep below. `_router` (synth path) is LEFT AS-IS in this spec —
`synth`'s binding IS the shared router, and `for_role("synth")` returns `app.state.model`; migrating
the raw `_router` accessor is behavior-identical polish deferred to keep this spec to the six
migrated sites. `synth` is fully registered so part 2's endpoint + the loop can resolve it.

### Task 4 — `src/artemis/capabilities/select.py` (modify)

**a.** Change `build_capability_selector` to accept an injected model (line ~110):
```python
def build_capability_selector(store: CapabilityStore, *, model: ModelPort) -> CapabilitySelector:
    """Build the selector over an injected role-resolved port (never a hardcoded provider)."""
    return CapabilitySelector(store=store, model=model)
```

**b.** In `CapabilitySelector.select`, drop the hardcoded model literal (line ~82) — the injected
port's `model_default` (from the binding) now drives the model:
```python
# remove this line from the .complete(...) call:
                model="haiku",
```

**c.** Remove the now-orphan imports `ClaudeCodeProvider` (line 11) and `ModelClient` (line 12).
Add `from artemis.ports.model import ModelPort` if not already imported (used in the new signature).

### Task 5 — `src/artemis/intent.py` (modify)

In `IntentRouter.classify`, drop the hardcoded model literal (line ~53):
```python
# remove this line from the self._model.complete(...) call:
                model="haiku",
```
(Behavior-identical: every construction site builds the port with `model_default="haiku"` — the API
site now via `for_role("selector")`, the CLI site still via its explicit `ModelClient`.)

### Task 6 — `src/artemis/data/curate.py` (modify)

In `CurateExtractor.extract`, drop the hardcoded model literal (line ~102):
```python
# remove this line from the self._model.complete(...) call:
                model="haiku",
```

### Task 7 — `src/artemis/data/read.py` (modify)

In `ReadService` phraser call, drop the hardcoded model literal (line ~185):
```python
# remove this line from the self._phraser.complete(...) call:
                model="haiku",
```

### Task 8 — `tests/test_model_roles.py` (create)

Hermetic (no CLI, no network). Fakes: a recording `RawProvider` and a sentinel router port.

```python
class _FakeProvider:  # satisfies RawProvider
    def __init__(self) -> None:
        self.calls: list[str] = []
    async def generate(self, *, messages, model, schema):  # type: ignore[no-untyped-def]
        self.calls.append(model)
        return "{}"

class _RecordingPort:  # satisfies ModelPort
    def __init__(self) -> None:
        self.temperature: float | None = None
    async def complete(self, *, messages, model=None, response_schema=None,
                       temperature=0.7, max_tokens=None):  # type: ignore[no-untyped-def]
        self.temperature = temperature
        return ModelResponse(text="{}", model_id=model or "x", structured=None,
                             finish_reason="stop", usage=Usage(0, 0, 0))
```

Cases (each = one `assert`-bearing test):
1. **defaults / no-file** → `ModelRoleRegistry(tmp_path/"r.json", router_factory=...).get("selector") == RoleBinding("claude_code", "haiku")`; `get("loop_driver") == RoleBinding("claude_code", "haiku")` (inert placeholder); `get("synth").provider == "router"`; `get("forge_author").provider == "router"`.
2. **for_role drives the model** → inject `provider_factory={"claude_code": lambda: fake}`; `await reg.for_role("selector").complete(messages=[Message("user","hi")])`; `fake.calls == ["haiku"]`.
3. **synth + forge_author resolve to the router** → `router_factory=lambda: sentinel`; `reg.for_role("synth") is sentinel` and `reg.for_role("forge_author") is sentinel`.
4. **constraint: extractor temperature forced to 0** → `_RoleConstrainedPort(rec, force_temperature=0.0)`; `await port.complete(messages=[...], temperature=0.9)`; `rec.temperature == 0.0`. And `force_temperature=None` → passes 0.9 through.
5. **for_role wires the extractor constraint** → wrap the fake so the returned port is `_RoleConstrainedPort`; assert `reg.constraints("extractor") == RoleConstraints(no_tools=False, temperature=0.0)` and `reg.constraints("reader") == RoleConstraints(no_tools=True, temperature=None)`.
6. **put persists + resolves without restart** → `reg.put("loop_driver", RoleBinding("codex", "gpt-5.5"))`; SAME instance `reg.get("loop_driver").provider == "codex"`; a NEW `ModelRoleRegistry` over the same path also reads `codex` (durable).
7. **invariant: judge != loop_driver** → `put("judge", RoleBinding("claude_code", "haiku"))` raises `RoleRegistryError` (equals loop_driver default); and after `put("loop_driver", RoleBinding("codex","gpt-5.5"))`, `put("judge", RoleBinding("codex","gpt-5.5"))` raises.
8. **invariant: unknown role / provider** → `put("nope", RoleBinding("codex","x"))` and `put("reader", RoleBinding("bogus","x"))` each raise `RoleRegistryError`.
9. **invariant: router only for synth / forge_author** → `put("reader", RoleBinding("router",""))` raises; `put("forge_author", RoleBinding("router",""))` and `put("forge_author", RoleBinding("codex","gpt-5.5"))` both succeed (router-role, no invariant).
10. **invariant: no-tools provider eligibility (security BLOCK 1)** → `put("reader", RoleBinding("codex", "gpt-5.5"))` raises `RoleRegistryError` (codex `--sandbox read-only` is a filesystem posture, not no-tools); `put("reader", RoleBinding("ollama", "qwen3:4b"))` and `put("reader", RoleBinding("claude_code", "sonnet"))` both succeed.
11. **fail-closed: corrupt file (security BLOCK 2)** → write `"{not json"` to the registry path; `reg.bindings()` returns `_DEFAULTS` for every role, `reg.for_role("selector")` resolves, nothing raises (a warning is logged).
12. **fail-closed: hand-edited judge==loop_driver** → write `{"judge": {"provider":"claude_code","model":"haiku"}}` directly to the file (equals loop_driver default, bypassing `put`); `reg.bindings()["judge"] == _DEFAULTS["judge"]` (override dropped, warning logged), no raise.
13. **fail-closed: codex-for-reader in the file** → write `{"reader": {"provider":"codex","model":"gpt-5.5"}}` directly; `reg.get("reader") == _DEFAULTS["reader"]` (dropped on load), `reg.for_role("reader")` resolves to the default claude_code port, no raise. Also a malformed entry (`{"phraser": "haiku"}`) is dropped while a valid sibling override still applies.

## Acceptance criteria
1. Registry unit suite → `uv run pytest -q tests/test_model_roles.py` passes all thirteen cases (incl. the two security-BLOCK regressions: reader→codex rejected on write; corrupt/invalid persisted file falls back to defaults without raising).
2. No hardcoded model literal remains at a migrated site → `rg -n 'model="haiku"' src/artemis/intent.py src/artemis/data/curate.py src/artemis/data/read.py src/artemis/capabilities/select.py` returns nothing.
3. No dedicated `ClaudeCodeProvider(...)` construction remains in the migrated API composition root → `rg -n 'ClaudeCodeProvider' src/artemis/api/ask_routes.py src/artemis/api/app.py` returns nothing.
4. Zero behavior change under defaults → `uv run pytest -q` full suite stays green (ask/ingest/select/curate paths behave identically because every default binding = `claude_code/haiku` or the router).
5. Type + lint clean → `uv run mypy` clean (incl. `_RoleConstrainedPort`/`ModelRoleRegistry` satisfy `ModelPort`/typing); `uv run ruff check .` + `uv run ruff format --check .` clean.
6. Surgical → `git diff --stat` shows only the eight files above.

## Commands to run
```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q tests/test_model_roles.py
uv run pytest -q
```

## Deferred to part 2 (`model-role-metering` — FLAGGED, not built here)

Part 2 adds metering + the owner-editable endpoint. The clean seam is `for_role`: part 2 wraps the
port returned by `for_role` in a metering recorder (records role, provider, model, prompt/completion
tokens, latency to a SQLite meter in the data dir, mirroring `scheduler/ledger.py`) — no migrated
call site changes again. Router-bound roles (`synth`, `forge_author`) meter the actually-served
backend read from `ModelResponse.model_id`, not the sentinel `provider="router"`.

**Endpoint contract the future client settings panel consumes (session-gated, `require_session`,
typed DTOs — built in part 2, panel is a later separate spec):**
- `GET /app/models` → `{ roles: [{ role, provider, model, constraints: { no_tools, temperature }, editable_fields: ["provider","model"] }], providers: [...PROVIDERS] }` (constraints are read-only; `router` offered only for `synth` + `forge_author`).
- `PUT /app/models/{role}` body `{ provider, model }` → validates via `ModelRoleRegistry.put` (unknown role/provider, judge==loop_driver collision, `router` for a non-router role, or a non-`_NO_TOOLS_PROVIDERS` provider for a no_tools role → 422); returns the updated binding.
- `GET /app/models/usage` → per-role aggregates from the meter `{ role, calls, prompt_tokens, completion_tokens, avg_latency_ms }`.

**Panel-UX contract notes (owner suggestions 2026-07-04, bind the panel spec):**
- `GET /app/models` additionally returns per-role `eligible_providers` so the panel's dropdown
  only OFFERS valid providers (a no_tools role never even shows codex) — prevention over 422s.
- The GET response surfaces `dropped_overrides: [{ role, reason }]` when the load path discarded
  invalid/tampered entries, so a silently-reverted toggle is explained in the panel ("your reader
  override was invalid and reverted to default"), never mysterious.
- codex joins `_NO_TOOLS_PROVIDERS` only after a verified no-tools invocation path passes a live
  injection smoke (the reader-no-tools precedent: prove an injected prompt cannot trigger a tool).

## Rulings applied (planning, 2026-07-04 — formerly open items)
1. **Distinct `selector` role (ACTIONED)** — intent-classify + capability-selection bind to `selector` (default claude_code/haiku), not `loop_driver`, so upgrading the future driver's tier never silently raises the cost of every selection/classify call. The judge≠loop_driver invariant stays as-is.
2. **loop_driver + judge + memory are inert placeholders (ACCEPTED)** — sensible defaults, no call site; the agent-loop arc binds them. `judge=claude_code/sonnet` satisfies `judge != loop_driver`; `memory=claude_code/haiku` is a cheap read default.
3. **CLI + reachout composition roots scoped OUT (ACCEPTED)** — `src/artemis/app.py:96` (`_build_ingress` IntentRouter) and `src/artemis/reachout/web_tool.py:293,300-301` (reader + heterogeneous synth router) still construct hardcoded `ClaudeCodeProvider` ports (no `app.state` in those roots). They migrate in part 2 or the loop arc, whichever touches them first — tracked in the spec header for full ADR-049 #1 coverage.
4. **`reader` no-tools is STRUCTURAL via provider eligibility (SUPERSEDED by security BLOCK 1)** — no_tools roles may bind only to `_NO_TOOLS_PROVIDERS` (`claude_code` hardcodes `--tools ""`; `ollama` has no tool machinery). codex is rejected on write AND dropped on load (its `--sandbox read-only` is a filesystem posture, not no-tools) until a verified no-tools invocation path exists. A runtime enforcement wrapper additionally becomes REQUIRED the day any eligible provider grows a tool-capable path.

## Security review folded (2026-07-04 — 2 BLOCKs, both actioned)
1. **No-tools must be structural** → `_validate_entry` rejects any binding of a `no_tools` role to a provider outside `_NO_TOOLS_PROVIDERS` (initially `{"claude_code", "ollama"}`); test case 10.
2. **Load path fails closed** → persisted JSON is re-validated on every read with the SAME per-entry rules as `put`; malformed/invalid entries dropped with a logged warning, file-level parse failure ignores the whole file, the post-merge judge==loop_driver check drops the offending override(s), and `for_role` never raises due to persisted-file content; test cases 11-13.
