---
spec: gate-b-action-review-surface
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seam 3) + cal-gate.md BLOCKs B2, B3 -->

# Spec: GATE-b — Pending-actions review surface (brain endpoints)

> **⚠️ RE-SCOPED 2026-06-27 (Tauri client rewrite, ADR-028):** this spec now ships **only the brain
> endpoints (Tasks 1–3)** — Windows-buildable now, framework-agnostic. The **Swift/ArtemisKit client
> half (Tasks 4–8: `WireModels`/`ApiClient`/`ReviewScreen.swift`) is SUPERSEDED** by
> **`docs/changes/GATE-b-client.md`** (the Tauri "Pending actions" surface). Do NOT build Tasks 4–8;
> they are retained below only as the contract source for the Tauri rewrite. (Housekeeping: the dead
> Swift tasks + their Files/Permissions rows can be pruned in a later pass.)

**Identity:** Adds the owner-approval surface for one-off pending actions — three `require_unlocked` brain endpoints (`GET /app/actions/pending`, `POST /app/actions/approve`, `POST /app/actions/reject`) + matching `ActionStagingService` wiring in `main.py`. The client surface lives in `GATE-b-client` (Tauri). Parallel to the existing recipe Review surface.
→ why: see docs/technical/adr/ADR-012-gated-action-staging.md (pending-action model + two-tier guard + client surface §4).

<!-- Split rule: 3 logical layers (brain HTTP / Swift DTO+client / SwiftUI screen); each is cohesive and the brain layer is the only one that touches main.py (no fork risk). Split into separate specs would leave a non-callable client DTO before the endpoint exists; the three layers are a delivery unit. Touches 5 files: api_app.py (additive), main.py (additive), WireModels.swift (additive), ApiClient.swift (additive), ReviewScreen.swift (additive). -->

## Assumptions

- GATE-a (`ActionStagingService` + `PendingActionStore`) is complete with the following confirmed contract (bound to ADR-012 §3):
  - `ActionStagingService.list_pending() -> list[PendingAction]` — calls `expire_due(now)` first (marks any past-expiry rows EXPIRED), then delegates to `store.list_pending()`; returns only `PENDING`-status actions. This method is now confirmed on GATE-a Task 3 (added per B2 / Seam 3). `ToolSpec.name` is bare; `module.tool` is the registry id used by `stage()`/`get_tool()`.
  - `ActionStagingService.approve(id: str) -> PendingAction` — **`async def`** (ADR-016 / Seam 3; the route `await`s it); executes once, sets `APPROVED`; raises `KeyError` if not found, `ValueError` if not `PENDING` (confirmed: plain `ValueError`, no dedicated subclass), `ScopeLockedError` if vault is locked during dispatch (propagates unwrapped from `callable_ref`).
  - `ActionStagingService.reject(id: str) -> PendingAction` — sets `REJECTED`; raises `KeyError` if not found, `ValueError` if not `PENDING`; no tool dispatch, no `ScopeLockedError` path.
  - `PendingAction` is a frozen Pydantic model with fields: `id: str`, `module: str`, `tool: str`, `args: dict[str, object]`, `summary: str`, `action_class: Literal["takes-action"]` (confirmed by GATE-a Task 1 — value is `"takes-action"`, lowercase hyphen), `status: ActionStatus` (enum values: `"pending"` | `"approved"` | `"rejected"` | `"expired"` — lowercase, confirmed by GATE-a `ActionStatus(StrEnum)`), `created_at: datetime`, `expires_at: datetime`, `result: dict[str, object] | None`.
  - The "already settled" exception is `ValueError` — confirmed by GATE-a Task 3: `raise ValueError(f"Cannot approve action {action_id}: status is {action.status}")` (and identically for `reject`). No dedicated `ActionAlreadySettledError` exists. The 409 mapping to `ValueError` in the routes below is correct as written.
  - `list_pending()` filters by `status = "pending"` at the SQL layer (GATE-a Task 2: `SELECT WHERE status = "pending"`). EXPIRED rows are never returned. No additional `status == "PENDING"` filter is needed in the endpoint.
