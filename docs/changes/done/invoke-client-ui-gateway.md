---
spec: invoke-client-ui-gateway
status: done
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: medium
---

# Spec: Invoke confirm — Rust command + TS gateway/DTO plumbing (CLIENT side, layer 1/2)

**Identity:** Adds the `app_invoke_confirm` Tauri command (POSTs the shipped
`/app/ask/invoke/{invoke_id}/confirm` brain endpoint with the session token, mirroring
`app_capability_promote`), its TS wrapper `invokeConfirm`, and the DTO field additions needed to
carry `path: "invoke_confirm" | "invoke_clarify"` and the invoke payload on `AskResponse`.
First of two client specs for the capability invoke/reuse path (#5b of 5); layer 2
(`askStore`/`AskPopup` UI) is `invoke-client-ui-ui`, which depends on this spec.
→ why: see docs/technical/adr/ADR-039-capability-invoke-reuse.md decisions 5, 6.

## Assumptions
- The brain's shipped contract (`src/artemis/api/ask_routes.py`, spec `invoke-wiring-quarantine-brain`,
  done) adds six new optional fields to `AskResponse` (`invoke_id`, `capability`, `egress_domains`,
  `secrets`, `args`, `missing`) and a new `POST /app/ask/invoke/{invoke_id}/confirm` route returning
  `InvokeConfirmResponse{invoke_id, status: "ok"|"missing_secrets"|"not_found"|"error", text, missing_secrets}`
  with no request body (the id is in the URL path) → impact: Stop (confirmed by direct read of
  `src/artemis/api/ask_routes.py` lines 39-56, 240-271 — not inferred).
- This client's existing DTO convention keeps wire field names **snake_case verbatim** in TS
  interfaces (no camelCase mapping) — confirmed by `AskResponse.tool_used`, `BuildPlanCard.build_id`/
  `egress_domains`/`missing_secrets`/`block_reason` in `client/src/api/dto.ts`. The new fields follow
  the identical convention → impact: Stop (getting this wrong breaks JSON round-tripping silently,
  since TS has no runtime schema check on the `invoke<T>` response).
