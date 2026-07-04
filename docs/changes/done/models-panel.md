---
spec: models-panel
status: draft
token_profile: lean
autonomy_level: L5
coder_effort: medium
---

# Spec: model-role registry — CLIENT settings panel (part 3 of 3)

**Identity:** Desktop client data layer for the owner-editable model-role registry: three Tauri
gateway commands (`app_models_get` / `app_models_put` / `app_models_usage`) with typed serde structs
mirroring every part-2 DTO field, their TS wrappers, and an open/close panel store — mirroring the
KeysPanel gateway/wrapper/store pattern.
→ why: docs/technical/adr/ADR-049-model-role-registry.md (#2 owner-editable from the client)

**Ruling 2026-07-04 (planning — RESOLVED, do not re-open in Part B):** the frozen part-2 contract
stands. PUT 422 `detail` is shown verbatim in the panel — bounded content: it echoes only the
owner's OWN request strings; no file content can reach it. Precision (security review FLAG,
2026-07-04): the `provider`/`model` body fields are regex-pinned at part 2's DTO boundary, but the
`{role}` PATH segment is bounded only as an owner-typed client string (an unknown-role 422 may echo
it unpinned) — Part B renders `detail` as TEXT (never markup) and must not assume tighter bounds.
The enum→human-string map applies ONLY to `dropped_overrides` from GET.

## Split notice (READ FIRST)

The full "part 3" (data layer + the ModelsPanel UI + App wiring) is ~9 client files across two
logical layers — over the 3-file / 2-phase split rule. It is split into two specs; **this spec drafts
PART A only** (the data layer). Part B is flagged for a follow-up draft.

- **PART A (this spec)** — gateway commands + serde structs, TS wrappers, panel open/close store, and
  their hermetic tests. 5 files, one cohesive data layer (gateway + store). No UI.
- **PART B (follow-up, NOT drafted here)** — `client/src/settings/ModelsPanel.tsx` (per-role rows:
  role name + constraint hint badges, a provider dropdown offering ONLY that role's
  `eligible_providers`, a model field, save-per-row calling `modelsPut` with inline 422 `detail`,
  a `dropped_overrides` notice area with a client-side enum→human-string map, and per-role usage
  columns), `ModelsPanel.test.tsx` (component tests mirroring `KeysPanel.test.tsx`), `App.tsx`
  (settings button + mount beside `KeysPanel`), and `CHANGELOG.md`. Part B depends on Part A's
  wrappers/store/types. Draft it after Part A builds green.

## Assumptions
- Part 2 (`docs/changes/model-role-metering.md`) ships the brain endpoints and is the FROZEN
  contract: `GET /app/models` → `{roles: RoleBindingDTO[], providers: string[],
  dropped_overrides: DroppedOverrideDTO[]}`; `PUT /app/models/{role}` body `{provider, model}` →
  `RoleBindingDTO` on 200 or **422 with `{detail: <str>}`** (the `RoleRegistryError` message
  verbatim — NOT a `DropReason` enum); `GET /app/models/usage` → `{roles: RoleUsageDTO[]}`.
  `RoleBindingDTO = {role, provider, model, constraints: {no_tools: bool, temperature: float|null},
  eligible_providers: string[], editable_fields: string[]}`. `DroppedOverrideDTO = {role, reason}`
  where `reason` is one of the five `DropReason` strings. `RoleUsageDTO = {role, calls,
  prompt_tokens, completion_tokens, avg_latency_ms}`. → impact: Stop (structs must match field-for-field).
- The session token stays in Rust (Tauri command pattern), mirroring `client/src-tauri/src/gateway.rs`:
  a thin `#[tauri::command] pub(crate) async fn app_X(state: State<AppState>, ...)` delegates to a
  private helper using `request_json(..., authed=true)` (bearer injected in Rust from `AppState`).
  Register each command in `generate_handler!` in `client/src-tauri/src/lib.rs`. → impact: Stop
- TS wrappers live under `client/src/api/`; a sibling `client/src/api/models.ts` mirrors `oauth.ts`
  (`export const x = (...) => call("app_x", {...})` over the `invoke`-based `call` helper that maps
  thrown errors through `toApiError`). → impact: Stop