- CLIENT-b (`api_app.py`) is complete: `require_unlocked`, `require_session`, `app_router`, pydantic response-model conventions, `app.state.key_provider`, `app.state.review_surface`, TestClient scaffold with `FakeKeyProvider`. → impact: Stop (GATE-b adds routes to `app_router` and a new `app.state` entry; CLIENT-b must exist for the imports to resolve).
- CLIENT-c (`WireModels.swift`, `ApiClient.swift`) is complete: the DTO + client pattern to mirror. → impact: Stop (GATE-b extends these files additively).
- CLIENT-e (`ReviewScreen.swift`) is complete: `ReviewModel`, `ReviewScreen` with Pending/Auto-enabled sections. → impact: Stop (GATE-b adds a "Pending actions" section to the same screen).
- `app.state.action_staging` is the attribute name for the `ActionStagingService` instance (matches the `app.state.review_surface` naming convention from CLIENT-b). → impact: Caution (if GATE-a wires it under a different name, update the routes accordingly).

Simplicity check: considered a combined `/app/review/unified` endpoint returning both recipe reviews and pending actions — rejected; ADR-012 §4 explicitly requires two separate surfaces with distinct semantics; a unified endpoint would conflate approve-execute vs approve-enable. Three thin endpoint additions + additive DTO/client/UI modifications is the minimum viable surface.

## Prerequisites

