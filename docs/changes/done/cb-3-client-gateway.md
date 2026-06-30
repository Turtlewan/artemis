---
slice: capability-build
status: ready
coder_effort: medium
depends_on: cb-2-build-endpoints
surface: client (Rust + TS)
---

# CB-3 — Client gateway for the build flow (Rust commands + TS wrappers)

**Identity:** Third spec of the capability-build slice. Wires CB-2's `/app/capabilities/*` endpoints into the Tauri client's Rust gateway (so the session token never enters the webview, ADR-030) + the TS gateway wrappers the React layer will call in CB-4. Adds three commands — `app_capability_propose`, `app_capability_build` (streaming), `app_capability_promote` — and a **named-event SSE parser** (CB-2's build stream uses `event: status` / `event: result`, which the existing bare-`data:` parser ignores). No UI (CB-4), no map (CB-5). Depends on CB-2 (the live endpoints + their wire shapes).

**Scope note (file count):** this is one cohesive cross-language wire — a gateway command is non-functional without its Rust impl, its `lib.rs` registration, the TS wrapper, and the shared DTO types. The 5 files below are a single logical surface (one phase), not separable into shippable halves.

**Wire facts (from CB-2, verified by the live smoke):**
- Build SSE frames: `event: status` + `data: <text>` · `event: result` + `data: <json {build_id,passed,blocked,output}>` · terminated by `data: [DONE]`. Field names are **snake_case** end-to-end (matches the existing ask/stream DTOs, e.g. `tool_used`), so keep snake_case through Rust→webview — no camelCase rename.
- The status text contains a literal `…` (U+2026); it passes through the UTF-8 `response.text()` → `Channel` path unchanged (the smoke's `�` was console-only). No transformation needed.

## Files to change

1. `src-tauri/src/gateway.rs` — **modify**: DTOs, `BuildStreamEvent` enum, `parse_build_frame`, the 3 gateway fns + 3 `#[tauri::command]` wrappers, unit tests.
2. `src-tauri/src/lib.rs` — **modify**: register the 3 new commands in the invoke handler.
3. `src/api/dto.ts` — **modify**: `BuildPlanCard`, `InstalledCard`, `BuildStreamEvent` types.
4. `src/api/gateway.ts` — **modify**: `capabilityPropose` / `capabilityBuild` / `capabilityPromote` wrappers; generalise `streamCommand` over the event type.
5. `src/api/gateway.test.ts` — **modify**: tests for the three wrappers.

## Exact changes

### 1. `src-tauri/src/gateway.rs`

**a. DTOs** (near the other request/response structs; keep snake_case, derive as the neighbours do):
```rust
#[derive(Debug, Serialize)]
struct CapabilityProposeRequest {
    goal: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct PlanCard {
    build_id: String,
    name: String,
    description: String,
    summary: String,
    secrets: Vec<String>,
    blocked: bool,
    block_reason: Option<String>,
}

#[derive(Debug, Serialize)]
struct CapabilityPromoteRequest {
    build_id: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct InstalledCard {
    name: String,
    version: i64,
    path: String,
}
```

**b. The build stream event + result frame** (near `StreamEvent`):
```rust
#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "type")]
pub(crate) enum BuildStreamEvent {
    #[serde(rename = "build_status")]
    Status { text: String },
    #[serde(rename = "build_result")]
    Result {
        build_id: String,
        passed: bool,
        blocked: bool,
        output: String,
    },
    #[serde(rename = "done")]
    Done,
    #[serde(rename = "error")]
    Error { message: String },
}

#[derive(Debug, Deserialize)]
struct BuildResultFrame {
    build_id: String,
    passed: bool,
    blocked: bool,
    output: String,
}
```

**c. The named-event parser** (pure fn, mirrors `parse_stream_frame`'s testability):
```rust
/// Map one SSE `data:` payload, tagged by the preceding `event:` line, to a typed build event.
pub(crate) fn parse_build_frame(
    event: Option<&str>,
    data: &str,
) -> Result<Option<BuildStreamEvent>, GatewayError> {
    let data = data.trim();
    if data.is_empty() {
        return Ok(None);
    }
    if data == "[DONE]" {
        return Ok(Some(BuildStreamEvent::Done));
    }
    match event {
        Some("status") => Ok(Some(BuildStreamEvent::Status {
            text: data.to_string(),
        })),
        Some("result") => {
            let frame: BuildResultFrame =
                serde_json::from_str(data).map_err(|_| GatewayError::Network)?;
            Ok(Some(BuildStreamEvent::Result {
                build_id: frame.build_id,
                passed: frame.passed,
                blocked: frame.blocked,
                output: frame.output,
            }))
        }
        Some("error") => Ok(Some(BuildStreamEvent::Error {
            message: data.to_string(),
        })),
        _ => Ok(None),
    }
}
```

**d. The three gateway fns:**
```rust
pub(crate) async fn capability_propose(
    state: &AppState,
    goal: String,
) -> Result<PlanCard, GatewayError> {
    request_json(
        state,
        Method::POST,
        "/app/capabilities/propose",
        Some(&CapabilityProposeRequest { goal }),
        true,
    )
    .await
}

pub(crate) async fn capability_promote(
    state: &AppState,
    build_id: String,
) -> Result<InstalledCard, GatewayError> {
    request_json(
        state,
        Method::POST,
        "/app/capabilities/promote",
        Some(&CapabilityPromoteRequest { build_id }),
        true,
    )
    .await
}

pub(crate) async fn capability_build(
    state: &AppState,
    build_id: String,
    channel: Channel<BuildStreamEvent>,
) -> Result<(), GatewayError> {
    let url = format!(
        "{}/app/capabilities/{}/build",
        base_url(state)?,
        build_id
    );
    let response = client().post(url).bearer_auth(bearer(state)?).send().await?;
    if !response.status().is_success() {
        return Err(GatewayError::from_status(response.status()));
    }
    let body = response.text().await?;
    let mut current_event: Option<&str> = None;
    for line in body.lines() {
        let line = line.trim_end();
        if line.is_empty() {
            current_event = None;
            continue;
        }
        if let Some(ev) = line.strip_prefix("event:") {
            current_event = Some(ev.trim());
        } else if let Some(data) = line.strip_prefix("data:") {
            if let Some(event) = parse_build_frame(current_event, data)? {
                channel.send(event).map_err(|_| GatewayError::Network)?;
            }
        }
    }
    Ok(())
}
```

**e. The `#[tauri::command]` wrappers** (alongside the other `app_*` commands):
```rust
#[tauri::command]
pub(crate) async fn app_capability_propose(
    state: State<'_, AppState>,
    goal: String,
) -> Result<PlanCard, GatewayError> {
    capability_propose(&state, goal).await
}

#[tauri::command]
pub(crate) async fn app_capability_build(
    state: State<'_, AppState>,
    build_id: String,
    channel: Channel<BuildStreamEvent>,
) -> Result<(), GatewayError> {
    capability_build(&state, build_id, channel).await
}

#[tauri::command]
pub(crate) async fn app_capability_promote(
    state: State<'_, AppState>,
    build_id: String,
) -> Result<InstalledCard, GatewayError> {
    capability_promote(&state, build_id).await
}
```

**f. Tests** (extend the existing `#[cfg(test)] mod tests`):
```rust
#[test]
fn build_frame_parser_is_typed() {
    assert!(matches!(
        parse_build_frame(Some("status"), "Testing in sandbox…").unwrap(),
        Some(BuildStreamEvent::Status { .. })
    ));
    assert!(matches!(
        parse_build_frame(
            Some("result"),
            r#"{"build_id":"b","passed":true,"blocked":false,"output":"ok"}"#
        )
        .unwrap(),
        Some(BuildStreamEvent::Result { passed: true, .. })
    ));
    assert!(matches!(
        parse_build_frame(None, "[DONE]").unwrap(),
        Some(BuildStreamEvent::Done)
    ));
    assert!(parse_build_frame(Some("status"), "").unwrap().is_none());
}
```
Optionally add a `wiremock` test for `capability_propose` mirroring the existing server-backed tests (assert it POSTs to `/app/capabilities/propose` with the bearer token and deserialises a `PlanCard`).

### 2. `src-tauri/src/lib.rs`

Add the three commands to the `tauri::generate_handler![...]` list alongside the existing `app_*` entries: `app_capability_propose`, `app_capability_build`, `app_capability_promote`. (Match the module path the existing `app_ask_stream` etc. use.)

### 3. `src/api/dto.ts`

```ts
export interface BuildPlanCard {
  build_id: string;
  name: string;
  description: string;
  summary: string;
  secrets: string[];
  blocked: boolean;
  block_reason: string | null;
}

export interface InstalledCard {
  name: string;
  version: number;
  path: string;
}

export type BuildStreamEvent =
  | { type: "build_status"; text: string }
  | { type: "build_result"; build_id: string; passed: boolean; blocked: boolean; output: string }
  | { type: "done" }
  | { type: "error"; message: string };
```

### 4. `src/api/gateway.ts`

Generalise `streamCommand` so it works for both `StreamEvent` and `BuildStreamEvent` (the only coupling today is the hardcoded finish check). Change its signature to accept an `isFinal` predicate and make it generic; update the existing `askStream`/`askVoice` callers to pass their current predicate (`(e) => e.type === "done" || e.type === "vault_locked"`):
```ts
async function* streamCommand<E extends { type: string }>(
  command: string,
  args: (channel: Channel<E>) => Record<string, unknown>,
  isFinal: (event: E) => boolean,
): AsyncGenerator<E> {
  // ...existing body, but `channel`/`queue` typed as E and the onmessage finish check uses isFinal(event)...
}
```
Then add the build wrappers:
```ts
export const capabilityPropose = (goal: string): Promise<BuildPlanCard> =>
  call("app_capability_propose", { goal });

export const capabilityPromote = (buildId: string): Promise<InstalledCard> =>
  call("app_capability_promote", { buildId });

export async function* capabilityBuild(buildId: string): AsyncGenerator<BuildStreamEvent> {
  yield* streamCommand<BuildStreamEvent>(
    "app_capability_build",
    (channel) => ({ buildId, channel }),
    (event) => event.type === "done" || event.type === "error",
  );
}
```
Import `BuildPlanCard`, `InstalledCard`, `BuildStreamEvent` from `./dto`. (Tauri maps the camelCase `buildId` arg to the Rust `build_id`, exactly like the existing `suggestionId`→`suggestion_id`.)

### 5. `src/api/gateway.test.ts`

Mirror the existing tests: mock `@tauri-apps/api/core` `invoke` + `Channel`. Add:
- `capabilityPropose("…")` invokes `app_capability_propose` with `{ goal }` and returns the `BuildPlanCard`.
- `capabilityPromote("b")` invokes `app_capability_promote` with `{ buildId: "b" }`.
- `capabilityBuild("b")` yields the build events the mocked channel emits, ending after `done`.

## Acceptance criteria

1. `parse_build_frame` maps `status`/`result`/`[DONE]`/empty correctly → `build_frame_parser_is_typed` (cargo test).
2. The three Rust commands compile, are registered in `lib.rs`, and `cargo test` passes → `cargo test` (in `src-tauri`).
3. `capabilityPropose`/`capabilityPromote`/`capabilityBuild` call the right commands and yield typed events → gateway.test.ts.
4. Client typechecks + lints clean → `npm run typecheck` + `npm run lint`.
5. Whole client green: `npm run test` and `cargo test` pass; `cargo clippy` clean.

## Commands to run

```bash
# from client/
npm run typecheck
npm run lint
npm run test
cargo test --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings
```