- **serde silently drops undeclared JSON fields** (house gotcha, memory `tauri-gateway-serde-silent-drop`):
  EVERY field the panel consumes needs a matching Rust struct field. This spec lists every struct +
  field explicitly (see Task 1). → impact: Stop
- The panel store mirrors `client/src/settings/keysStore.ts` exactly — a `useSyncExternalStore`
  open/close store (`{ open: boolean }`). The panel component (Part B) holds fetched data in
  `useState` and fetches on open, exactly as `KeysPanel` does. keysStore has NO dedicated test; the
  wrapper layer (`oauth.test.ts`) does. This spec mirrors that: wrapper tests yes, store test no. → impact: Caution

Simplicity check: reuse the KeysPanel gateway-command / wrapper / open-close-store pattern verbatim.
The **422 `detail` is surfaced as a normal return value**, not a new error variant — `app_models_put`
returns an untagged enum (`Updated(binding)` | `Invalid{detail}`), mirroring the existing
`OAuthConnectResponse` untagged `Started`/`ClientNotConfigured` precedent already in `gateway.rs`.
This keeps `error.rs` / `errors.ts` (shared) UNTOUCHED — all model logic stays in `models.ts` +
`gateway.rs`.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src-tauri/src/gateway.rs | modify | serde structs (every part-2 DTO field) + 3 private helpers + 3 `#[tauri::command]`s + `#[cfg(test)]` wiremock tests |
| client/src-tauri/src/lib.rs | modify | register `app_models_get` / `app_models_put` / `app_models_usage` in `generate_handler!` |
| client/src/api/models.ts | create | TS wrappers + interfaces (sibling to `oauth.ts`) + `isRoleInvalid` narrow |
| client/src/api/models.test.ts | create | vitest wrapper tests (mirror `oauth.test.ts`) |
| client/src/settings/modelsStore.ts | create | open/close panel store (mirror `keysStore.ts`) |

## Tasks