- Specs that must be complete first: GATE-a (`ActionStagingService` + `PendingActionStore`), CLIENT-b, CLIENT-c, CLIENT-e.
- Environment setup required: none beyond CLIENT-b's `pytest`/`fastapi[testing]` and CLIENT-c/e's Swift 6 toolchain. Off-device testable via FastAPI `TestClient` + a `FakeActionStagingService`; the tailnet live round-trip is gated on-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/api_app.py` | modify | additive: `PendingActionResponse` model, 3 new routes on `app_router`, `FakeActionStagingService` for tests |
| `src/artemis/main.py` | modify | additive: construct `ActionStagingService` at startup, attach to `app.state.action_staging` |
| `swift/ArtemisKit/Sources/ArtemisKit/WireModels.swift` | modify | additive: `PendingActionResponse` DTO |
| `swift/ArtemisKit/Sources/ArtemisKit/ApiClient.swift` | modify | additive: `pendingActions(token:)`, `approveAction(id:token:)`, `rejectAction(id:token:)` |
| `swift/ArtemisApp/Sources/Screens/ReviewScreen.swift` | modify | additive: "Pending actions" section in `ReviewScreen`, `PendingActionRow` sub-view, `ReviewModel` additions |

## Tasks

- [ ] Task 1: Add `PendingActionResponse` pydantic model + three `/app/actions/*` routes — files: `src/artemis/api_app.py` (modify, additive only — do not touch any existing route or model) —

  **Response model** (add after the existing `ReviewItem` model):
  ```python
  class PendingActionResponse(BaseModel):
      id: str
      module: str
      tool: str
      summary: str
      action_class: str          # always "takes-action" (GATE-a Literal["takes-action"])
      status: str                # "pending" | "approved" | "rejected" | "expired" (GATE-a ActionStatus StrEnum, lowercase)
      created_at: datetime
      expires_at: datetime
      result: dict[str, object] | None = None  # matches GATE-a PendingAction.result: dict[str, object] | None

      @classmethod
      def from_pending_action(cls, pa: "PendingAction") -> "PendingActionResponse":
          return cls(
              id=pa.id, module=pa.module, tool=pa.tool, summary=pa.summary,
              action_class=pa.action_class, status=pa.status,
              created_at=pa.created_at, expires_at=pa.expires_at, result=pa.result,
          )
  ```
  Note: `args` is **intentionally excluded** from the response — the bound payload is owner-private internal state, not needed by the display surface (apex-security: surface only what the client renders).

  **Routes** (add at the end of `app_router`, after the existing review/chat/status routes):
  ```python
  # B3 fix: `request: Request` placed BEFORE defaulted `Depends(...)` params to avoid
  # Python SyntaxError (non-default argument after default argument).
  @app_router.get("/actions/pending", response_model=list[PendingActionResponse])
  async def get_pending_actions(
      request: Request,
      principal: Principal = Depends(require_unlocked),
  ) -> list[PendingActionResponse]:
      actions = request.app.state.action_staging.list_pending()
      return [PendingActionResponse.from_pending_action(a) for a in actions]

  @app_router.post("/actions/approve", response_model=PendingActionResponse)
  async def approve_action(
      request: Request,
      body: ActionIdRequest,
      principal: Principal = Depends(require_unlocked),
  ) -> PendingActionResponse:
      try:
          pa = await request.app.state.action_staging.approve(body.id)
      except KeyError:
          raise HTTPException(status_code=404, detail="action not found")
      except ValueError:
          raise HTTPException(status_code=409, detail="action already settled")
      return PendingActionResponse.from_pending_action(pa)

  @app_router.post("/actions/reject", response_model=PendingActionResponse)
  async def reject_action(
      request: Request,
      body: ActionIdRequest,
      principal: Principal = Depends(require_unlocked),
  ) -> PendingActionResponse:
      try:
          pa = request.app.state.action_staging.reject(body.id)
      except KeyError:
          raise HTTPException(status_code=404, detail="action not found")
      except ValueError:
          raise HTTPException(status_code=409, detail="action already settled")
      return PendingActionResponse.from_pending_action(pa)
  ```

  **Request model** (add with the other request models):
  ```python
  class ActionIdRequest(BaseModel):
      id: str
  ```

  Error mapping: `KeyError` → 404 `"action not found"`, `ValueError` → 409 `"action already settled"`. Add `except ScopeLockedError: raise HTTPException(423, "vault locked")` to the approve route — the vault can idle-lock between the `require_unlocked` dependency check and the awaited async dispatch (ADR-016: `approve` is `async`, awaited in the route), so `ScopeLockedError` can surface as a 500 without this guard. Consistent with CLIENT-b's fail-closed posture. Note: the exception is named `ScopeLockedError` (not `VaultLockedError`).

  All three routes use `require_unlocked` as the sole dependency (which itself depends on `require_session` via `Depends` — the two-tier guard from CLIENT-b §Security is inherited, not re-implemented). No session-only variant exists for these routes.

  — done when: `uv run mypy --strict src` passes; the three new symbols are importable.

- [ ] Task 2: Wire `ActionStagingService` into `main.py` — files: `src/artemis/main.py` (modify, additive only — do not touch any existing wiring) —

  In the startup/lifespan block, after the existing `ReviewSurface` construction, add:
  ```python
  from artemis.staging import ActionStagingService, PendingActionStore  # confirmed: GATE-a Task 4 re-exports both from artemis.staging.__init__
  app.state.action_staging = ActionStagingService(
      store=PendingActionStore(settings, app.state.key_provider),  # confirmed: PendingActionStore(settings: Settings, key_provider: KeyProvider) — GATE-a Task 2
      tool_registry=app.state.gateway.tool_registry,  # reuse the existing ToolRegistry from the gateway
  )
  ```
  The `ActionStagingService` takes the same `ToolRegistry` the brain already uses (ADR-012 §3: approve re-dispatches via `await ToolRegistry.get_tool(fq_name).callable_ref(args)` — ADR-016: `callable_ref` is `async def`; no second execution route). Do NOT create a second `ToolRegistry`.

  — done when: `uv run mypy --strict src` passes; `python -c "from artemis.main import app; assert hasattr(app.state, 'action_staging')"` (after startup) exits 0.

- [ ] Task 3: TestClient tests for the three action routes — files: `tests/test_api_app.py` (modify, additive — add a new test class/section after the existing tests) —

  Add a `FakeActionStagingService` (in-test, not a module-level singleton — injected via `app.state` override matching the CLIENT-b fake pattern):
  ```python
  class FakeActionStagingService:
      def __init__(self) -> None:
          self._pending: dict[str, FakePendingAction] = {
              "act-1": FakePendingAction(id="act-1", summary="Send invite to bob@example.com for 3pm Thu"),
          }
      def list_pending(self) -> list[FakePendingAction]: ...
      async def approve(self, id: str) -> FakePendingAction: ...  # async (ADR-016: route awaits it); raises KeyError / ValueError
      def reject(self, id: str) -> FakePendingAction: ...  # sync — reject route does not await
  ```

  Test cases (each sets `app.state.action_staging = FakeActionStagingService()`):
  - `GET /app/actions/pending` without bearer → 401 (session gate enforced first).
  - `GET /app/actions/pending` with session, vault **locked** → 423 (unlock gate enforced).
  - `GET /app/actions/pending` with session + unlocked → 200 + list containing `act-1`; response body does **not** contain `"args"` key (excluded).
  - `POST /app/actions/approve {"id": "act-1"}` unlocked → 200; response `status == "approved"` (GATE-a ActionStatus.APPROVED.value).
  - `POST /app/actions/approve {"id": "nonexistent"}` unlocked → 404.
  - `POST /app/actions/approve {"id": "act-1"}` (already approved) unlocked → 409.
  - `POST /app/actions/reject {"id": "act-1"}` unlocked → 200; response `status == "rejected"` (GATE-a ActionStatus.REJECTED.value).
  - `POST /app/actions/reject {"id": "nonexistent"}` unlocked → 404.
  - Regression: existing `/app/review/pending` still 200 with unlocked session; `/healthz` still 200.

  Mirror the CLIENT-b test style: reuse the existing `FakeKeyProvider`, the in-test phone keypair, and the `TestClient(app)` fixture.

  — done when: `uv run pytest -q tests/test_api_app.py` passes AND `uv run mypy --strict src tests/test_api_app.py` passes.

- [ ] Task 4: `PendingActionResponse` Swift DTO — files: `swift/ArtemisKit/Sources/ArtemisKit/WireModels.swift` (modify, additive — add after the existing `ReviewItem` struct) —

  ```swift
  /// Wire DTO for a pending one-off action (ADR-012). Mirrors PendingActionResponse in api_app.py.
  /// Note: `args` is not included — the brain excludes it from the response surface.
  public struct PendingActionResponse: Codable, Sendable, Equatable, Identifiable {
      public let id: String
      public let module: String
      public let tool: String
      public let summary: String
      public let actionClass: String     // always "takes-action" (GATE-a Literal["takes-action"])
      public let status: String          // "pending" | "approved" | "rejected" | "expired" (GATE-a ActionStatus StrEnum, lowercase)
      public let createdAt: Date
      public let expiresAt: Date
      public let result: [String: AnyCodable]?
      // Confirmed by GATE-a Task 1: `result: dict[str, object] | None`. Values are Python-native
      // types (str/int/float/bool/None/list/dict) — not constrained to str-only.
      // AnyCodable must be present in ArtemisKit (add the lightweight AnyCodable type if absent).

      private enum CodingKeys: String, CodingKey {
          case id, module, tool, summary, result
          case actionClass = "action_class"
          case status
          case createdAt = "created_at"
          case expiresAt = "expires_at"
      }
  }
  ```

  Use a `JSONDecoder` with `.iso8601` date decoding strategy (consistent with existing DTOs). `result` is `[String: AnyCodable]?` — confirmed by GATE-a Task 1: the Python field is `dict[str, object] | None`, populated from `result_obj.model_dump()` after dispatch. If ArtemisKit does not yet have `AnyCodable`, add the standard lightweight implementation (a `struct AnyCodable: Codable` wrapping `Any`) as a new file in the ArtemisKit source tree before Task 4.

  — done when: `swift build --package-path swift/ArtemisKit` passes; a `JSONEncoder`/`JSONDecoder` round-trip of `PendingActionResponse` is identity (covered by Task 6 test extension).

- [ ] Task 5: `ApiClient` action methods — files: `swift/ArtemisKit/Sources/ArtemisKit/ApiClient.swift` (modify, additive — add after the existing `reject(name:token:)` method) —

  ```swift
  /// Returns all PENDING actions awaiting owner approval.
  public func pendingActions(token: String) async throws -> [PendingActionResponse] {
      try await get("/app/actions/pending", token: token)
  }

  /// Executes the action with the given id once and returns the settled action.
  /// Throws ApiError.notFound (404) or ApiError.conflict (409) on error.
  public func approveAction(id: String, token: String) async throws -> PendingActionResponse {
      try await post("/app/actions/approve", body: ["id": id], token: token)
  }

  /// Rejects the action with the given id (never executes).
  /// Throws ApiError.notFound (404) or ApiError.conflict (409) on error.
  public func rejectAction(id: String, token: String) async throws -> PendingActionResponse {
      try await post("/app/actions/reject", body: ["id": id], token: token)
  }
  ```

  Map HTTP 404 → `ApiError.notFound` (add this case if not already present) and 409 → `ApiError.conflict` (add if absent) — alongside the existing `.unauthenticated` (401) and `.vaultLocked` (423) cases. No token or response body is logged.

  — done when: `swift build --package-path swift/ArtemisKit` passes; mock URLProtocol tests (Task 6 extension) verify correct paths/bearer/JSON body.

- [ ] Task 6: Swift DTO round-trip + ApiClient mock tests (extension) — files: `swift/ArtemisKit/Tests/ArtemisKitTests/ArtemisKitTests.swift` (modify, additive — add to the existing test file) —

  Add:
  - `PendingActionResponse` Codable round-trip (snake_case keys verified; `Date` decoding; `result: nil` case).
  - `ApiClient` mock tests for all three methods: assert `GET /app/actions/pending` sends `Authorization: Bearer` and decodes `[PendingActionResponse]`; `POST /app/actions/approve` sends `{"id": "act-1"}` + bearer and decodes a single `PendingActionResponse`; `POST /app/actions/reject` similarly; a 404 response surfaces `ApiError.notFound`; a 409 surfaces `ApiError.conflict`; a 423 surfaces `ApiError.vaultLocked`.

  — done when: `swift test --package-path swift/ArtemisKit` passes.

- [ ] Task 7: Add "Pending actions" section to `ReviewScreen` — files: `swift/ArtemisApp/Sources/Screens/ReviewScreen.swift` (modify, additive) —

  **BrainApi protocol extension** (in `BrainApi.swift` — additive, single line): add `pendingActions(token:)`, `approveAction(id:token:)`, `rejectAction(id:token:)` to the `BrainApi` protocol declaration and the `extension ApiClient: BrainApi` conformance.

  **ReviewModel additions** (add to the existing `@Observable final class ReviewModel`):
  ```swift
  // New state (additive)
  var pendingActions: [PendingActionResponse] = []

  // Extend load() to fetch pending actions alongside recipes
  // In load(): pendingActions = try await api.pendingActions(token: token() ?? "")
  // On .vaultLocked: onLocked() (same pattern as existing recipe load)

  func approveAction(_ id: String) async {
      // optimistic remove from pendingActions; restore on error
      let original = pendingActions
      pendingActions.removeAll { $0.id == id }
      do {
          _ = try await api.approveAction(id: id, token: token() ?? "")
      } catch ApiError.vaultLocked {
          pendingActions = original; onLocked()
      } catch {
          pendingActions = original
          self.error = "Could not approve action. Try again."
      }
  }

  func rejectAction(_ id: String) async {
      let original = pendingActions
      pendingActions.removeAll { $0.id == id }
      do {
          _ = try await api.rejectAction(id: id, token: token() ?? "")
      } catch ApiError.vaultLocked {
          pendingActions = original; onLocked()
      } catch {
          pendingActions = original
          self.error = "Could not reject action. Try again."
      }
  }
  ```

  **PendingActionRow sub-view** (add as a private struct in `ReviewScreen.swift`):
  ```swift
  private struct PendingActionRow: View {
      let action: PendingActionResponse
      let onApprove: () async -> Void
      let onReject: () async -> Void

      var body: some View {
          VStack(alignment: .leading, spacing: 8) {
              Text(action.summary)
                  .font(.body)
              HStack {
                  Text(action.tool)
                      .font(.caption)
                      .foregroundStyle(.secondary)
                  Spacer()
                  // Expiry indicator: text-only, not colour-alone (WCAG 1.4.1)
                  if action.expiresAt.timeIntervalSinceNow < 3600 {
                      Label("Expires soon", systemImage: "clock.badge.exclamationmark")
                          .font(.caption)
                          .foregroundStyle(.orange)
                          .accessibilityLabel("Expires soon")
                  }
              }
              HStack {
                  Button("Approve") { Task { await onApprove() } }
                      .buttonStyle(.borderedProminent)
                      .accessibilityLabel("Approve: \(action.summary)")  // disambiguates rows
                  Button("Reject", role: .destructive) { Task { await onReject() } }
                      .accessibilityLabel("Reject: \(action.summary)")
              }
          }
          .padding(.vertical, 4)
          // Each row is a combined accessibility element (VoiceOver reads summary then actions)
          // NOT .accessibilityElement(children: .combine) — the buttons must remain individually focusable
          // Row's accessibilityValue is the tool + module for context
          .accessibilityValue("\(action.module).\(action.tool)")
          // Minimum 44pt touch target enforced by List row height + .padding
      }
  }
  ```

  **ReviewScreen additions** (add a "Pending actions" section to the existing `List`):
  ```swift
  // Add as a new Section ABOVE the existing Pending Recipes section
  Section("Pending actions") {
      if model.pendingActions.isEmpty {
          ContentUnavailableView(
              "No pending actions",
              systemImage: "checkmark.circle",
              description: Text("Actions waiting for your approval appear here.")
          )
          // systemImage is decorative — ContentUnavailableView handles VoiceOver correctly
      } else {
          ForEach(model.pendingActions) { action in
              PendingActionRow(
                  action: action,
                  onApprove: { await model.approveAction(action.id) },
                  onReject: { await model.rejectAction(action.id) }
              )
          }
      }
  }
  ```

  A11y checklist for the new section (apex-accessibility):
  - **Approve/Reject labels carry the action summary** (not just "Approve" / "Reject") — disambiguates when VoiceOver reads multiple rows (WCAG 1.3.1).
  - **Expiry indicator uses text + icon**, not colour alone — `Label("Expires soon", …)` + `.accessibilityLabel("Expires soon")` (WCAG 1.4.1).
  - **Buttons are individually focusable** — do not wrap in `.accessibilityElement(children: .combine)`; the Approve and Reject buttons must be reachable as distinct VoiceOver elements (WCAG 2.1.1).
  - **Touch targets ≥ 44pt** — enforced by `List` row height + `.borderedProminent` button style (WCAG 2.5.8 / iOS HIG).
  - **`ContentUnavailableView` empty state** — system view, correctly announces to VoiceOver without further annotation.
  - **Dynamic Type** — `Text` uses `.font(.body)` / `.font(.caption)`; no fixed-size containers.
  - **No colour as sole information channel** — expiry indicator uses `Label` text + system image (WCAG 1.4.1).

  — done when: the ArtemisApp target compiles; `ReviewModel` in `ScreenModelsTests` covers `approveAction`/`rejectAction` (Task 8).

- [ ] Task 8: View-model tests for pending-action methods — files: `swift/ArtemisApp/Tests/ArtemisAppTests/ScreenModelsTests.swift` (modify, additive) —

  Add to the existing `ReviewModel` test section:
  - `load()` populates `pendingActions` from a fake `BrainApi`.
  - `approveAction` optimistically removes the row → on success stays removed; on `ApiError.conflict` (already settled) restores and sets `error`.
  - `rejectAction` optimistically removes → on success stays removed; on `ApiError.notFound` restores and sets `error`.
  - A `.vaultLocked` error on `approveAction` or `rejectAction` calls `onLocked` and restores the row.
  - Regression: existing `ReviewModel.load` / `approve` / `reject` (recipe) tests still pass.

  — done when: `xcodebuild test` (gated, Mac) or the off-device Swift test runner passes the new test cases.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `src/artemis/api_app.py` |
| Modify | `src/artemis/main.py` |
| Modify | `swift/ArtemisKit/Sources/ArtemisKit/WireModels.swift` |
| Modify | `swift/ArtemisKit/Sources/ArtemisKit/ApiClient.swift` |
| Modify | `swift/ArtemisApp/Sources/Screens/BrainApi.swift` |
| Modify | `swift/ArtemisApp/Sources/Screens/ReviewScreen.swift` |
| Modify | `tests/test_api_app.py` |
| Modify | `swift/ArtemisKit/Tests/ArtemisKitTests/ArtemisKitTests.swift` |
| Modify | `swift/ArtemisApp/Tests/ArtemisAppTests/ScreenModelsTests.swift` |
| Delete | (none) |
| Create | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_api_app.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_api_app.py` | Python test gate |
| `swift build --package-path swift/ArtemisKit` | ArtemisKit build gate |
| `swift test --package-path swift/ArtemisKit` | ArtemisKit DTO + client test gate |
| `xcodebuild test -project swift/ArtemisApp/Artemis.xcodeproj -scheme Artemis -destination 'platform=iOS Simulator,name=iPhone 16'` (GATED, Mac) | ArtemisApp screen-model test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/api_app.py`, `src/artemis/main.py`, `swift/ArtemisKit/Sources/ArtemisKit/WireModels.swift`, `swift/ArtemisKit/Sources/ArtemisKit/ApiClient.swift`, `swift/ArtemisApp/Sources/Screens/BrainApi.swift`, `swift/ArtemisApp/Sources/Screens/ReviewScreen.swift`, `tests/test_api_app.py`, `swift/ArtemisKit/Tests/ArtemisKitTests/ArtemisKitTests.swift`, `swift/ArtemisApp/Tests/ArtemisAppTests/ScreenModelsTests.swift` |
| `git commit` | `"feat: GATE-b pending-actions review surface (brain endpoints + ArtemisKit DTOs + Review screen tab)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot settings (data_root for PendingActionStore path) |
| `ARTEMIS_DATA_ROOT` | PendingActionStore SQLCipher db location |

### Network
| Action | Purpose |
|--------|---------|
| (none at build/test) | Python tests use TestClient; Swift tests use mock URLProtocol |
| `tailscale serve` (GATED, on-Mini) | Live round-trip against `/app/actions/*` gated on hardware |

## Specialist Context

### Security
The three action endpoints inherit the **ADR-010 §6 two-tier guard** from CLIENT-b without modification: `require_unlocked` depends on `require_session` via FastAPI `Depends`, so a request with no bearer hits 401 before the vault check, and a request with a valid session but locked vault hits 423. This is not re-implemented — it is the same `require_unlocked` dependency defined in CLIENT-b.

`approve` is the highest-privilege action in the entire surface (it executes an external-effect tool — calendar invite, future Gmail send, etc.). The security layers are:
1. Session gate (CLIENT-b `require_session` — reachability).
2. Vault unlocked (CLIENT-b `require_unlocked` — data/execution access; the `ActionStagingService.approve` also asserts vault-unlocked server-side per ADR-012 §3 — defence in depth).
3. Owner-private scope: `PendingActionStore` is owner-private (SQLCipher under the M2 wall); actions cannot be staged by external input (the staging tool is called by the brain's own gated tool, not by the client).
4. Bound-args re-validation: `ActionStagingService.approve` re-validates `args` against the tool's `args_schema` before dispatch (ADR-012 §3) — the client cannot mutate the payload.

`PendingAction.args` is **excluded from the response** — the client receives only the `summary` (human-readable, deterministic, generated at stage time — no LLM at review time). This eliminates any risk of the client rendering or exfiltrating the raw payload.

Errors are generic: 404 `"action not found"`, 409 `"action already settled"` — no internal state exposed (OWASP A10).

No token, action id, or result is logged in the brain routes (consistent with CLIENT-b's no-logging invariant). The `args` field is never present in any serialised form on the wire.

Rate limiting: these routes are `require_unlocked` (authenticated), so they inherit the session layer. No additional rate limit is specified — the vault-unlock TTL and session expiry are the natural throttle. [FLAG apex-security: confirm whether approve/reject need an explicit per-action rate limit beyond session gating — relevant if an adversary with a valid session tries to hammer approve on expired/nonexistent ids.]

### Performance
`list_pending()` is an owner-private SQLCipher read (small table — at most O(dozens) of staged actions outstanding). `approve` awaits the bound tool's async dispatch (ADR-016: `callable_ref` is `async def`; the same call path as a live brain tool call — latency is tool-dependent; calendar writes are ~100-300ms). No streaming; these are short awaited responses.

### Accessibility
The "Pending actions" section targets WCAG 2.2 AA on SwiftUI/VoiceOver (apex-accessibility):
- Approve/Reject buttons carry the action summary in `.accessibilityLabel` (not just "Approve"/"Reject") — WCAG 1.3.1 (no ambiguity across rows).
- Expiry indicator uses `Label(text, systemImage)` not colour alone — WCAG 1.4.1.
- Buttons remain individually focusable (not collapsed into a combined element) — WCAG 2.1.1 (keyboard/switch control).
- 44pt minimum touch targets via `List` row + `.borderedProminent` — WCAG 2.5.8 / iOS HIG.
- Dynamic Type via system font styles — WCAG 1.4.4.
- **Manual VoiceOver pass required (gated, Task 8 integration):** navigate to Pending actions section; each row announces summary + "Approve: [summary]" / "Reject: [summary]"; expiry label reads as text; approve fires correctly; empty-state announces correctly. Record any gaps in handoff.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/api_app.py` | Docstring `PendingActionResponse`, the three routes (auth tier: require_unlocked → session + vault; error codes: 404/409/423) |
| Inline | `swift/ArtemisKit/Sources/ArtemisKit/WireModels.swift` | DocC-comment `PendingActionResponse`; document `args` exclusion rationale |
| Inline | `swift/ArtemisKit/Sources/ArtemisKit/ApiClient.swift` | DocC-comment the three new methods; document 404→`.notFound`, 409→`.conflict` error mapping |
| API | `docs/product/api/client-app-api.md` | Add `/app/actions/*` endpoint reference (routes, auth tier: require_unlocked, request/response shapes, error codes) |

## Acceptance Criteria

- [ ] Run `uv run mypy --strict src tests/test_api_app.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_api_app.py` → verify: no-bearer→401 on all three action routes; session+locked→423; unlocked `GET /app/actions/pending`→200 + list (no `args` key in response); `approve` existing→200 `status=="approved"`; `approve` nonexistent→404; `approve` already-settled→409; `reject` existing→200 `status=="rejected"`; reject nonexistent→404; existing `/app/review/pending` and `/healthz` still pass.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] Run `swift build --package-path swift/ArtemisKit` → verify: exit 0 (Swift 6, no warnings-as-errors bypass).
- [ ] Run `swift test --package-path swift/ArtemisKit` → verify: `PendingActionResponse` round-trip passes; `ApiClient` mock tests assert correct paths/bearer/body; 404→`.notFound` and 409→`.conflict` and 423→`.vaultLocked` surface correctly.
- [ ] Inspect `api_app.py` `PendingActionResponse` and the three action routes → verify: `args` field absent from model; `require_unlocked` is the declared dependency (not `require_session`); `require_unlocked` itself depends on `require_session` via `Depends` (two-tier guard intact — not re-implemented).
- [ ] Inspect `ReviewScreen.swift` → verify: Approve/Reject `.accessibilityLabel` strings include the action summary; expiry uses `Label` (text + icon, not colour alone); buttons are NOT wrapped in `.accessibilityElement(children: .combine)`.
- [ ] (GATED, simulator/device) `ReviewScreen` Pending actions section lists a staged test action → Approve executes and the row disappears; Reject dismisses without executing; locking the vault then opening the section triggers the re-unlock sheet; empty state renders correctly. Manual VoiceOver pass: row navigates to Approve/Reject as distinct focusable elements, each announces the action summary → record in handoff.
- [ ] (GATED, on-Mini) `GET https://<host>.ts.net/app/actions/pending` with a valid session but locked vault → 423; after unlock → 200 with staged actions list → record in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
