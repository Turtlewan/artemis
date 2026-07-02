---
spec: secret-routes
status: ready
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: high
cross_model_review: true
risk: high
---

# Spec: 4a — secret CRUD routes over the cred-store (brain half of secret-capture)

**Identity:** Session-gated `/app/secrets` routes (set / list-names / delete) backed by the
keyring `SecretStore`, and wire the store onto `app.state`. Brain foundation the step-4 client
modal (4b) and the step-5 build-flow gate consume.
→ why: ADR-035 enabler #2 (secret-capture); builds on `cred-store` (SecretStorePort).

## Assumptions
- `KeyringSecretStore(index_path, *, backend=None)` exists (secrets_store.py) implementing
  `SecretStorePort` (get/set/delete/list_names) → impact: Low
- `create_app(...)` in src/artemis/api/app.py builds `app.state` and registers routers; adding
  `app.state.secrets` + a new router mirrors the existing pattern (e.g. forge / capability_routes)
  → impact: Caution (follow the existing app.state + include_router style exactly)
- All /app/* routes are session-gated via `require_session` (see ask_routes.py / capability_routes.py)
  → impact: Low

Simplicity check: considered folding secrets into an existing router — rejected; a dedicated
`secret_routes.py` keeps the credential surface isolated + easy to security-review.

## Prerequisites
- Specs complete first: cred-store (done)
- Environment: `uv sync`

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/api/app.py | modify | construct `app.state.secrets = KeyringSecretStore(<data_dir>/secrets_index.json)` (injectable seam for tests, mirroring the `sandbox`/`forge` seams) + `include_router(secret_routes.router)` |
| src/artemis/api/secret_routes.py | create | session-gated POST /app/secrets, GET /app/secrets, DELETE /app/secrets/{name} |
| tests/api/test_secret_routes.py | create | in-memory store: set→list→get(via store)→delete; GET returns names only; values never in any response body |

## Tasks
- [ ] Task 1: secret_routes.py — files: src/artemis/api/secret_routes.py — done when: an APIRouter(prefix="/app") with:
  - `POST /secrets` body `{name: str, value: str}` → `store.set(name, value)` → 204 No Content, EMPTY body (never echo the value or the name back with the value).
  - `GET /secrets` → `{names: list[str]}` (from `store.list_names()`) — NAMES ONLY, never values.
  - `DELETE /secrets/{name}` → `store.delete(name)` → 204.
  All three `Depends(require_session)`. The store is read from `request.app.state.secrets` via a `_store(request)` dep (mirror ask_routes `_router`). Never log a secret value. mypy clean.
- [ ] Task 2: wire the store into create_app — files: src/artemis/api/app.py — done when: `create_app` sets `app.state.secrets` to a `SecretStorePort` (default `KeyringSecretStore(Path(data_dir)/"secrets_index.json")`, with a `secrets: SecretStorePort | None = None` injection param mirroring the existing `sandbox` seam) and `app.include_router(secret_routes.router)`; `uv run mypy` clean.
- [ ] Task 3: tests — files: tests/api/test_secret_routes.py — done when: `uv run pytest tests/api/test_secret_routes.py -q` passes with an INJECTED in-memory SecretStore (no real keychain). Assert: POST then GET shows the name; POST response body is empty (no value echoed); GET body contains names but NOT values; DELETE removes it from GET; all routes 401/403 without a session (reuse the app's session-gating test pattern).

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/api/secret_routes.py, tests/api/test_secret_routes.py |
| Modify | src/artemis/api/app.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run pytest tests/api/test_secret_routes.py -q` | route tests |
| `uv run mypy` | typecheck |
| `uv run ruff check src tests` | lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/api/app.py src/artemis/api/secret_routes.py tests/api/test_secret_routes.py |
| `git commit` | "feat: session-gated secret CRUD routes over the cred-store" |

### Network
| Action | Purpose |
|--------|---------|
| (none) | local store only |

## Specialist Context
### Security
- apex-security MUST review. Invariants: session gate on all three routes; GET returns NAMES ONLY
  (never values); POST/DELETE return empty 204 (no value echo); no secret value in logs or error
  messages; the store namespace + index path live under the app data dir (not web-served).
- No new egress. The store is host-side; these routes never hand the store into the sandbox.

### Performance
(none)

### Accessibility
(none — routes only; UI is 4b)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/api/secret_routes.py | docstrings; note no-value-echo / no-log invariant |

## Acceptance Criteria
- [ ] Set → list shows name → delete removes it → verify: Task 3 tests green
- [ ] GET returns names only, POST/DELETE echo no value → verify: Task 3 asserts response bodies
- [ ] Session-gated → verify: Task 3 asserts unauthenticated calls are rejected
- [ ] Full gate green → verify: `uv run mypy` + `uv run ruff check src tests` + `uv run pytest -q` exit 0

## Progress
_(Coding mode writes here — do not edit manually)_