- [ ] **Task 1: Rust gateway — structs + 3 commands** — files: `client/src-tauri/src/gateway.rs`,
  `client/src-tauri/src/lib.rs` —

  **1a. Add these structs** (place near the OAuth structs; `u64` for the int aggregates, `Option<f64>`
  for the nullable temperature, `String` for the wire `reason`/`detail`). List is exhaustive — every
  part-2 DTO field is present so nothing silently drops:
  ```rust
  #[derive(Debug, Deserialize, Serialize)]
  pub(crate) struct ModelConstraintsDto {
      no_tools: bool,
      // Brain sends `float | None` (extractor/judge = 0.0, others null); Option<f64> round-trips both.
      temperature: Option<f64>,
  }

  #[derive(Debug, Deserialize, Serialize)]
  pub(crate) struct ModelRoleDto {
      role: String,
      provider: String,
      model: String,
      constraints: ModelConstraintsDto,
      eligible_providers: Vec<String>,
      editable_fields: Vec<String>,
  }

  #[derive(Debug, Deserialize, Serialize)]
  pub(crate) struct DroppedOverrideDto {
      role: String,
      reason: String, // one of the five DropReason strings; opaque passthrough to the UI
  }

  #[derive(Debug, Deserialize, Serialize)]
  pub(crate) struct ModelsResponse {
      roles: Vec<ModelRoleDto>,
      providers: Vec<String>,
      dropped_overrides: Vec<DroppedOverrideDto>,
  }

  #[derive(Debug, Serialize)]
  struct RoleUpdateRequest {
      provider: String,
      model: String,
  }

  // PUT outcome: 200 -> Updated(binding); 422 -> Invalid{detail}. Untagged so the TS side checks
  // `"detail" in response` (mirrors OAuthConnectResponse). Constructed in Rust, serialized to webview.
  #[derive(Debug, Deserialize, Serialize)]
  #[serde(untagged)]
  pub(crate) enum RolePutResponse {
      Updated(ModelRoleDto),
      Invalid { detail: String },
  }

  #[derive(Debug, Deserialize, Serialize)]
  pub(crate) struct ModelUsageDto {
      role: String,
      calls: u64,
      prompt_tokens: u64,
      completion_tokens: u64,
      avg_latency_ms: f64,
  }

  #[derive(Debug, Deserialize, Serialize)]
  pub(crate) struct ModelUsageResponse {
      roles: Vec<ModelUsageDto>,
  }
  ```

  **1b. Add three private helpers** (GET/usage reuse `request_json`; PUT is bespoke to branch on 422):
  ```rust
  async fn models_get(state: &AppState) -> Result<ModelsResponse, GatewayError> {
      request_json::<ModelsResponse, ()>(state, Method::GET, "/app/models", None, true).await
  }

  async fn models_usage(state: &AppState) -> Result<ModelUsageResponse, GatewayError> {
      request_json::<ModelUsageResponse, ()>(state, Method::GET, "/app/models/usage", None, true)
          .await
  }

  async fn models_put(
      state: &AppState,
      role: String,
      provider: String,
      model: String,
  ) -> Result<RolePutResponse, GatewayError> {
      let url = format!("{}/app/models/{}", base_url(state)?, path_segment(&role));
      let response = client()
          .put(url)
          .bearer_auth(bearer(state)?)
          .json(&RoleUpdateRequest { provider, model })
          .send()
          .await?;
      let status = response.status();
      if status.is_success() {
          let binding = response.json::<ModelRoleDto>().await?;
          return Ok(RolePutResponse::Updated(binding));
      }
      if status.as_u16() == 422 {
          // Surface the brain's RoleRegistryError message verbatim so the row explains the
          // rejection. Fall back to a fixed string if the body is absent/!json (never raw bytes).
          #[derive(Deserialize)]
          struct Detail {
              detail: String,
          }
          return match response.json::<Detail>().await {
              Ok(body) => Ok(RolePutResponse::Invalid { detail: body.detail }),
              Err(_) => Ok(RolePutResponse::Invalid {
                  detail: "invalid model binding".to_string(),
              }),
          };
      }
      Err(GatewayError::from_status(status)) // 401 -> Unauthenticated, 423 -> VaultLocked, else Http
  }
  ```

  **1c. Add three commands** (beside the other `#[tauri::command]`s):
  ```rust
  #[tauri::command]
  pub(crate) async fn app_models_get(
      state: State<'_, AppState>,
  ) -> Result<ModelsResponse, GatewayError> {
      models_get(&state).await
  }

  #[tauri::command]
  pub(crate) async fn app_models_put(
      state: State<'_, AppState>,
      role: String,
      provider: String,
      model: String,
  ) -> Result<RolePutResponse, GatewayError> {
      models_put(&state, role, provider, model).await
  }

  #[tauri::command]
  pub(crate) async fn app_models_usage(
      state: State<'_, AppState>,
  ) -> Result<ModelUsageResponse, GatewayError> {
      models_usage(&state).await
  }
  ```

  **1d. Register** in `client/src-tauri/src/lib.rs` `generate_handler!` after `gateway::app_layout_put,`:
  ```rust
      gateway::app_models_get,
      gateway::app_models_put,
      gateway::app_models_usage,
  ```

  **1e. Add `#[cfg(test)]` wiremock tests** in `gateway.rs` (mirror `oauth_commands_use_session_bearer_and_expected_routes`):
  - `models_get_lists_roles_providers_and_dropped`: mock `GET /app/models` (bearer header asserted)
    returning a body with two roles — one with `constraints.temperature: null` +
    `eligible_providers: ["claude_code","ollama"]`, one with `temperature: 0.0` — plus
    `providers: ["claude_code","codex","ollama","router"]` and one `dropped_overrides` entry
    `{"role":"reader","reason":"no_tools_ineligible"}`. Assert the decoded struct round-trips both
    temperatures (`None` and `Some(0.0)`), `editable_fields`, and the dropped entry (via
    `serde_json::to_value(&response)` equality).
  - `models_put_updated_and_invalid_arms`: mock `PUT /app/models/loop_driver` with
    `body_json({"provider":"codex","model":"gpt-5.5"})` → 200 returning a full `RoleBindingDTO`;
    assert `matches!(models_put(...).await.unwrap(), RolePutResponse::Updated(_))`. Then a second
    mock `PUT /app/models/reader` → `ResponseTemplate::new(422).set_body_json(json!({"detail":
    "reader must resolve to a no-tools-capable provider"}))`; assert the result is
    `RolePutResponse::Invalid { detail }` with `detail == "reader must resolve to a no-tools-capable provider"`
    (verbatim). Use `path_segment` for the role in the mocked path.
  - `models_usage_returns_per_role_aggregates`: mock `GET /app/models/usage` → one row
    `{"role":"selector","calls":1,"prompt_tokens":2,"completion_tokens":4,"avg_latency_ms":7.0}`;
    assert `response.roles[0].calls == 1` and `avg_latency_ms == 7.0`.

  — done when: `cargo test --manifest-path client/src-tauri/Cargo.toml` is green; the three commands
  appear in `generate_handler!`; the session token is injected in Rust (no token field crosses to the webview).

