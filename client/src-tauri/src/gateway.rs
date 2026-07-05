use reqwest::Method;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use tauri::ipc::Channel;
use tauri::State;

use crate::error::GatewayError;
use crate::state::AppState;

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct PairRequest {
    pub(crate) device_id: String,
    pub(crate) public_key_b64: String,
    pub(crate) pairing_code: String,
    pub(crate) code_signature_b64: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct SessionBeginRequest {
    pub(crate) device_id: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct SessionBeginResponse {
    pub(crate) nonce_b64: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct SessionCompleteRequest {
    pub(crate) device_id: String,
    pub(crate) nonce_b64: String,
    pub(crate) counter: u64,
    pub(crate) signature_b64: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct SessionCompleteResponse {
    session_token: String,
    // Brain serializes this as a float Unix timestamp (api_app SessionCompleteResponse.expires_at: float);
    // u64 would fail serde deserialization on any fractional value. Deserialize-only — never used in arithmetic.
    expires_at: f64,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct UnlockBeginRequest {}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct UnlockBeginResponse {
    pub(crate) nonce_b64: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct UnlockCompleteRequest {
    pub(crate) nonce_b64: String,
    pub(crate) counter: u64,
    pub(crate) signature_b64: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct StatusResponse {
    connected: bool,
    vault_unlocked: bool,
    device_id: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct AskRequest {
    text: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct VoiceAskRequest {
    speak: bool,
}

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
    // Without these fields serde silently DROPS them between the brain and the webview,
    // leaving the plan-gate render undefined (informed-consent gap; missing_secrets also
    // feeds the pending-credential deep-link).
    #[serde(default)]
    egress_domains: Vec<String>,
    #[serde(default)]
    oauth_scopes: Vec<String>,
    #[serde(default)]
    missing_secrets: Vec<String>,
    blocked: bool,
    block_reason: Option<String>,
}

#[derive(Debug, Serialize)]
struct CapabilityPromoteRequest {
    build_id: String,
}

#[derive(Debug, Serialize)]
struct SecretSetRequest {
    name: String,
    value: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct SecretNamesResponse {
    names: Vec<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct BlessEntry {
    name: String,
    current_version: Option<i64>,
    blessed_version: Option<i64>,
    blessed: bool,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct BlessListResponse {
    capabilities: Vec<BlessEntry>,
}

#[derive(Debug, Serialize)]
struct OAuthConnectRequest {
    scopes: Vec<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(untagged)]
pub(crate) enum OAuthConnectResponse {
    Started { consent_url: String },
    ClientNotConfigured { status: String },
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct OAuthStatusResponse {
    account: String,
    connected: bool,
    granted_scopes: Vec<String>,
    #[serde(default)]
    connect_pending: bool,
    #[serde(default)]
    last_connect_error: Option<String>,
}

#[derive(Debug, Serialize)]
struct OAuthDisconnectRequest {
    #[serde(skip_serializing_if = "Option::is_none")]
    account: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct OAuthDisconnectResponse {
    disconnected: bool,
}

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
    reason: String,
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

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct InstalledCard {
    name: String,
    version: i64,
    path: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct InvokeConfirmResponse {
    invoke_id: String,
    status: String,
    text: Option<String>,
    missing_secrets: Vec<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct AskResponse {
    text: String,
    path: String,
    tool_used: Option<String>,
    escalated: bool,
    invoke_id: Option<String>,
    capability: Option<String>,
    egress_domains: Option<Vec<String>>,
    secrets: Option<Vec<String>>,
    args: Option<serde_json::Value>,
    missing: Option<Vec<String>>,
    // AL-4c: agent-loop verdict/answered_from signals (AL-4a contract). Option<String> so a
    // non-loop response (fields absent) deserializes to None and serializes back as null.
    // Without these fields serde SILENTLY DROPS them before the webview (tauri-gateway-serde-silent-drop).
    verdict: Option<String>,
    verdict_reason: Option<String>,
    answered_from: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct ReviewItem {
    name: String,
    description: String,
    status: String,
    action_class: String,
    safety: String,
    explanation: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct PendingAction {
    id: String,
    module: String,
    tool: String,
    summary: String,
    action_class: String,
    status: String,
    created_at: String,
    expires_at: String,
    result: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct TaskSuggestionAcceptRequest {
    suggestion_id: String,
    due_at: Option<String>,
    project_id: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct TaskSuggestionAcceptResponse {
    task: serde_json::Value,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct TaskSuggestionRejectRequest {
    suggestion_id: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct CardPlacement {
    id: String,
    domain: String,
    cluster: String,
    x: f64,
    y: f64,
    w: f64,
    h: f64,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct LayoutDto {
    version: u64,
    updated_at: String,
    cards: Vec<CardPlacement>,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct OkResponse {
    pub(crate) ok: bool,
}

#[derive(Debug, Deserialize)]
struct PairResponse {
    paired: bool,
}

#[derive(Debug, Deserialize)]
struct LockResponse {
    locked: bool,
}

#[derive(Debug, Deserialize)]
struct UnlockResponse {
    unlocked: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "type")]
pub(crate) enum StreamEvent {
    #[serde(rename = "text")]
    Text { text: String },
    #[serde(rename = "vault_locked")]
    VaultLocked,
    #[serde(rename = "done")]
    Done {
        path: Option<String>,
        tool_used: Option<String>,
        escalated: bool,
    },
}

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

#[derive(Debug, Deserialize)]
struct ErrorFrame {
    error: String,
}

fn client() -> reqwest::Client {
    reqwest::Client::new()
}

fn base_url(state: &AppState) -> Result<String, GatewayError> {
    state.base_url().ok_or(GatewayError::Network)
}

fn bearer(state: &AppState) -> Result<String, GatewayError> {
    state.token().ok_or(GatewayError::Unauthenticated)
}

fn path_segment(raw: &str) -> String {
    let mut encoded = String::new();
    for byte in raw.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => {
                encoded.push(char::from(byte));
            }
            _ => encoded.push_str(&format!("%{byte:02X}")),
        }
    }
    encoded
}

async fn request_json<T, B>(
    state: &AppState,
    method: Method,
    path: &str,
    body: Option<&B>,
    authed: bool,
) -> Result<T, GatewayError>
where
    T: DeserializeOwned,
    B: Serialize + ?Sized,
{
    let url = format!("{}{}", base_url(state)?, path);
    let mut request = client().request(method, url);
    if authed {
        request = request.bearer_auth(bearer(state)?);
    }
    if let Some(payload) = body {
        request = request.json(payload);
    }

    let response = request.send().await?;
    if !response.status().is_success() {
        return Err(GatewayError::from_status(response.status()));
    }
    Ok(response.json::<T>().await?)
}

async fn request_empty<B>(
    state: &AppState,
    method: Method,
    path: &str,
    body: Option<&B>,
    authed: bool,
) -> Result<(), GatewayError>
where
    B: Serialize + ?Sized,
{
    let url = format!("{}{}", base_url(state)?, path);
    let mut request = client().request(method, url);
    if authed {
        request = request.bearer_auth(bearer(state)?);
    }
    if let Some(payload) = body {
        request = request.json(payload);
    }

    let response = request.send().await?;
    if !response.status().is_success() {
        return Err(GatewayError::from_status(response.status()));
    }
    Ok(())
}

pub(crate) async fn pair(
    state: &AppState,
    request: PairRequest,
) -> Result<OkResponse, GatewayError> {
    let response: PairResponse =
        request_json(state, Method::POST, "/app/pair", Some(&request), false).await?;
    Ok(OkResponse {
        ok: response.paired,
    })
}

pub(crate) async fn session_begin(
    state: &AppState,
    request: SessionBeginRequest,
) -> Result<SessionBeginResponse, GatewayError> {
    request_json(
        state,
        Method::POST,
        "/app/session/begin",
        Some(&request),
        false,
    )
    .await
}

pub(crate) async fn session_complete(
    state: &AppState,
    request: SessionCompleteRequest,
) -> Result<SessionCompleteResponse, GatewayError> {
    let response: SessionCompleteResponse = request_json(
        state,
        Method::POST,
        "/app/session/complete",
        Some(&request),
        false,
    )
    .await?;
    state.set_token(response.session_token.clone());
    Ok(response)
}

pub(crate) async fn unlock_begin(
    state: &AppState,
    request: UnlockBeginRequest,
) -> Result<UnlockBeginResponse, GatewayError> {
    request_json(
        state,
        Method::POST,
        "/app/unlock/begin",
        Some(&request),
        true,
    )
    .await
}

pub(crate) async fn unlock_complete(
    state: &AppState,
    request: UnlockCompleteRequest,
) -> Result<OkResponse, GatewayError> {
    let response: UnlockResponse = request_json(
        state,
        Method::POST,
        "/app/unlock/complete",
        Some(&request),
        true,
    )
    .await?;
    Ok(OkResponse {
        ok: response.unlocked,
    })
}

pub(crate) async fn status(state: &AppState) -> Result<StatusResponse, GatewayError> {
    request_json::<StatusResponse, ()>(state, Method::GET, "/app/status", None, false).await
}

pub(crate) async fn review_pending(state: &AppState) -> Result<Vec<ReviewItem>, GatewayError> {
    request_json::<Vec<ReviewItem>, ()>(state, Method::GET, "/app/review/pending", None, true).await
}

pub(crate) async fn review_auto_enabled(state: &AppState) -> Result<Vec<ReviewItem>, GatewayError> {
    request_json::<Vec<ReviewItem>, ()>(state, Method::GET, "/app/review/auto-enabled", None, true)
        .await
}

pub(crate) async fn review_approve(
    state: &AppState,
    name: String,
) -> Result<OkResponse, GatewayError> {
    #[derive(Serialize)]
    struct ReviewDecision {
        name: String,
    }

    request_json(
        state,
        Method::POST,
        "/app/review/approve",
        Some(&ReviewDecision { name }),
        true,
    )
    .await
}

pub(crate) async fn review_reject(
    state: &AppState,
    name: String,
) -> Result<OkResponse, GatewayError> {
    #[derive(Serialize)]
    struct ReviewDecision {
        name: String,
    }

    request_json(
        state,
        Method::POST,
        "/app/review/reject",
        Some(&ReviewDecision { name }),
        true,
    )
    .await
}

pub(crate) async fn actions_pending(state: &AppState) -> Result<Vec<PendingAction>, GatewayError> {
    request_json::<Vec<PendingAction>, ()>(state, Method::GET, "/app/actions/pending", None, true)
        .await
}

pub(crate) async fn actions_approve(
    state: &AppState,
    id: String,
) -> Result<OkResponse, GatewayError> {
    #[derive(Serialize)]
    struct ActionDecision {
        id: String,
    }

    request_json(
        state,
        Method::POST,
        "/app/actions/approve",
        Some(&ActionDecision { id }),
        true,
    )
    .await
}

pub(crate) async fn actions_reject(
    state: &AppState,
    id: String,
) -> Result<OkResponse, GatewayError> {
    #[derive(Serialize)]
    struct ActionDecision {
        id: String,
    }

    request_json(
        state,
        Method::POST,
        "/app/actions/reject",
        Some(&ActionDecision { id }),
        true,
    )
    .await
}

pub(crate) async fn accept_task_suggestion(
    state: &AppState,
    suggestion_id: String,
    due_at: Option<String>,
) -> Result<TaskSuggestionAcceptResponse, GatewayError> {
    request_json(
        state,
        Method::POST,
        "/app/tasks/suggestion/accept",
        Some(&TaskSuggestionAcceptRequest {
            suggestion_id,
            due_at,
            project_id: None,
        }),
        true,
    )
    .await
}

pub(crate) async fn reject_task_suggestion(
    state: &AppState,
    suggestion_id: String,
) -> Result<OkResponse, GatewayError> {
    request_json(
        state,
        Method::POST,
        "/app/tasks/suggestion/reject",
        Some(&TaskSuggestionRejectRequest { suggestion_id }),
        true,
    )
    .await
}

pub(crate) async fn ask(
    state: &AppState,
    request: AskRequest,
) -> Result<AskResponse, GatewayError> {
    request_json(state, Method::POST, "/app/ask", Some(&request), true).await
}

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

pub(crate) async fn invoke_confirm(
    state: &AppState,
    invoke_id: String,
) -> Result<InvokeConfirmResponse, GatewayError> {
    request_json::<InvokeConfirmResponse, ()>(
        state,
        Method::POST,
        &format!("/app/ask/invoke/{invoke_id}/confirm"),
        None,
        true,
    )
    .await
}

pub(crate) async fn secret_set(
    state: &AppState,
    name: String,
    value: String,
) -> Result<(), GatewayError> {
    request_empty(
        state,
        Method::POST,
        "/app/secrets",
        Some(&SecretSetRequest { name, value }),
        true,
    )
    .await
}

pub(crate) async fn secret_list(state: &AppState) -> Result<Vec<String>, GatewayError> {
    let response: SecretNamesResponse =
        request_json::<SecretNamesResponse, ()>(state, Method::GET, "/app/secrets", None, true)
            .await?;
    Ok(response.names)
}

pub(crate) async fn secret_delete(state: &AppState, name: String) -> Result<(), GatewayError> {
    request_empty::<()>(
        state,
        Method::DELETE,
        &format!("/app/secrets/{name}"),
        None,
        true,
    )
    .await
}

pub(crate) async fn bless_list(state: &AppState) -> Result<Vec<BlessEntry>, GatewayError> {
    let response: BlessListResponse =
        request_json::<BlessListResponse, ()>(state, Method::GET, "/app/bless", None, true).await?;
    Ok(response.capabilities)
}

pub(crate) async fn bless_set(state: &AppState, name: String) -> Result<BlessEntry, GatewayError> {
    request_json::<BlessEntry, ()>(
        state,
        Method::POST,
        &format!("/app/bless/{}", path_segment(&name)),
        None,
        true,
    )
    .await
}

pub(crate) async fn bless_clear(state: &AppState, name: String) -> Result<(), GatewayError> {
    request_empty::<()>(
        state,
        Method::DELETE,
        &format!("/app/bless/{}", path_segment(&name)),
        None,
        true,
    )
    .await
}

async fn oauth_connect(
    state: &AppState,
    scopes: Vec<String>,
) -> Result<OAuthConnectResponse, GatewayError> {
    request_json(
        state,
        Method::POST,
        "/app/oauth/google/connect",
        Some(&OAuthConnectRequest { scopes }),
        true,
    )
    .await
}

async fn oauth_status(state: &AppState) -> Result<OAuthStatusResponse, GatewayError> {
    request_json::<OAuthStatusResponse, ()>(
        state,
        Method::GET,
        "/app/oauth/google/status",
        None,
        true,
    )
    .await
}

async fn oauth_disconnect(
    state: &AppState,
    account: Option<String>,
) -> Result<OAuthDisconnectResponse, GatewayError> {
    request_json(
        state,
        Method::POST,
        "/app/oauth/google/disconnect",
        Some(&OAuthDisconnectRequest { account }),
        true,
    )
    .await
}

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
        #[derive(Deserialize)]
        struct Detail {
            detail: String,
        }
        return match response.json::<Detail>().await {
            Ok(body) => Ok(RolePutResponse::Invalid {
                detail: body.detail,
            }),
            Err(_) => Ok(RolePutResponse::Invalid {
                detail: "invalid model binding".to_string(),
            }),
        };
    }
    Err(GatewayError::from_status(status))
}

pub(crate) async fn lock(state: &AppState) -> Result<OkResponse, GatewayError> {
    let response =
        request_json::<LockResponse, ()>(state, Method::POST, "/app/lock", None, true).await;
    state.clear_token();
    response.map(|body| OkResponse { ok: body.locked })
}

pub(crate) async fn logout(state: &AppState) -> Result<OkResponse, GatewayError> {
    let response =
        request_json::<OkResponse, ()>(state, Method::POST, "/app/logout", None, true).await;
    state.clear_token();
    response
}

pub(crate) async fn layout_get(state: &AppState) -> Result<LayoutDto, GatewayError> {
    request_json::<LayoutDto, ()>(state, Method::GET, "/app/layout", None, true).await
}

pub(crate) async fn layout_put(
    state: &AppState,
    layout: LayoutDto,
) -> Result<LayoutDto, GatewayError> {
    request_json(state, Method::PUT, "/app/layout", Some(&layout), true).await
}

pub(crate) fn parse_stream_frame(frame: &str) -> Result<Option<StreamEvent>, GatewayError> {
    let data = frame.trim();
    if data.is_empty() {
        return Ok(None);
    }
    if data == "[DONE]" {
        // The brain's SSE [DONE] frame currently carries no path/tool metadata. The non-stream
        // /app/ask response remains the source for those answer tags until the wire format changes.
        return Ok(Some(StreamEvent::Done {
            path: None,
            tool_used: None,
            escalated: false,
        }));
    }
    if let Ok(error) = serde_json::from_str::<ErrorFrame>(data) {
        if error.error == "vault_locked" {
            return Ok(Some(StreamEvent::VaultLocked));
        }
        return Err(GatewayError::Network);
    }
    Ok(Some(StreamEvent::Text {
        text: data.to_string(),
    }))
}

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

pub(crate) async fn ask_stream(
    state: &AppState,
    request: AskRequest,
    channel: Channel<StreamEvent>,
) -> Result<(), GatewayError> {
    let url = format!("{}{}", base_url(state)?, "/app/ask/stream");
    let response = client()
        .post(url)
        .bearer_auth(bearer(state)?)
        .json(&request)
        .send()
        .await?;
    if !response.status().is_success() {
        return Err(GatewayError::from_status(response.status()));
    }

    let body = response.text().await?;
    for line in body.lines() {
        let Some(data) = line.strip_prefix("data:") else {
            continue;
        };
        if let Some(event) = parse_stream_frame(data)? {
            channel.send(event).map_err(|_| GatewayError::Network)?;
        }
    }
    Ok(())
}

pub(crate) async fn ask_voice(
    state: &AppState,
    speak: bool,
    channel: Channel<StreamEvent>,
) -> Result<(), GatewayError> {
    let url = format!("{}{}", base_url(state)?, "/app/ask/voice");
    let response = client()
        .post(url)
        .bearer_auth(bearer(state)?)
        .json(&VoiceAskRequest { speak })
        .send()
        .await?;
    if !response.status().is_success() {
        return Err(GatewayError::from_status(response.status()));
    }

    let body = response.text().await?;
    for line in body.lines() {
        let Some(data) = line.strip_prefix("data:") else {
            continue;
        };
        if let Some(event) = parse_stream_frame(data)? {
            channel.send(event).map_err(|_| GatewayError::Network)?;
        }
    }
    Ok(())
}

pub(crate) async fn capability_build(
    state: &AppState,
    build_id: String,
    channel: Channel<BuildStreamEvent>,
) -> Result<(), GatewayError> {
    let url = format!("{}/app/capabilities/{}/build", base_url(state)?, build_id);
    let response = client()
        .post(url)
        .bearer_auth(bearer(state)?)
        .send()
        .await?;
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

#[tauri::command]
pub(crate) async fn app_status(state: State<'_, AppState>) -> Result<StatusResponse, GatewayError> {
    status(&state).await
}

#[tauri::command]
pub(crate) async fn app_review_pending(
    state: State<'_, AppState>,
) -> Result<Vec<ReviewItem>, GatewayError> {
    review_pending(&state).await
}

#[tauri::command]
pub(crate) async fn app_review_auto_enabled(
    state: State<'_, AppState>,
) -> Result<Vec<ReviewItem>, GatewayError> {
    review_auto_enabled(&state).await
}

#[tauri::command]
pub(crate) async fn app_review_approve(
    state: State<'_, AppState>,
    name: String,
) -> Result<OkResponse, GatewayError> {
    review_approve(&state, name).await
}

#[tauri::command]
pub(crate) async fn app_review_reject(
    state: State<'_, AppState>,
    name: String,
) -> Result<OkResponse, GatewayError> {
    review_reject(&state, name).await
}

#[tauri::command]
pub(crate) async fn app_actions_pending(
    state: State<'_, AppState>,
) -> Result<Vec<PendingAction>, GatewayError> {
    actions_pending(&state).await
}

#[tauri::command]
pub(crate) async fn app_actions_approve(
    state: State<'_, AppState>,
    id: String,
) -> Result<OkResponse, GatewayError> {
    actions_approve(&state, id).await
}

#[tauri::command]
pub(crate) async fn app_actions_reject(
    state: State<'_, AppState>,
    id: String,
) -> Result<OkResponse, GatewayError> {
    actions_reject(&state, id).await
}

#[tauri::command]
pub(crate) async fn task_suggestion_accept(
    state: State<'_, AppState>,
    suggestion_id: String,
    due_at: Option<String>,
) -> Result<TaskSuggestionAcceptResponse, GatewayError> {
    accept_task_suggestion(&state, suggestion_id, due_at).await
}

#[tauri::command]
pub(crate) async fn task_suggestion_reject(
    state: State<'_, AppState>,
    suggestion_id: String,
) -> Result<OkResponse, GatewayError> {
    reject_task_suggestion(&state, suggestion_id).await
}

#[tauri::command]
pub(crate) async fn app_ask(
    state: State<'_, AppState>,
    request: AskRequest,
) -> Result<AskResponse, GatewayError> {
    ask(&state, request).await
}

#[tauri::command]
pub(crate) async fn app_ask_stream(
    state: State<'_, AppState>,
    request: AskRequest,
    channel: Channel<StreamEvent>,
) -> Result<(), GatewayError> {
    ask_stream(&state, request, channel).await
}

#[tauri::command]
pub(crate) async fn app_ask_voice(
    state: State<'_, AppState>,
    speak: bool,
    channel: Channel<StreamEvent>,
) -> Result<(), GatewayError> {
    ask_voice(&state, speak, channel).await
}

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

#[tauri::command]
pub(crate) async fn app_invoke_confirm(
    state: State<'_, AppState>,
    invoke_id: String,
) -> Result<InvokeConfirmResponse, GatewayError> {
    invoke_confirm(&state, invoke_id).await
}

#[tauri::command]
pub(crate) async fn app_secret_set(
    state: State<'_, AppState>,
    name: String,
    value: String,
) -> Result<(), GatewayError> {
    secret_set(&state, name, value).await
}

#[tauri::command]
pub(crate) async fn app_secret_list(
    state: State<'_, AppState>,
) -> Result<Vec<String>, GatewayError> {
    secret_list(&state).await
}

#[tauri::command]
pub(crate) async fn app_secret_delete(
    state: State<'_, AppState>,
    name: String,
) -> Result<(), GatewayError> {
    secret_delete(&state, name).await
}

#[tauri::command]
pub(crate) async fn app_bless_list(
    state: State<'_, AppState>,
) -> Result<Vec<BlessEntry>, GatewayError> {
    bless_list(&state).await
}

#[tauri::command]
pub(crate) async fn app_bless_set(
    state: State<'_, AppState>,
    name: String,
) -> Result<BlessEntry, GatewayError> {
    bless_set(&state, name).await
}

#[tauri::command]
pub(crate) async fn app_bless_clear(
    state: State<'_, AppState>,
    name: String,
) -> Result<(), GatewayError> {
    bless_clear(&state, name).await
}

#[tauri::command]
pub(crate) async fn app_oauth_connect(
    state: State<'_, AppState>,
    scopes: Vec<String>,
) -> Result<OAuthConnectResponse, GatewayError> {
    oauth_connect(&state, scopes).await
}

#[tauri::command]
pub(crate) async fn app_oauth_status(
    state: State<'_, AppState>,
) -> Result<OAuthStatusResponse, GatewayError> {
    oauth_status(&state).await
}

#[tauri::command]
pub(crate) async fn app_oauth_disconnect(
    state: State<'_, AppState>,
    account: Option<String>,
) -> Result<OAuthDisconnectResponse, GatewayError> {
    oauth_disconnect(&state, account).await
}

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

#[tauri::command]
pub(crate) async fn app_lock(state: State<'_, AppState>) -> Result<OkResponse, GatewayError> {
    lock(&state).await
}

#[tauri::command]
pub(crate) async fn app_logout(state: State<'_, AppState>) -> Result<OkResponse, GatewayError> {
    logout(&state).await
}

#[tauri::command]
pub(crate) async fn app_layout_get(state: State<'_, AppState>) -> Result<LayoutDto, GatewayError> {
    layout_get(&state).await
}

#[tauri::command]
pub(crate) async fn app_layout_put(
    state: State<'_, AppState>,
    layout: LayoutDto,
) -> Result<LayoutDto, GatewayError> {
    layout_put(&state, layout).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::{Arc, Mutex};
    use tauri::ipc::InvokeResponseBody;
    use wiremock::matchers::{body_json, header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn state_with_server(server: &MockServer) -> AppState {
        let state = AppState::default();
        state.set_base_url(server.uri());
        state
    }

    #[test]
    fn app_state_debug_redacts_token() {
        let state = AppState::default();
        state.set_token("secret-token".to_string());
        let output = format!("{state:?}");
        assert!(output.contains("<redacted>"));
        assert!(!output.contains("secret-token"));
        assert!(!output.to_lowercase().contains("bearer"));
    }

    #[test]
    fn gateway_error_serialization_does_not_leak_token_words() {
        let output = serde_json::to_string(&GatewayError::Http { status: 500 }).unwrap();
        assert!(!output.contains("secret-token"));
        assert!(!output.to_lowercase().contains("bearer"));
    }

    #[test]
    fn status_mapping_handles_auth_and_lock() {
        assert!(matches!(
            GatewayError::from_status(reqwest::StatusCode::UNAUTHORIZED),
            GatewayError::Unauthenticated
        ));
        assert!(matches!(
            GatewayError::from_status(reqwest::StatusCode::LOCKED),
            GatewayError::VaultLocked
        ));
    }

    #[test]
    fn stream_frame_parser_is_typed() {
        assert!(matches!(
            parse_stream_frame("hello").unwrap(),
            Some(StreamEvent::Text { .. })
        ));
        assert!(matches!(
            parse_stream_frame(r#"{"error":"vault_locked"}"#).unwrap(),
            Some(StreamEvent::VaultLocked)
        ));
        assert!(matches!(
            parse_stream_frame("[DONE]").unwrap(),
            Some(StreamEvent::Done { .. })
        ));
        assert!(matches!(
            parse_stream_frame(r#"{"error":"other"}"#),
            Err(GatewayError::Network)
        ));
    }

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

    #[test]
    fn zeroizing_token_is_removed_on_clear() {
        let state = AppState::default();
        state.set_token("secret-token".to_string());
        state.clear_token();
        assert!(state.token().is_none());
    }

    #[test]
    fn path_segment_encodes_capability_names_for_routes() {
        assert_eq!(path_segment("Date Utility/v2"), "Date%20Utility%2Fv2");
    }

    #[tokio::test]
    async fn pair_posts_exact_request_shape_without_bearer() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        let body = json!({
            "device_id": "device-1",
            "public_key_b64": "pub",
            "pairing_code": "code",
            "code_signature_b64": "sig"
        });
        Mock::given(method("POST"))
            .and(path("/app/pair"))
            .and(body_json(&body))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "paired": true })))
            .expect(1)
            .mount(&server)
            .await;

        let response = pair(
            &state,
            PairRequest {
                device_id: "device-1".to_string(),
                public_key_b64: "pub".to_string(),
                pairing_code: "code".to_string(),
                code_signature_b64: "sig".to_string(),
            },
        )
        .await
        .unwrap();

        assert!(response.ok);
    }

    #[tokio::test]
    async fn authed_routes_inject_bearer_header() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("GET"))
            .and(path("/app/layout"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "version": 1,
                "updated_at": "2026-06-24T00:00:00.000Z",
                "cards": []
            })))
            .expect(1)
            .mount(&server)
            .await;

        let response = layout_get(&state).await.unwrap();

        assert_eq!(response.version, 1);
    }

    #[tokio::test]
    async fn status_gets_live_status_response_without_network_gate() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        Mock::given(method("GET"))
            .and(path("/app/status"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "connected": true,
                "vault_unlocked": false,
                "device_id": "device-1"
            })))
            .expect(1)
            .mount(&server)
            .await;

        let response = status(&state).await.unwrap();

        let encoded = serde_json::to_value(&response).unwrap();
        assert_eq!(
            encoded,
            json!({
                "connected": true,
                "vault_unlocked": false,
                "device_id": "device-1"
            })
        );
    }

    #[tokio::test]
    async fn connect_and_ask_use_brain_app_contract() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        Mock::given(method("POST"))
            .and(path("/app/session/begin"))
            .and(body_json(json!({ "device_id": "device-1" })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "nonce_b64": "nonce"
            })))
            .expect(1)
            .mount(&server)
            .await;

        let begin = session_begin(
            &state,
            SessionBeginRequest {
                device_id: "device-1".to_string(),
            },
        )
        .await
        .unwrap();
        assert_eq!(begin.nonce_b64, "nonce");

        Mock::given(method("POST"))
            .and(path("/app/session/complete"))
            .and(body_json(json!({
                "device_id": "device-1",
                "nonce_b64": "nonce",
                "counter": 7,
                "signature_b64": "sig"
            })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "session_token": "session-token",
                "expires_at": 123
            })))
            .expect(1)
            .mount(&server)
            .await;
        session_complete(
            &state,
            SessionCompleteRequest {
                device_id: "device-1".to_string(),
                nonce_b64: begin.nonce_b64,
                counter: 7,
                signature_b64: "sig".to_string(),
            },
        )
        .await
        .unwrap();

        Mock::given(method("POST"))
            .and(path("/app/ask"))
            .and(header("authorization", "Bearer session-token"))
            .and(body_json(json!({ "text": "hello" })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "text": "answer",
                "path": "direct",
                "tool_used": null,
                "escalated": false
            })))
            .expect(1)
            .mount(&server)
            .await;

        let response = ask(
            &state,
            AskRequest {
                text: "hello".to_string(),
            },
        )
        .await
        .unwrap();
        let encoded = serde_json::to_value(&response).unwrap();
        assert_eq!(
            encoded,
            json!({
                "text": "answer",
                "path": "direct",
                "tool_used": null,
                "escalated": false,
                "invoke_id": null,
                "capability": null,
                "egress_domains": null,
                "secrets": null,
                "args": null,
                "missing": null,
                "verdict": null,
                "verdict_reason": null,
                "answered_from": null
            })
        );
    }

    #[tokio::test]
    async fn ask_carries_loop_verdict_fields() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("session-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/ask"))
            .and(header("authorization", "Bearer session-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "text": "you have lunch at noon",
                "path": "loop",
                "tool_used": null,
                "escalated": true,
                "verdict": "flagged",
                "verdict_reason": "no calendar record matched",
                "answered_from": "general_knowledge"
            })))
            .expect(1)
            .mount(&server)
            .await;

        let response = ask(
            &state,
            AskRequest {
                text: "when is lunch".to_string(),
            },
        )
        .await
        .unwrap();

        assert_eq!(response.path, "loop");
        assert!(response.escalated);
        assert_eq!(response.verdict.as_deref(), Some("flagged"));
        assert_eq!(
            response.verdict_reason.as_deref(),
            Some("no calendar record matched")
        );
        assert_eq!(
            response.answered_from.as_deref(),
            Some("general_knowledge")
        );
    }

    #[tokio::test]
    async fn http_401_and_423_map_to_gateway_errors() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("GET"))
            .and(path("/app/layout"))
            .respond_with(ResponseTemplate::new(401))
            .expect(1)
            .mount(&server)
            .await;
        assert!(matches!(
            layout_get(&state).await,
            Err(GatewayError::Unauthenticated)
        ));

        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("GET"))
            .and(path("/app/layout"))
            .respond_with(ResponseTemplate::new(423))
            .expect(1)
            .mount(&server)
            .await;
        assert!(matches!(
            layout_get(&state).await,
            Err(GatewayError::VaultLocked)
        ));
    }

    #[tokio::test]
    async fn lock_clears_session_token_after_success() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/lock"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "locked": true })))
            .expect(1)
            .mount(&server)
            .await;

        let response = lock(&state).await.unwrap();

        assert!(response.ok);
        assert!(state.token().is_none());
    }

    #[tokio::test]
    async fn actions_pending_gets_authed_response_without_args() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("GET"))
            .and(path("/app/actions/pending"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!([
                {
                    "id": "act-1",
                    "module": "calendar",
                    "tool": "create_event",
                    "summary": "Create lunch",
                    "action_class": "takes-action",
                    "status": "pending",
                    "created_at": "2026-06-27T00:00:00Z",
                    "expires_at": "2026-06-27T01:00:00Z",
                    "result": null
                }
            ])))
            .expect(1)
            .mount(&server)
            .await;

        let response = actions_pending(&state).await.unwrap();
        let encoded = serde_json::to_value(&response).unwrap();

        assert_eq!(response[0].id, "act-1");
        assert!(encoded[0].get("args").is_none());
    }

    #[tokio::test]
    async fn actions_approve_posts_id_with_bearer() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/actions/approve"))
            .and(header("authorization", "Bearer secret-token"))
            .and(body_json(json!({ "id": "act-1" })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "ok": true })))
            .expect(1)
            .mount(&server)
            .await;

        let response = actions_approve(&state, "act-1".to_string()).await.unwrap();

        assert!(response.ok);
    }

    #[tokio::test]
    async fn capability_propose_posts_goal_with_bearer() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/capabilities/propose"))
            .and(header("authorization", "Bearer secret-token"))
            .and(body_json(json!({ "goal": "make a planner" })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "build_id": "b",
                "name": "Planner",
                "description": "Plan things",
                "summary": "Adds planning",
                "secrets": ["TOKEN"],
                "egress_domains": ["www.googleapis.com"],
                "oauth_scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
                "missing_secrets": ["TOKEN"],
                "blocked": false,
                "block_reason": null
            })))
            .expect(1)
            .mount(&server)
            .await;

        let response = capability_propose(&state, "make a planner".to_string())
            .await
            .unwrap();

        let encoded = serde_json::to_value(&response).unwrap();
        assert_eq!(
            encoded,
            json!({
                "build_id": "b",
                "name": "Planner",
                "description": "Plan things",
                "summary": "Adds planning",
                "secrets": ["TOKEN"],
                "egress_domains": ["www.googleapis.com"],
                "oauth_scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
                "missing_secrets": ["TOKEN"],
                "blocked": false,
                "block_reason": null
            })
        );
    }

    #[tokio::test]
    async fn invoke_confirm_posts_to_confirm_route_with_bearer() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/ask/invoke/inv-1/confirm"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "invoke_id": "inv-1",
                "status": "ok",
                "text": "done",
                "missing_secrets": []
            })))
            .expect(1)
            .mount(&server)
            .await;

        let response = invoke_confirm(&state, "inv-1".to_string()).await.unwrap();

        let encoded = serde_json::to_value(&response).unwrap();
        assert_eq!(
            encoded,
            json!({
                "invoke_id": "inv-1",
                "status": "ok",
                "text": "done",
                "missing_secrets": []
            })
        );
    }

    #[tokio::test]
    async fn actions_reject_posts_id_with_bearer() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/actions/reject"))
            .and(header("authorization", "Bearer secret-token"))
            .and(body_json(json!({ "id": "act-1" })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "ok": true })))
            .expect(1)
            .mount(&server)
            .await;

        let response = actions_reject(&state, "act-1".to_string()).await.unwrap();

        assert!(response.ok);
    }

    #[tokio::test]
    async fn bless_commands_use_session_bearer_and_expected_routes() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("GET"))
            .and(path("/app/bless"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "capabilities": [{
                    "name": "Echo",
                    "current_version": 2,
                    "blessed_version": 2,
                    "blessed": true
                }]
            })))
            .expect(1)
            .mount(&server)
            .await;

        let listed = bless_list(&state).await.unwrap();
        assert_eq!(listed[0].name, "Echo");
        assert!(listed[0].blessed);

        Mock::given(method("POST"))
            .and(path("/app/bless/Date%20Utility"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "name": "Date Utility",
                "current_version": 2,
                "blessed_version": 2,
                "blessed": true
            })))
            .expect(1)
            .mount(&server)
            .await;
        assert!(
            bless_set(&state, "Date Utility".to_string())
                .await
                .unwrap()
                .blessed
        );

        Mock::given(method("DELETE"))
            .and(path("/app/bless/Date%20Utility"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(204))
            .expect(1)
            .mount(&server)
            .await;
        bless_clear(&state, "Date Utility".to_string())
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn oauth_commands_use_session_bearer_and_expected_routes() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/oauth/google/connect"))
            .and(header("authorization", "Bearer secret-token"))
            .and(body_json(json!({
                "scopes": ["https://www.googleapis.com/auth/calendar.readonly"]
            })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "consent_url": "https://accounts.google.com/o/oauth2/v2/auth"
            })))
            .expect(1)
            .mount(&server)
            .await;

        let connected = oauth_connect(
            &state,
            vec!["https://www.googleapis.com/auth/calendar.readonly".to_string()],
        )
        .await
        .unwrap();
        let encoded = serde_json::to_value(&connected).unwrap();
        assert_eq!(
            encoded,
            json!({
                "consent_url": "https://accounts.google.com/o/oauth2/v2/auth"
            })
        );

        Mock::given(method("GET"))
            .and(path("/app/oauth/google/status"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "account": "default",
                "connected": true,
                "granted_scopes": ["scope-a"]
            })))
            .expect(1)
            .mount(&server)
            .await;
        let status = oauth_status(&state).await.unwrap();
        assert!(status.connected);
        assert_eq!(status.account, "default");

        Mock::given(method("POST"))
            .and(path("/app/oauth/google/disconnect"))
            .and(header("authorization", "Bearer secret-token"))
            .and(body_json(json!({})))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "disconnected": true
            })))
            .expect(1)
            .mount(&server)
            .await;
        let response = oauth_disconnect(&state, None).await.unwrap();
        assert!(response.disconnected);
    }

    #[tokio::test]
    async fn models_get_lists_roles_providers_and_dropped() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        let body = json!({
            "roles": [
                {
                    "role": "reader",
                    "provider": "claude_code",
                    "model": "sonnet",
                    "constraints": {
                        "no_tools": true,
                        "temperature": null
                    },
                    "eligible_providers": ["claude_code", "ollama"],
                    "editable_fields": ["provider", "model"]
                },
                {
                    "role": "extractor",
                    "provider": "codex",
                    "model": "gpt-5",
                    "constraints": {
                        "no_tools": false,
                        "temperature": 0.0
                    },
                    "eligible_providers": ["codex"],
                    "editable_fields": ["model"]
                }
            ],
            "providers": ["claude_code", "codex", "ollama", "router"],
            "dropped_overrides": [
                {
                    "role": "reader",
                    "reason": "no_tools_ineligible"
                }
            ]
        });
        Mock::given(method("GET"))
            .and(path("/app/models"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(body.clone()))
            .expect(1)
            .mount(&server)
            .await;

        let response = models_get(&state).await.unwrap();

        assert_eq!(response.roles[0].constraints.temperature, None);
        assert_eq!(response.roles[1].constraints.temperature, Some(0.0));
        assert_eq!(
            response.roles[0].eligible_providers,
            vec!["claude_code".to_string(), "ollama".to_string()]
        );
        assert_eq!(
            response.roles[0].editable_fields,
            vec!["provider".to_string(), "model".to_string()]
        );
        assert_eq!(response.dropped_overrides[0].reason, "no_tools_ineligible");
        assert_eq!(serde_json::to_value(&response).unwrap(), body);
    }

    #[tokio::test]
    async fn models_put_updated_and_invalid_arms() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        let loop_driver_path = format!("/app/models/{}", path_segment("loop_driver"));
        Mock::given(method("PUT"))
            .and(path(loop_driver_path.as_str()))
            .and(header("authorization", "Bearer secret-token"))
            .and(body_json(json!({
                "provider": "codex",
                "model": "gpt-5.5"
            })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "role": "loop_driver",
                "provider": "codex",
                "model": "gpt-5.5",
                "constraints": {
                    "no_tools": false,
                    "temperature": null
                },
                "eligible_providers": ["codex", "claude_code"],
                "editable_fields": ["provider", "model"]
            })))
            .expect(1)
            .mount(&server)
            .await;

        let updated = models_put(
            &state,
            "loop_driver".to_string(),
            "codex".to_string(),
            "gpt-5.5".to_string(),
        )
        .await
        .unwrap();
        assert!(matches!(updated, RolePutResponse::Updated(_)));

        let reader_path = format!("/app/models/{}", path_segment("reader"));
        Mock::given(method("PUT"))
            .and(path(reader_path.as_str()))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(422).set_body_json(json!({
                "detail": "reader must resolve to a no-tools-capable provider"
            })))
            .expect(1)
            .mount(&server)
            .await;

        let invalid = models_put(
            &state,
            "reader".to_string(),
            "codex".to_string(),
            "gpt-5.5".to_string(),
        )
        .await
        .unwrap();

        let RolePutResponse::Invalid { detail } = invalid else {
            panic!("expected invalid response");
        };
        assert_eq!(detail, "reader must resolve to a no-tools-capable provider");
    }

    #[tokio::test]
    async fn models_usage_returns_per_role_aggregates() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("GET"))
            .and(path("/app/models/usage"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "roles": [
                    {
                        "role": "selector",
                        "calls": 1,
                        "prompt_tokens": 2,
                        "completion_tokens": 4,
                        "avg_latency_ms": 7.0
                    }
                ]
            })))
            .expect(1)
            .mount(&server)
            .await;

        let response = models_usage(&state).await.unwrap();

        assert_eq!(response.roles[0].calls, 1);
        assert_eq!(response.roles[0].avg_latency_ms, 7.0);
    }

    #[tokio::test]
    async fn task_suggestion_accept_posts_due_date_with_bearer() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/tasks/suggestion/accept"))
            .and(header("authorization", "Bearer secret-token"))
            .and(body_json(json!({
                "suggestion_id": "sug-1",
                "due_at": "2026-07-02",
                "project_id": null
            })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "task": {
                    "id": "task-1",
                    "due_at": "2026-07-02"
                }
            })))
            .expect(1)
            .mount(&server)
            .await;

        let response =
            accept_task_suggestion(&state, "sug-1".to_string(), Some("2026-07-02".to_string()))
                .await
                .unwrap();

        assert_eq!(response.task["id"], "task-1");
        assert_eq!(response.task["due_at"], "2026-07-02");
    }

    #[tokio::test]
    async fn task_suggestion_reject_posts_id_with_bearer() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/tasks/suggestion/reject"))
            .and(header("authorization", "Bearer secret-token"))
            .and(body_json(json!({ "suggestion_id": "sug-1" })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "ok": true })))
            .expect(1)
            .mount(&server)
            .await;

        let response = reject_task_suggestion(&state, "sug-1".to_string())
            .await
            .unwrap();

        assert!(response.ok);
    }

    #[tokio::test]
    async fn ask_voice_posts_speak_flag_and_emits_stream_events() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("secret-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/ask/voice"))
            .and(header("authorization", "Bearer secret-token"))
            .and(body_json(json!({ "speak": true })))
            .respond_with(
                ResponseTemplate::new(200).set_body_string("data: hello\n\ndata: [DONE]\n\n"),
            )
            .expect(1)
            .mount(&server)
            .await;
        let events = Arc::new(Mutex::new(Vec::new()));
        let captured_events = Arc::clone(&events);
        let channel = Channel::new(move |body| {
            let InvokeResponseBody::Json(json) = body else {
                return Err(tauri::Error::FailedToReceiveMessage);
            };
            captured_events
                .lock()
                .unwrap()
                .push(serde_json::from_str::<StreamEvent>(&json)?);
            Ok(())
        });

        ask_voice(&state, true, channel).await.unwrap();

        let events = events.lock().unwrap();
        assert!(matches!(events[0], StreamEvent::Text { .. }));
        assert!(matches!(events[1], StreamEvent::Done { .. }));
    }
}
