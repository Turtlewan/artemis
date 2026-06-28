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
    expires_at: u64,
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
pub(crate) struct AskResponse {
    text: String,
    path: String,
    tool_used: Option<String>,
    escalated: bool,
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

pub(crate) async fn ask(
    state: &AppState,
    request: AskRequest,
) -> Result<AskResponse, GatewayError> {
    request_json(state, Method::POST, "/app/ask", Some(&request), true).await
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
    fn zeroizing_token_is_removed_on_clear() {
        let state = AppState::default();
        state.set_token("secret-token".to_string());
        state.clear_token();
        assert!(state.token().is_none());
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
                "escalated": false
            })
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
}