- [ ] **Task 2: TS wrappers + open/close store** — files: `client/src/api/models.ts` (create),
  `client/src/api/models.test.ts` (create), `client/src/settings/modelsStore.ts` (create) —

  **2a. `client/src/api/models.ts`** — mirror `oauth.ts` (interfaces field-for-field with the Rust
  structs; the `call` helper is copied from `oauth.ts`):
  ```ts
  import { invoke } from "@tauri-apps/api/core";
  import { toApiError } from "./errors";

  export interface ModelConstraints {
    no_tools: boolean;
    temperature: number | null;
  }

  export interface ModelRole {
    role: string;
    provider: string;
    model: string;
    constraints: ModelConstraints;
    eligible_providers: string[];
    editable_fields: string[];
  }

  export interface DroppedOverride {
    role: string;
    reason: string;
  }

  export interface ModelsResponse {
    roles: ModelRole[];
    providers: string[];
    dropped_overrides: DroppedOverride[];
  }

  export interface RoleInvalid {
    detail: string;
  }

  /** PUT result: the new binding, or a 422 rejection carrying the brain's message verbatim. */
  export type RolePutResponse = ModelRole | RoleInvalid;

  export interface ModelUsage {
    role: string;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    avg_latency_ms: number;
  }

  export interface ModelUsageResponse {
    roles: ModelUsage[];
  }

  const call = async <T>(command: string, args?: Record<string, unknown>): Promise<T> => {
    try {
      return await invoke<T>(command, args);
    } catch (error: unknown) {
      throw toApiError(error);
    }
  };

  /** List every model role with its binding, constraints, eligible providers, and dropped overrides. */
  export const modelsGet = (): Promise<ModelsResponse> => call("app_models_get");

  /** Update one role's provider/model binding. Returns the new binding, or {detail} on a 422 rejection. */
  export const modelsPut = (
    role: string,
    provider: string,
    model: string,
  ): Promise<RolePutResponse> => call("app_models_put", { role, provider, model });

  /** Per-role usage aggregates (calls, tokens, average latency). */
  export const modelsUsage = (): Promise<ModelUsageResponse> => call("app_models_usage");

  /** Narrow a PUT result to the 422-rejection arm. */
  export const isRoleInvalid = (response: RolePutResponse): response is RoleInvalid =>
    "detail" in response;
  ```

  **2b. `client/src/api/models.test.ts`** — mirror `oauth.test.ts` (hoisted `invoke` mock):
  - `modelsGet` invokes `"app_models_get"` with `undefined` args and resolves the response object.
  - `modelsPut` invokes `"app_models_put"` with `{ role, provider, model }` and resolves an
    `Updated` binding; `isRoleInvalid(result)` is `false`.
  - `modelsPut` resolves the `Invalid` arm `{ detail: "..." }`; `isRoleInvalid(result)` is `true`
    and `result.detail` is the passed string.
  - `modelsUsage` invokes `"app_models_usage"` with `undefined` args and resolves the aggregates.

  **2c. `client/src/settings/modelsStore.ts`** — copy `keysStore.ts` structure, drop `pendingKey`
  (snapshot is `{ open: boolean }`); exports `openModels()`, `closeModels()`, `modelsStore`
  (`getSnapshot` / `subscribe` / `resetForTest`), and `useModelsStore(selector)` over
  `useSyncExternalStore`. No dedicated test (mirrors `keysStore.ts`, which has none).

  — done when: `npm --prefix client run typecheck`, `npm --prefix client run lint`, and
  `npm --prefix client run test` are clean; the wrapper tests pass; no token or secret is referenced
  in `models.ts`.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]
