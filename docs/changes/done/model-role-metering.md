---
spec: model-role-metering
status: draft
token_profile: lean
autonomy_level: L3
coder_tier: codex
---

# Spec: model-role-metering — per-role meter + owner-editable endpoint (BRAIN, part 2 of 2)

**Identity:** Add a fail-soft SQLite per-role meter (mirrors `scheduler/ledger.py`) wrapping the port
`ModelRoleRegistry.for_role` returns — records role, binding provider, actually-served model
(`ModelResponse.model_id`), prompt/completion/cache tokens, latency, timestamp — and a session-gated
`GET/PUT /app/models` + `GET /app/models/usage` endpoint (typed DTOs, per-role `eligible_providers`
+ `dropped_overrides` for the future panel). Consumes part 1's `ModelRoleRegistry` / `for_role` /
`_validate_entry` / `_NO_TOOLS_PROVIDERS` / nine roles as-built; no migrated call site from part 1
changes again (the meter wraps at the `for_role` seam).
→ why: docs/technical/adr/ADR-049-model-role-registry.md (#2 owner-editable, #4 per-role metering).

Security review 2026-07-04: no BLOCKs, 2 FLAGs folded (PUT-DTO boundary pinning + registry-side
empty-model rejection; `dropped_overrides` never echoes tampered file content — enum reasons,
non-ROLES keys never emitted).

Amended 2026-07-04 (provider-usage-parse ruling): meter schema + aggregates + usage DTO carry
`cache_read_tokens` / `cache_creation_tokens`; `MeteredPort` reads them getattr-with-default so
the build is order-independent vs the usage-parse spec that adds the fields to `Usage`.

This spec depends on `docs/changes/model-role-registry.md` (part 1) being built first: it edits the
`roles.py` and `api/app.py` that part 1 creates/modifies. Treat part 1's contracts as existing.

## Files to change
| # | File | Op | What |
|---|------|----|------|
| 1 | `src/artemis/model/meter.py` | create | `ModelMeter` (SQLite, parameterized, fail-soft record), `RoleUsage`, `MeteredPort` (wraps a `ModelPort`, records each call). |
| 2 | `src/artemis/model/roles.py` | modify | `ModelRoleRegistry.__init__` takes an optional `meter`; `for_role` wraps its result in `MeteredPort`; add `eligible_providers`, `dropped_overrides` + `DropReason`/`DroppedOverride`; `_validate_entry` rejects an empty model for non-router providers. |
| 3 | `src/artemis/api/model_routes.py` | create | Session-gated `GET /app/models`, `PUT /app/models/{role}`, `GET /app/models/usage` + typed pydantic DTOs (pattern-pinned PUT body). |
| 4 | `src/artemis/api/app.py` | modify | Construct `ModelMeter` on `app.state.model_meter`, pass it into the registry, register `model_routes.router`. |
| 5 | `tests/test_model_meter.py` | create | Hermetic meter + `MeteredPort` tests (aggregation, model_id/provider recording, cache-token fields + build-order independence, fail-soft, persistence). |
| 6 | `tests/test_model_routes.py` | create | Hermetic endpoint tests (list, edit, 422s, usage, session gate, dropped-override surfacing). |

Scope note: 6 files, one cohesive phase (metering + endpoint are the single unit ADR-049's
consequence names — "brain: registry + resolution + metering + endpoint" — already split from part 1).
Not split further. The part-1-header scoped-out roots are **re-flagged, not migrated** — see the
"Re-flagged follow-up" section for the reasoned deferral.

## Exact changes

### Task 1 — `src/artemis/model/meter.py` (create)

Mirror the `ScheduleLedger` idiom: sync sqlite3, parameterized SQL, `commit()` per write, never
delete. The meter is append-only. `MeteredPort` records after the inner call and is fail-soft — a
metering failure logs a warning and returns the response; it NEVER fails the model call.

```python
"""Per-role model-call meter: append-only SQLite, mirrors scheduler/ledger.py.

ADR-049 #4. Every role-resolved call records role, binding provider, actually-served model
(ModelResponse.model_id — for router-bound roles this is the backend the router chose, not the
"router" sentinel), prompt/completion/cache tokens, latency ms, timestamp. Recording is fail-soft:
a meter failure logs a warning and returns the response, never raising into the model call path.
Cache fields are read getattr-with-default: the meter works whether or not the usage-parse spec
(which adds cache_read_tokens/cache_creation_tokens to Usage) has landed — build-order independent.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import cast

from artemis.ports.model import ModelPort
from artemis.types import Message, ModelResponse

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoleUsage:
    role: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    avg_latency_ms: float


class ModelMeter:
    """Append-only per-call meter in SQLite (sync; low-volume; called from async handlers)."""

    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        now: Callable[[], float] = time.time,
        check_same_thread: bool = True,
    ) -> None:
        self._now = now
        self._conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS calls ("
            " id INTEGER PRIMARY KEY, role TEXT NOT NULL, provider TEXT NOT NULL,"
            " model TEXT NOT NULL, prompt_tokens INTEGER NOT NULL,"
            " completion_tokens INTEGER NOT NULL,"
            " cache_read_tokens INTEGER NOT NULL DEFAULT 0,"
            " cache_creation_tokens INTEGER NOT NULL DEFAULT 0,"
            " latency_ms INTEGER NOT NULL, at REAL NOT NULL)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS calls_role ON calls(role)")
        self._conn.commit()

    def record(
        self,
        role: str,
        provider: str,
        model: str,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        self._conn.execute(
            "INSERT INTO calls(role, provider, model, prompt_tokens, completion_tokens,"
            " cache_read_tokens, cache_creation_tokens, latency_ms, at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (
                role,
                provider,
                model,
                prompt_tokens,
                completion_tokens,
                cache_read_tokens,
                cache_creation_tokens,
                latency_ms,
                self._now(),
            ),
        )
        self._conn.commit()

    def usage(self) -> list[RoleUsage]:
        """Per-role aggregates (calls, summed tokens incl. cache, mean latency), by role."""
        rows = cast(
            Iterable[tuple[str, int, int, int, int, int, float]],
            self._conn.execute(
                "SELECT role, COUNT(*), COALESCE(SUM(prompt_tokens), 0),"
                " COALESCE(SUM(completion_tokens), 0), COALESCE(SUM(cache_read_tokens), 0),"
                " COALESCE(SUM(cache_creation_tokens), 0), COALESCE(AVG(latency_ms), 0.0)"
                " FROM calls GROUP BY role ORDER BY role"
            ),
        )
        return [RoleUsage(r, c, p, comp, cr, cc, lat) for (r, c, p, comp, cr, cc, lat) in rows]

    def close(self) -> None:
        self._conn.close()


class MeteredPort:
    """Wrap a ModelPort so every completion is recorded to the meter (fail-soft).

    Satisfies ModelPort structurally. The inner call is NOT guarded — a real model failure
    propagates unchanged; only the meter write is guarded.
    """

    def __init__(self, inner: ModelPort, *, meter: ModelMeter, role: str, provider: str) -> None:
        self._inner = inner
        self._meter = meter
        self._role = role
        self._provider = provider

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        t0 = time.perf_counter()
        resp = await self._inner.complete(
            messages=messages,
            model=model,
            response_schema=response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        try:
            # Cache fields via getattr-with-default: present once the usage-parse spec lands
            # (Usage gains cache_read_tokens/cache_creation_tokens, defaults 0); zeros before.
            # Either build order works — neither spec blocks the other.
            self._meter.record(
                self._role,
                self._provider,
                resp.model_id,
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                latency_ms=latency_ms,
                cache_read_tokens=int(getattr(resp.usage, "cache_read_tokens", 0)),
                cache_creation_tokens=int(getattr(resp.usage, "cache_creation_tokens", 0)),
            )
        except Exception:  # noqa: BLE001 — metering must never fail the model call
            _log.warning("model_meter: record failed for role %r", self._role, exc_info=True)
        return resp
```

### Task 2 — `src/artemis/model/roles.py` (modify)

**a.** Add import (near the other `artemis.model.*` imports):
```python
from artemis.model.meter import ModelMeter, MeteredPort
```

**b.** Add `DropReason` + `DroppedOverride` beside `RoleBinding` / `RoleConstraints` (add
`from typing import Literal` to the imports). `reason` is a FIXED enum of static strings — never
`str(exc)` or any interpolation of file content (security FLAG 2):
```python
DropReason = Literal[
    "malformed_entry",
    "unknown_provider",
    "no_tools_ineligible",
    "router_restricted",
    "judge_conflict",
]


@dataclass(frozen=True)
class DroppedOverride:
    """A persisted override the fail-closed load path discarded, with a panel-surfaceable reason.

    role is ALWAYS a member of ROLES (non-ROLES file keys are never emitted); reason is a static
    enum value — tampered file content can never reach the API response through this type.
    """

    role: str
    reason: DropReason
```

**c.** Extend `ModelRoleRegistry.__init__` — add `meter: ModelMeter | None = None` (last kw-only
param) and store `self._meter = meter`. All existing params unchanged.

**c2.** Amend `_validate_entry` (part-1 method; security FLAG 1) — append one rule at the end, so
an empty/whitespace model is rejected on write AND dropped on the fail-closed load path (which
reuses `_validate_entry`):
```python
        if binding.provider != "router" and not binding.model.strip():
            raise RoleRegistryError("model must be non-empty for a non-router provider")
```
(`router` bindings keep `model == ""` — the sentinel ignores it; part-1 defaults unchanged.)

**d.** In `for_role`, wrap the resolved port in `MeteredPort` when a meter is present. Replace the
return path so the router branch is metered too:
```python
    def for_role(self, role: str) -> ModelPort:
        binding = self.get(role)
        if binding.provider == "router":
            port: ModelPort = self._router_factory()
        else:
            factory = self._provider_factory.get(binding.provider)
            if factory is None:
                raise RoleRegistryError(f"no provider factory for {binding.provider!r}")
            client = ModelClient(factory(), model_default=binding.model)
            port = _RoleConstrainedPort(
                client, force_temperature=constraints_for(role).temperature
            )
        if self._meter is None:
            return port
        return MeteredPort(port, meter=self._meter, role=role, provider=binding.provider)
```

**e.** Add two read methods (panel-UX contract from part 1's "Panel-UX contract notes"):
```python
    def eligible_providers(self, role: str) -> list[str]:
        """Providers a put(role, ...) would accept — mirrors _validate_entry per-provider, so the
        panel dropdown only OFFERS valid providers (a no_tools role never even shows codex)."""
        if role not in ROLES:
            raise RoleRegistryError(f"unknown role: {role!r}")
        no_tools = constraints_for(role).no_tools
        out: list[str] = []
        for provider in PROVIDERS:
            if provider == "router":
                if role in _ROUTER_ROLES:
                    out.append(provider)
                continue
            if no_tools and provider not in _NO_TOOLS_PROVIDERS:
                continue
            out.append(provider)
        return out

    def dropped_overrides(self) -> list[DroppedOverride]:
        """Persisted entries the fail-closed load path discarded (invalid/tampered), with STATIC
        enum reasons — so a silently-reverted binding is explained in the panel, never mysterious,
        and tampered file content is never reflected (non-ROLES keys are dropped silently)."""
        dropped: list[DroppedOverride] = []
        for role, entry in self._load_raw().items():
            if role not in ROLES:
                continue  # tampered/unknown key: never echoed anywhere
            reason = self._classify_drop(role, entry)
            if reason is not None:
                dropped.append(DroppedOverride(role=role, reason=reason))
        # Post-merge cross-role drop: a hand-edited judge==loop_driver bypasses put().
        sanitized = self._sanitized_overrides()
        merged = dict(_DEFAULTS)
        merged.update(sanitized)
        if "judge" in sanitized and merged["judge"] == merged["loop_driver"]:
            dropped.append(DroppedOverride(role="judge", reason="judge_conflict"))
        return dropped

    def _classify_drop(self, role: str, entry: object) -> DropReason | None:
        """Static drop reason for a raw persisted entry of a KNOWN role; None = entry is valid.

        Rule-for-rule mirror of the malformed-shape check + _validate_entry (role already known
        valid here). Returns only DropReason constants — never exception text.
        """
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("provider"), str)
            or not isinstance(entry.get("model"), str)
        ):
            return "malformed_entry"
        provider, model = entry["provider"], entry["model"]
        if provider not in PROVIDERS:
            return "unknown_provider"
        if provider == "router" and role not in _ROUTER_ROLES:
            return "router_restricted"
        if constraints_for(role).no_tools and provider not in _NO_TOOLS_PROVIDERS:
            return "no_tools_ineligible"
        if provider != "router" and not model.strip():
            return "malformed_entry"
        return None
```
`eligible_providers` is exactly the per-provider acceptance set of `_validate_entry` (unknown
providers are excluded by iterating `PROVIDERS`; the cross-role judge≠loop_driver invariant is not a
per-provider rule and still surfaces as a 422 on PUT). `_classify_drop` mirrors `_validate_entry`
rule-for-rule (incl. the new empty-model rule) so the surfaced list always matches what the load
path actually dropped.

### Task 3 — `src/artemis/api/model_routes.py` (create)

Session-gated (`require_session`) typed DTOs. Mirror `secret_routes.py` (prefix `/app`, `_store`-style
accessor, `Depends(require_session)`).

```python
"""Session-gated model-role registry + per-role usage routes (ADR-049 #2, #4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from artemis.api.auth import Principal, require_session
from artemis.model.meter import ModelMeter
from artemis.model.roles import (
    PROVIDERS,
    ROLES,
    DropReason,
    ModelRoleRegistry,
    RoleBinding,
    RoleRegistryError,
)

# Boundary pinning (mirrors secret_routes' pattern idiom): reject junk before it reaches the
# registry. model allows "" only so router bindings round-trip — the registry 422s an empty
# model for any non-router provider.
_PROVIDER_PATTERN = r"^[a-z_]{1,32}$"
_MODEL_PATTERN = r"^[A-Za-z0-9._:-]{0,64}$"


class ConstraintsDTO(BaseModel):
    no_tools: bool
    temperature: float | None


class RoleBindingDTO(BaseModel):
    role: str
    provider: str
    model: str
    constraints: ConstraintsDTO
    eligible_providers: list[str]
    editable_fields: list[str] = ["provider", "model"]


class DroppedOverrideDTO(BaseModel):
    role: str  # always a member of ROLES (registry never emits a non-ROLES key)
    reason: DropReason  # static enum — never file-content interpolation


class ModelsResponse(BaseModel):
    roles: list[RoleBindingDTO]
    providers: list[str]
    dropped_overrides: list[DroppedOverrideDTO]


class RoleUpdateRequest(BaseModel):
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    model: str = Field(pattern=_MODEL_PATTERN)


class RoleUsageDTO(BaseModel):
    role: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    avg_latency_ms: float


class UsageResponse(BaseModel):
    roles: list[RoleUsageDTO]


router = APIRouter(prefix="/app")


def _registry(request: Request) -> ModelRoleRegistry:
    reg: ModelRoleRegistry = request.app.state.model_roles
    return reg


def _meter(request: Request) -> ModelMeter:
    meter: ModelMeter = request.app.state.model_meter
    return meter


def _binding_dto(reg: ModelRoleRegistry, role: str) -> RoleBindingDTO:
    binding = reg.get(role)
    constraints = reg.constraints(role)
    return RoleBindingDTO(
        role=role,
        provider=binding.provider,
        model=binding.model,
        constraints=ConstraintsDTO(
            no_tools=constraints.no_tools, temperature=constraints.temperature
        ),
        eligible_providers=reg.eligible_providers(role),
    )


@router.get("/models", response_model=ModelsResponse)
async def list_models(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> ModelsResponse:
    reg = _registry(request)
    return ModelsResponse(
        roles=[_binding_dto(reg, role) for role in ROLES],
        providers=list(PROVIDERS),
        dropped_overrides=[
            DroppedOverrideDTO(role=d.role, reason=d.reason) for d in reg.dropped_overrides()
        ],
    )


@router.put("/models/{role}", response_model=RoleBindingDTO)
async def put_model(
    role: str,
    body: RoleUpdateRequest,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> RoleBindingDTO:
    reg = _registry(request)
    try:
        reg.put(role, RoleBinding(provider=body.provider, model=body.model))
    except RoleRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _binding_dto(reg, role)


@router.get("/models/usage", response_model=UsageResponse)
async def usage_models(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> UsageResponse:
    rows = _meter(request).usage()
    return UsageResponse(
        roles=[
            RoleUsageDTO(
                role=u.role,
                calls=u.calls,
                prompt_tokens=u.prompt_tokens,
                completion_tokens=u.completion_tokens,
                cache_read_tokens=u.cache_read_tokens,
                cache_creation_tokens=u.cache_creation_tokens,
                avg_latency_ms=u.avg_latency_ms,
            )
            for u in rows
        ]
    )
```
Route note: `PUT /models/{role}` never matches `GET /models/usage` (different method); `GET
/models/usage` is a distinct literal path from `GET /models`. No ordering hazard.

### Task 4 — `src/artemis/api/app.py` (modify)

**a.** Add imports — extend the `from artemis.api import ... secret_routes` group with `model_routes`,
and add:
```python
from artemis.model.meter import ModelMeter
```

**b.** Construct the meter immediately BEFORE the part-1 `app.state.model_roles = ModelRoleRegistry(...)`
line:
```python
    app.state.model_meter = ModelMeter(
        str(resolved_data_dir / "model_meter.db"), check_same_thread=False
    )
```

**c.** Modify the part-1 registry construction to pass the meter:
```python
    app.state.model_roles = ModelRoleRegistry(
        resolved_data_dir / "model_roles.json",
        router_factory=lambda: app.state.model,
        meter=app.state.model_meter,
    )
```

**d.** Register the router beside the others (with the other `app.include_router(...)` calls):
```python
    app.include_router(model_routes.router)
```

### Task 5 — `tests/test_model_meter.py` (create)

Hermetic: in-memory / `tmp_path` SQLite, a fake `ModelPort`. No network, no CLI.

```python
class _FakePort:  # satisfies ModelPort
    def __init__(self, *, model_id: str = "sonnet", usage: Usage | None = None) -> None:
        self._model_id = model_id
        self._usage = usage or Usage(prompt_tokens=3, completion_tokens=5, total_tokens=8)
    async def complete(self, *, messages, model=None, response_schema=None,
                       temperature=0.7, max_tokens=None):  # type: ignore[no-untyped-def]
        return ModelResponse(text="{}", model_id=self._model_id, structured=None,
                             finish_reason="stop", usage=self._usage)
```

Cases (each = one `assert`-bearing test):
1. **aggregation** → `ModelMeter(":memory:")`; `record("selector","claude_code","haiku",prompt_tokens=3,completion_tokens=5,latency_ms=10)` twice + one `record("extractor",...)`; `usage()` → two `RoleUsage`, selector `calls==2`, `prompt_tokens==6`, `completion_tokens==10`, extractor `calls==1`; ordered alphabetically (extractor before selector).
2. **avg latency** → record latencies `10` and `20` for one role → `usage()[0].avg_latency_ms == 15.0`.
3. **MeteredPort records actually-served model + binding provider** → `MeteredPort(_FakePort(model_id="sonnet"), meter=m, role="synth", provider="router")`; `await port.complete(messages=[Message("user","hi")])`; `m._conn.execute("SELECT role, provider, model FROM calls").fetchone() == ("synth","router","sonnet")` (router-bound role meters the backend model, not the sentinel), `latency_ms >= 0`.
4. **MeteredPort is fail-soft** → `monkeypatch.setattr(m, "record", _raise)`; `resp = await MeteredPort(_FakePort(model_id="haiku"), meter=m, role="selector", provider="claude_code").complete(messages=[...])`; no exception, `resp.model_id == "haiku"`.
5. **inner failure propagates** → a `_FakePort` whose `complete` raises → `MeteredPort(...).complete(...)` raises the SAME error (only the meter write is guarded, not the model call).
6. **persistence** → `ModelMeter(str(tmp_path/"m.db"))`; record one call; `close()`; a NEW `ModelMeter` over the same path → `usage()` still returns the row (durable).
7. **empty meter** → fresh `ModelMeter(":memory:").usage() == []`.
8. **static conformance** → `_check: ModelPort = MeteredPort(_FakePort(), meter=m, role="selector", provider="claude_code")` type-checks (proves `MeteredPort` satisfies `ModelPort`).
9. **cache tokens recorded + aggregated, build-order independent** → (a) a fake response whose `usage` object carries `cache_read_tokens=7` and `cache_creation_tokens=11` (if `Usage` doesn't yet have the fields, use a stand-in usage object exposing all five attributes — the meter reads via getattr): two `MeteredPort` completions → `usage()[0].cache_read_tokens == 14` and `.cache_creation_tokens == 22`; (b) a plain 3-field `Usage(prompt_tokens=3, completion_tokens=5, total_tokens=8)` WITHOUT the cache attributes → recorded row has `cache_read_tokens == 0` and `cache_creation_tokens == 0`, no raise.

### Task 6 — `tests/test_model_routes.py` (create)

Mirror `tests/test_api_layout.py`'s `_client` helper (override `require_session` with a fixed
`Principal`, `TestClient(create_app(data_dir=str(tmp_path)))`).

Cases:
1. **GET /app/models lists nine roles + constraints + eligibility** → `200`; `len(body["roles"]) == 9`; every role has `provider`/`model`/`constraints`/`eligible_providers`/`editable_fields==["provider","model"]`; `body["providers"] == list(PROVIDERS)`; the `reader` row's `eligible_providers == ["claude_code","ollama"]` and its `constraints == {"no_tools": True, "temperature": None}`; the `extractor` row's `constraints["temperature"] == 0.0`; the `synth` row's `eligible_providers` contains `"router"`; `body["dropped_overrides"] == []`.
2. **PUT edits a binding (no restart)** → `PUT /app/models/loop_driver {"provider":"codex","model":"gpt-5.5"}` → `200`, returns `provider=="codex"`; a follow-up `GET /app/models` shows `loop_driver` provider `codex` (same app instance — call-time resolution).
3. **PUT 422 on invariant violation** → each returns `422` with a non-empty `detail`: `PUT /app/models/reader {"provider":"codex","model":"gpt-5.5"}` (no-tools eligibility); `PUT /app/models/judge {"provider":"claude_code","model":"haiku"}` (equals loop_driver default); `PUT /app/models/nope {"provider":"codex","model":"x"}` (unknown role); `PUT /app/models/reader {"provider":"router","model":""}` (router on a non-router role); `PUT /app/models/selector {"provider":"claude_code","model":""}` (empty model, non-router — registry rule); `PUT /app/models/selector {"provider":"claude_code","model":"a b/../c"}` (charset violation — DTO pattern rejects before the registry). After all of the above, `GET /app/models` still shows every default binding (nothing persisted).
4. **GET /app/models/usage per-role aggregates** → before any call `body["roles"] == []`; then `app.state.model_meter.record("selector","claude_code","haiku",prompt_tokens=2,completion_tokens=4,latency_ms=7,cache_read_tokens=1,cache_creation_tokens=6)`; `GET /app/models/usage` → one row `{"role":"selector","calls":1,"prompt_tokens":2,"completion_tokens":4,"cache_read_tokens":1,"cache_creation_tokens":6,"avg_latency_ms":7.0}`.
5. **dropped-override surfacing (fail-closed end-to-end)** → write `{"reader": {"provider":"codex","model":"gpt-5.5"}}` to `tmp_path/"model_roles.json"` BEFORE `create_app`; `GET /app/models` → the `reader` row still shows the DEFAULT binding (`claude_code`/`haiku`, override dropped on load) AND `dropped_overrides` contains exactly `{"role":"reader","reason":"no_tools_ineligible"}` (static enum value, not exception text).
6. **tampered file content is never echoed** → write `{"<img src=x onerror=alert(1)>": {"provider":"evil<script>","model":"x"}, "phraser": {"provider":"claude_code","model":"   "}}` to the registry path BEFORE `create_app`; `GET /app/models` → `200`; the raw response text contains NEITHER `"<img"` NOR `"<script"` NOR `"evil"` anywhere (non-ROLES key dropped silently, provider string never reflected); `dropped_overrides == [{"role":"phraser","reason":"malformed_entry"}]` (whitespace model dropped on load); the `phraser` row shows its default binding.
7. **session gate** → `TestClient(create_app(data_dir=str(tmp_path)))` with NO `require_session` override → `GET /app/models` returns `401`.

## Acceptance criteria
1. Meter suite → `uv run pytest -q tests/test_model_meter.py` passes all nine cases (incl. router-bound role meters `ModelResponse.model_id` not the sentinel; fail-soft record; inner-failure propagation; persistence; cache tokens recorded + aggregated AND a cache-field-less `Usage` records zeros without raising — build-order independence vs the usage-parse spec).
2. Endpoint suite → `uv run pytest -q tests/test_model_routes.py` passes all seven cases (list + constraints/eligibility, edit-without-restart, the six 422 rejections incl. empty-model + DTO charset pinning, usage aggregates, dropped-override surfacing with static enum reasons, tampered-content never echoed, 401 session gate).
3. Fail-soft is real → in case 4 of the meter suite, a meter whose `record` raises does not fail `MeteredPort.complete` (response returned, warning logged).
4. Zero behavior change to existing paths → `uv run pytest -q` full suite stays green (the meter only wraps `for_role` results; a call with `usage=Usage(0,0,0)` records a zero-token row and changes nothing observable).
5. Security-FLAG regressions hold → PUT with an empty model on a non-router provider → 422; a file override with an empty/whitespace model is dropped on load (case 6); no fragment of a tampered registry file (non-ROLES key or provider string) appears in any `GET /app/models` response byte; every `dropped_overrides[].reason` is one of the five `DropReason` constants.
6. Type + lint clean → `uv run mypy` clean (`MeteredPort` satisfies `ModelPort`; DTOs typed; `DropReason` Literal flows registry→DTO); `uv run ruff check .` + `uv run ruff format --check .` clean.
7. Surgical → `git diff --stat` shows only the six files above.

## Commands to run
```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q tests/test_model_meter.py tests/test_model_routes.py
uv run pytest -q
```

## Re-flagged follow-up (part-1 header tracked item — NOT migrated here)

Part 1's header tracked two composition roots for `for_role` migration "in part 2 or the loop arc,
whichever touches them first". **This spec does NOT migrate them** — a reasoned deferral, not a silent
drop:
- `src/artemis/app.py:~96` (`_build_ingress` → `IntentRouter(ModelClient(ClaudeCodeProvider(), "haiku"))`)
  and `src/artemis/reachout/web_tool.py:~293,298-303` (reader + a heterogeneous `QuotaAwareRouter`)
  are CLI/reachout roots with **no `app.state`** — migrating them cleanly requires constructing a
  `ModelRoleRegistry` (and now a `ModelMeter`) at each root, which is registry *placement* design, not
  metering.
- `web_tool.py`'s synth is a **deliberately heterogeneous** router (each backend keeps its own
  `model_default`; a documented "never force a single model string" constraint). `for_role("synth")`
  returns the api's `QuotaAwareRouter` (`app.state.model`) — a **different** object with different
  failover semantics. Rebinding it is a behavior change, not a like-for-like swap, and belongs to the
  loop arc that actually owns those roots.

Recommendation: the agent-loop arc migrates both (it constructs these roots and can place a shared
registry+meter there). This keeps part 2 to the cohesive metering+endpoint unit. The tracked item
stays open — carried to `docs/status.md` for the loop arc.

## Open items flagged (planning)
1. **Token counts are currently zero** — `ModelClient.complete` returns `Usage(0,0,0)` (providers
   don't yet surface real token usage). The meter records faithfully (zeros today); `prompt_tokens`/
   `completion_tokens` become meaningful only once a provider populates `ModelResponse.usage`. Latency
   and call counts are live immediately. No blocker — noted so "usage shows zeros" isn't read as a bug.
2. **Scoped-out roots deferred to the loop arc** (see "Re-flagged follow-up") — needs a planning
   decision on where the CLI/reachout registry+meter live; do not silently drop.