- Tauri IPC camelCases Rust snake_case command **parameter names** into the JS `invoke()` args object
  (confirmed by `capabilityPromote = (buildId) => call("app_capability_promote", { buildId })` against
  Rust's `build_id: String` param) — this is a different layer from the DTO body convention above and
  applies only to the `invokeId` argument of the new command, not to any JSON body → impact: Low.
- `serde`'s default (no `#[serde(skip_serializing_if = ...)]` anywhere in `gateway.rs` today) serializes
  `Option::None` as explicit JSON `null`, confirmed by the existing `PlanCard.block_reason` test
  expectation (`"block_reason": null`) → impact: Stop (adding six new `Option` fields to Rust
  `AskResponse` changes what `connect_and_ask_use_brain_app_contract`'s
  `serde_json::to_value(&response)` produces; that test's exact-equality assertion must be updated in
  the same task, mirroring how the brain-side spec updated `test_plain_ask_keeps_completion_path`).

Simplicity check: considered adding the confirm call as a generic `request_json` one-liner directly
inline at the Tauri command (skipping the `gateway::invoke_confirm` helper layer) — rejected because
every other authed POST-with-path-param in this file (`secret_delete`, `review_approve`,
`actions_approve`) goes through the same `helper fn` → `#[tauri::command]` two-layer split (helper is
unit-testable against `wiremock` without the Tauri command harness); matching that existing shape.

## Prerequisites
- Specs that must be complete first: none (brain contract already shipped — commit `b59e512`).
- Environment setup required: none.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src-tauri/src/gateway.rs | modify | `AskResponse` gains 6 optional fields; new `InvokeConfirmResponse` struct; new `invoke_confirm` helper fn; new `app_invoke_confirm` Tauri command; new/updated tests |
| client/src-tauri/src/lib.rs | modify | register `gateway::app_invoke_confirm` in `invoke_handler!` |
| client/src/api/dto.ts | modify | `AskResponse` gains 6 optional fields; new `InvokeConfirmResponse` interface |
| client/src/api/gateway.ts | modify | new `invokeConfirm(invokeId: string): Promise<InvokeConfirmResponse>` export |
| client/src/api/gateway.test.ts | modify | test for `invokeConfirm` args mapping |

## Tasks
- [ ] Task 1: Rust command + DTO — files: client/src-tauri/src/gateway.rs, client/src-tauri/src/lib.rs
  — done when: (a) `AskResponse` struct (lines ~115-121) gains `invoke_id: Option<String>`,
  `capability: Option<String>`, `egress_domains: Option<Vec<String>>`, `secrets: Option<Vec<String>>`,
  `args: Option<serde_json::Value>`, `missing: Option<Vec<String>>` (all `#[derive(Debug, Deserialize,
  Serialize)]`, no rename attrs — matches existing snake_case-verbatim fields on the same struct);
  (b) new `#[derive(Debug, Deserialize, Serialize)] pub(crate) struct InvokeConfirmResponse { invoke_id:
  String, status: String, text: Option<String>, missing_secrets: Vec<String> }` placed near
  `PlanCard`/`InstalledCard`; (c) new fn `pub(crate) async fn invoke_confirm(state: &AppState,
  invoke_id: String) -> Result<InvokeConfirmResponse, GatewayError> { request_json::<InvokeConfirmResponse,
  ()>(state, Method::POST, &format!("/app/ask/invoke/{invoke_id}/confirm"), None, true).await }` placed
  near `capability_promote`; (d) new `#[tauri::command] pub(crate) async fn app_invoke_confirm(state:
  State<'_, AppState>, invoke_id: String) -> Result<InvokeConfirmResponse, GatewayError> {
  invoke_confirm(&state, invoke_id).await }` placed near `app_capability_promote`; (e)
  `gateway::app_invoke_confirm` added to the `tauri::generate_handler![...]` list in `lib.rs` (after
  `gateway::app_capability_promote`); (f) new `#[tokio::test]` `invoke_confirm_posts_to_confirm_route_with_bearer`
  mirroring `capability_propose_posts_goal_with_bearer`'s shape: mocks `POST /app/ask/invoke/inv-1/confirm`
  with bearer header, asserts NO request body is sent (use `wiremock`'s `body_json` absence — i.e. do
  not add a `.and(body_json(...))` matcher), responds with
  `{"invoke_id":"inv-1","status":"ok","text":"done","missing_secrets":[]}`, asserts the decoded
  `InvokeConfirmResponse` matches; (g) the existing `connect_and_ask_use_brain_app_contract` test's
  final `assert_eq!(encoded, json!({...}))` block is updated to include the six new fields as explicit
  `null` (matching serde's default `Option::None` → `null` serialization, per the Assumptions note);
  (h) `cargo build` and `cargo clippy` (from `client/`) are clean; `cargo test` (from `client/`) passes.
- [ ] Task 2: TS DTO + gateway wrapper — files: client/src/api/dto.ts, client/src/api/gateway.ts —
  done when: (a) `AskResponse` interface (dto.ts) gains `invoke_id?: string`, `capability?: string`,
  `egress_domains?: string[]`, `secrets?: string[]`, `args?: Record<string, unknown>`, `missing?:
  string[]` (optional, snake_case, matching the existing `tool_used?` convention on the same
  interface); (b) new `export interface InvokeConfirmResponse { invoke_id: string; status: "ok" |
  "missing_secrets" | "not_found" | "error"; text: string | null; missing_secrets: string[]; }` added
  near `BuildPlanCard`; (c) `gateway.ts` imports `InvokeConfirmResponse` from `./dto` alongside the
  existing DTO imports; (d) new export `export const invokeConfirm = (invokeId: string):
  Promise<InvokeConfirmResponse> => call("app_invoke_confirm", { invokeId });` placed near
  `capabilityPromote`; (e) `npm run typecheck` (from `client/`) is clean.
- [ ] Task 3: gateway test — files: client/src/api/gateway.test.ts — done when: new test
  `"invokes app_invoke_confirm with the invoke id"` mirrors the existing
  `"invokes app_capability_promote with the build id"` test: mocks `mocks.invoke` to resolve
  `{ invoke_id: "inv-1", status: "ok", text: "done", missing_secrets: [] }`, asserts
  `gateway.invokeConfirm("inv-1")` resolves to that object and `mocks.invoke` was called with
  `("app_invoke_confirm", { invokeId: "inv-1" })`; `npm run test -- gateway.test.ts` (host-run, not
  inside the Codex sandbox — see note below) passes.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3]
<!-- Task 1 (Rust) and Task 2 (TS DTO/gateway) are file-disjoint. Task 3 depends on Task 2's new export. -->

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | client/src-tauri/src/gateway.rs, client/src-tauri/src/lib.rs, client/src/api/dto.ts, client/src/api/gateway.ts, client/src/api/gateway.test.ts |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `cargo build` (from client/src-tauri, or `cargo build --manifest-path client/src-tauri/Cargo.toml`) | Rust build check |
| `cargo clippy` (same manifest) | Rust lint |
| `cargo test` (same manifest) | Rust unit tests |
| `npm run typecheck` (from client/) | tsc |
| `npm run lint` (from client/) | eslint --max-warnings 0 |
| `npm run test -- gateway.test.ts` (from client/) | vitest — **HOST-RUN ONLY**: vitest cannot run inside the Codex sandbox (esbuild blocks the `../..` path escape); the coder runs typecheck/lint/cargo build/clippy/test in-sandbox, then the HOST runs `npm run test` as the final verification step |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/src-tauri/src/gateway.rs client/src-tauri/src/lib.rs client/src/api/dto.ts client/src/api/gateway.ts client/src/api/gateway.test.ts |
| `git commit` | "feat: invoke-confirm Rust command + TS gateway/DTO plumbing (invoke-client-ui-gateway)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | no new env vars |

### Network
| Action | Purpose |
|--------|---------|
| (none) | test-only `wiremock`/mocked `invoke()` — no real network calls |

## Specialist Context
### Security
- `invoke_confirm`'s request carries the bearer session token exactly like `capability_promote`
  (`request_json(..., authed: true)`) — no new auth surface, no secret VALUES cross this layer (the
  brain never returns resolved secret values in `InvokeConfirmResponse`, only names in the earlier
  `AskResponse.secrets` field, per the shipped brain contract).

### Performance
(none — single POST, no new polling)

### Accessibility
(none — no UI in this spec; UI is `invoke-client-ui-ui`)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Add entry under Unreleased: invoke-confirm Rust command + TS gateway plumbing (client-side, layer 1 of 2 for capability invoke/reuse) |

## Acceptance Criteria
- [ ] `AskResponse` (Rust + TS) carries the six new invoke fields → verify: `cargo test
  connect_and_ask_use_brain_app_contract` passes with the updated exact-JSON assertion including the
  six `null` fields; `npm run typecheck` passes with the new optional `AskResponse` fields in
  `dto.ts`.
- [ ] `app_invoke_confirm` posts to the confirm route with no body and a bearer token → verify:
  `cargo test invoke_confirm_posts_to_confirm_route_with_bearer` passes.
- [ ] `app_invoke_confirm` is registered and callable via Tauri IPC → verify: `lib.rs`'s
  `generate_handler!` list contains `gateway::app_invoke_confirm`; `cargo build` succeeds.
- [ ] TS `invokeConfirm` wrapper maps to the Tauri command with camelCased args → verify:
  `npm run test -- gateway.test.ts` passes the new test asserting `invoke("app_invoke_confirm",
  { invokeId: "inv-1" })`.
- [ ] Whole-client verification recipe is green → verify: `npm run typecheck`, `npm run lint`,
  `cargo build`, `cargo clippy` all clean (coder, in-sandbox); `npm run test` clean (host, after
  handoff — vitest cannot run inside the Codex sandbox per the esbuild `../..` block).

## Progress
_(Coding mode writes here — do not edit manually)_