<!-- Task 2's TS types mirror Task 1's structs; sequence gateway → wrappers. One cohesive data layer,
5 files, no parallelism to gain from a split. -->

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src/api/models.ts, client/src/api/models.test.ts, client/src/settings/modelsStore.ts |
| Modify | client/src-tauri/src/gateway.rs, client/src-tauri/src/lib.rs |

### Commands
| Command | Purpose |
|---------|---------|
| `cargo test --manifest-path client/src-tauri/Cargo.toml` | Rust command + serde round-trip tests |
| `npm --prefix client run typecheck` | TS type gate (`tsc --noEmit`) |
| `npm --prefix client run lint` | eslint (`--max-warnings 0`) |
| `npm --prefix client run test` | vitest wrapper tests |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the five files above |
| `git commit` | "feat(client): model-role registry gateway + wrappers + store (part 3a)" |

## Specialist Context
### Security
The session token stays in Rust (injected via `bearer(state)` in the private helpers), never the
webview — matches the established gateway pattern. The panel surfaces only role/provider/model names,
constraint flags, the brain's own 422 `detail` string, `DropReason` enum values, and numeric usage —
no tokens or secrets. `error.rs` / `errors.ts` are untouched (the 422 detail rides a normal return
value, not a new error surface). Light review: confirm no token/secret field crosses into the webview
and the 422 fallback never emits raw response bytes (fixed string on non-json body).

### Accessibility
(none in Part A — data layer only. Part B's ModelsPanel follows the `KeysPanel` a11y: labels, focus,
keyboard, per the sibling panel.)

## Acceptance Criteria
- [ ] Run `cargo test --manifest-path client/src-tauri/Cargo.toml` → verify: exit 0; the three new
  wiremock tests pass (GET round-trips `temperature: null` AND `0.0` + `eligible_providers` +
  `editable_fields` + a dropped-override; PUT returns `Updated` on 200 and `Invalid{detail}` verbatim
  on 422; usage returns per-role aggregates).
- [ ] Run `npm --prefix client run typecheck` → verify: exit 0 (TS interfaces match the Rust structs;
  `RolePutResponse` union narrows via `isRoleInvalid`).
- [ ] Run `npm --prefix client run lint` → verify: exit 0.
- [ ] Run `npm --prefix client run test` → verify: exit 0; the `models.test.ts` wrapper cases pass
  (`modelsGet`/`modelsUsage` no-arg invoke, `modelsPut` `{role,provider,model}` invoke, both PUT arms,
  `isRoleInvalid` narrowing).
- [ ] The three commands are registered in `client/src-tauri/src/lib.rs` `generate_handler!`.

## Open items flagged (planning)
1. **RESOLVED by planning ruling 2026-07-04 (see header)** — PUT 422 is `{detail: string}` shown
   verbatim (bounded, owner-input-only content); the `DropReason` enum→human-string map applies ONLY
   to `dropped_overrides` from GET. No redesign; Part B must not re-open this.
2. **Part B (ModelsPanel UI + App wiring + CHANGELOG) is not drafted** — see the Split notice. It
   needs: the enum→human-string map for the five `DropReason` values, the provider dropdown offering
   ONLY `eligible_providers[role]` (the top-level `providers` list is plumbed but must NOT widen the
   dropdown), constraint-hint badges (e.g. "no-tools" when `constraints.no_tools`), save-per-row with
   inline `detail` on the `Invalid` arm, the `dropped_overrides` notice, per-role usage columns, and
   a settings button + mount beside `KeysPanel` in `App.tsx`. Baseline CSS only (owner refines visuals).
3. **Part 2 must be built before this spec** — it edits nothing part-2 owns, but its acceptance
   depends on the endpoints existing to smoke live. Hermetic Part-A tests (wiremock + mocked `invoke`)
   pass standalone; a live smoke needs part 2 shipped.
</content>
</invoke>
