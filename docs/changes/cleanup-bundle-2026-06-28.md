---
status: ready
---

# cleanup-bundle-2026-06-28

**Identity:** Bundle of 4 small carried items from the 2026-06-27 handoff + tonight: align the client to the brain's `/review/auto-enabled` contract, harden `test_health.py` TestClient teardown, delete dead `_EnvKeyProvider`, and refresh CHANGELOG/README.

## Files to change

- `C:\Users\User\artemis\client\src-tauri\src\gateway.rs` — modify
- `C:\Users\User\artemis\client\src\api\gateway.ts` — modify
- `C:\Users\User\artemis\client\src\screens\ReviewDetail.tsx` — modify
- `C:\Users\User\artemis\tests\test_health.py` — modify
- `C:\Users\User\artemis\src\artemis\dev\email_rules.py` — modify
- `C:\Users\User\artemis\CHANGELOG.md` — modify
- `C:\Users\User\artemis\README.md` — modify (light, conditional)

## Exact changes

### Task 1 — `/review/auto-enabled` contract: align the client to the brain

Brain (source of truth) serves `GET /app/review/auto-enabled` → `list[ReviewItem]` (`src/artemis/api_app.py:740`, backed by `ReviewSurface.auto_enabled()` in `recipes/review.py`, which mirrors `/review/pending`). The client requests the underscore path `/app/review/auto_enabled` and expects `bool` — that path 404s and the shape is wrong. The brain is well-formed; the **client moves**. The UI keeps its boolean "enabled / paused" copy by deriving it from the list.

Files: `client/src-tauri/src/gateway.rs`, `client/src/api/gateway.ts`, `client/src/screens/ReviewDetail.tsx`.

1. `gateway.rs` — `review_auto_enabled` (line ~277-279): rename path and change shape:

```rust
pub(crate) async fn review_auto_enabled(state: &AppState) -> Result<Vec<ReviewItem>, GatewayError> {
    request_json::<Vec<ReviewItem>, ()>(state, Method::GET, "/app/review/auto-enabled", None, true).await
}
```

2. `gateway.rs` — the `#[tauri::command] app_review_auto_enabled` (line ~460-463): change return type to `Result<Vec<ReviewItem>, GatewayError>` (body unchanged — it just forwards `review_auto_enabled`).

3. `gateway.ts` — line 27:

```ts
export const reviewAutoEnabled = (): Promise<ReviewItem[]> => call("app_review_auto_enabled");
```

4. `ReviewDetail.tsx` — change the prop type (line 13) `autoReader?: () => Promise<ReviewItem[]>;` and, in the `Promise.all().then(([pendingActions, pending, auto]) => …)` body (line ~57), derive the boolean from the list, keeping the existing `autoEnabled` boolean state and the "enabled / paused" copy at line 135:

```ts
        setAutoEnabled(auto.length > 0);
```

### Task 2 — `test_health.py` TestClient lifecycle hardening

File: `tests/test_health.py`. The module-level `client = TestClient(app)` never enters/exits the lifespan context, leaking the anyio portal thread; combined with the `winsdk` import this trips a `0xc0000374` heap corruption at interpreter teardown. Replace the module-level client with a context-managed fixture so lifespan startup/shutdown runs and the portal thread is joined:

```python
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from artemis.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
```

Remove the module-level `client = TestClient(app)`. Add `client: TestClient` as a parameter to `test_healthz` and `test_readyz` (bodies otherwise unchanged).

### Task 3 — delete dead `_EnvKeyProvider`

File: `src/artemis/dev/email_rules.py`. `_EnvKeyProvider` (lines ~213-233) is unused — the CLI uses `build_owner_key_provider` (confirmed: repo-wide grep for `_EnvKeyProvider` hits only its definition + handoff/done-spec notes). Delete the class. Then remove the orphans **it** alone kept alive:

- `import os` (line 17) — used only inside `_EnvKeyProvider`.
- `SecretKey` from `from artemis.identity.key_provider import KeyProvider, SecretKey` (line 26) → keep `KeyProvider`, drop `SecretKey`.
- `class BuildKeyProviderError` (line ~73) — only referenced by `_EnvKeyProvider`. Before deleting, grep `BuildKeyProviderError` across `src/` and `tests/`; remove it only if no other reference exists, else leave it.

Let `ruff` (F401/unused) be the gate for any missed orphan.

### Task 4 — CHANGELOG + README refresh (light)

File: `CHANGELOG.md`. The win-brain-runtime, CLIENT-auth core, live overlay (separate Ask window + brain connection), and GATE-b pending-actions surface work — plus tonight's fixes — are not reflected. Append bullets under the existing `## [Unreleased]` section (`### Added` / `### Changed` / `### Fixed` as appropriate); keep entries one line each and point at `git log` for detail rather than re-listing files. Suggested:

- Added: Tauri desktop client — app auth/pairing, the spatial command-map shell, live Ask overlay (floating window + brain connection), and the pending-actions / recipe review surface (GATE-b).
- Added: Windows brain runtime bring-up.
- Fixed: client now calls the brain's `/review/auto-enabled` contract; quarantine reader tolerates local-model prose output; `test_health.py` teardown hardened; removed dead `_EnvKeyProvider`.

File: `README.md` — conditional/light: if (and only if) the README has a Components / Status / Architecture section that enumerates the brain without the client, add a single line noting the Tauri client lives under `client/`. Otherwise no README change.

## Acceptance criteria

- Task 1: `cargo check` (in `client/src-tauri`) passes; `grep -rn "auto_enabled" client/src-tauri/src client/src` shows the Tauri command name only, no underscore HTTP path; `cd client && npx tsc --noEmit` passes.
- Task 2: `uv run pytest -q tests/test_health.py` passes on a clean run with no teardown error.
- Task 3: `uv run ruff check src/artemis/dev/email_rules.py` clean (no F401); `grep -rn "_EnvKeyProvider" src/` returns nothing.
- Task 4: `## [Unreleased]` in `CHANGELOG.md` contains the new client + fixes bullets.

## Commands to run

```bash
uv run mypy
uv run pytest -q
cd client && npx tsc --noEmit && cargo check --manifest-path src-tauri/Cargo.toml
```
