use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use serde::ser::{SerializeStruct, Serializer};
use serde::Serialize;
use sha2::{Digest, Sha256};
use tauri::{Manager, State};
use tauri_plugin_keystore::counter::CounterStore;
use tauri_plugin_keystore::error::KeystoreError;
use tauri_plugin_keystore::KeystoreState;
use thiserror::Error;
use zeroize::Zeroizing;

use crate::error::GatewayError;
use crate::gateway::{
    self, OkResponse, PairRequest, SessionBeginRequest, SessionCompleteRequest, UnlockBeginRequest,
    UnlockCompleteRequest,
};
use crate::state::AppState;

const CONNECT_CONTEXT: &[u8] = b"session";
const UNLOCK_CONTEXT: &[u8] = b"unlock";

/// IPC-facing auth orchestration error.
///
/// It deliberately carries no signature bytes, nonces, backend status codes, or passphrase material.
#[derive(Debug, Error)]
pub(crate) enum AuthError {
    #[error("keystore error")]
    Keystore(#[from] KeystoreError),
    #[error("gateway error")]
    Gateway(#[from] GatewayError),
    #[error("encoding error")]
    Encoding,
}

impl Serialize for AuthError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let kind = match self {
            Self::Keystore(KeystoreError::BiometricCancelled) => "biometricCancelled",
            Self::Keystore(KeystoreError::HardwareUnavailable) => "hardwareUnavailable",
            Self::Keystore(KeystoreError::KeyNotFound) => "keyNotFound",
            Self::Keystore(KeystoreError::Encoding) | Self::Encoding => "encoding",
            Self::Gateway(GatewayError::Unauthenticated) => "unauthenticated",
            Self::Gateway(GatewayError::VaultLocked) => "vaultLocked",
            Self::Gateway(GatewayError::Http {
                status: 400 | 401 | 403 | 404 | 410,
            }) => "pairingRejected",
            Self::Gateway(GatewayError::Http { .. }) | Self::Gateway(GatewayError::Network) => {
                "network"
            }
        };
        let mut state = serializer.serialize_struct("AuthError", 1)?;
        state.serialize_field("kind", kind)?;
        state.end()
    }
}

/// Pair this client by creating a fresh device key and signing the pairing code proof.
#[tauri::command]
pub(crate) async fn auth_pair(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    keystore: State<'_, KeystoreState>,
    pairing_code: String,
) -> Result<OkResponse, AuthError> {
    let counter = counter_store(&app)?;
    let (device_id, public_key_b64, signature_b64) =
        create_and_sign_pairing(&keystore, &counter, &pairing_code)?;

    gateway::pair(
        &state,
        PairRequest {
            device_id,
            public_key_b64,
            pairing_code,
            code_signature_b64: signature_b64,
        },
    )
    .await
    .map_err(AuthError::from)
}

/// Complete the signed session bootstrap and store the returned session token in `AppState`.
///
/// Returns `()` — the session token is stored in `AppState` (Rust-only) and is deliberately
/// NOT serialized back to the webview (ADR-030: the session token never reaches the webview).
#[tauri::command]
pub(crate) async fn auth_connect(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    keystore: State<'_, KeystoreState>,
) -> Result<(), AuthError> {
    let counter = counter_store(&app)?;
    let device_id = device_id(&public_key(&keystore)?);
    let begin = gateway::session_begin(
        &state,
        SessionBeginRequest {
            device_id: device_id.clone(),
        },
    )
    .await?;
    let (proof_counter, signature_b64) =
        sign_nonce_context(&keystore, &counter, &begin.nonce_b64, CONNECT_CONTEXT)?;
    gateway::session_complete(
        &state,
        SessionCompleteRequest {
            device_id,
            nonce_b64: begin.nonce_b64,
            counter: proof_counter,
            signature_b64,
        },
    )
    .await?;
    Ok(())
}

/// Complete a signed unlock proof using the existing session token.
#[tauri::command]
pub(crate) async fn auth_unlock(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    keystore: State<'_, KeystoreState>,
) -> Result<OkResponse, AuthError> {
    let counter = counter_store(&app)?;
    let begin = gateway::unlock_begin(&state, UnlockBeginRequest {}).await?;
    let (proof_counter, signature_b64) =
        sign_nonce_context(&keystore, &counter, &begin.nonce_b64, UNLOCK_CONTEXT)?;
    gateway::unlock_complete(
        &state,
        UnlockCompleteRequest {
            nonce_b64: begin.nonce_b64,
            counter: proof_counter,
            signature_b64,
        },
    )
    .await
    .map_err(AuthError::from)
}

/// Log out of the current session and clear the in-memory token.
#[tauri::command]
pub(crate) async fn auth_logout(state: State<'_, AppState>) -> Result<OkResponse, AuthError> {
    gateway::logout(&state).await.map_err(AuthError::from)
}

/// Relay a recovery passphrase without retaining it in Rust after the command returns.
///
/// Tauri command args must impl `CommandArg` (deserializable), which `Zeroizing<String>`
/// does not, so the passphrase arrives as a `String` and is wrapped in `Zeroizing`
/// immediately — the Rust-held copy is zeroized on drop. (The transient String produced by
/// the IPC deserializer is an unavoidable boundary artifact; the TS side clears its own ref.)
///
/// DEV-WALL (ADR-005, broker Mac-gated): the Argon2id-wrapped DEK escrow relay lives host-side
/// in the broker, which is not present on the Windows dev box (same Mac-gate as M2-c/broker).
/// On this platform the passphrase is zeroized and discarded — the client never holds the DEK.
/// Wiring the actual broker escrow relay (using the `argon2` dep) is the Mac-gated follow-up.
#[tauri::command]
pub(crate) async fn auth_recover(passphrase: String) -> Result<(), AuthError> {
    let _passphrase = Zeroizing::new(passphrase);
    Ok(())
}

fn counter_store(app: &tauri::AppHandle) -> Result<CounterStore, AuthError> {
    let app_data_dir = app.path().app_data_dir().map_err(|_| AuthError::Encoding)?;
    Ok(CounterStore::new(app_data_dir))
}

fn create_and_sign_pairing(
    keystore: &KeystoreState,
    counter: &CounterStore,
    pairing_code: &str,
) -> Result<(String, String, String), AuthError> {
    {
        let mut keystore = keystore
            .lock()
            .map_err(|_| KeystoreError::HardwareUnavailable)?;
        if !keystore.has_key()? {
            keystore.create_key()?;
            counter.reset_for_new_key()?;
        }
    }
    let public_key = public_key(keystore)?;
    let device_id = device_id(&public_key);
    let message = pairing_message(pairing_code.as_bytes(), device_id.as_bytes())?;
    let signature = sign_message(keystore, &message)?;
    Ok((
        device_id,
        STANDARD.encode(public_key),
        STANDARD.encode(signature),
    ))
}

fn sign_nonce_context(
    keystore: &KeystoreState,
    counter: &CounterStore,
    nonce_b64: &str,
    context: &[u8],
) -> Result<(u64, String), AuthError> {
    let nonce = STANDARD
        .decode(nonce_b64)
        .map_err(|_| AuthError::Encoding)?;
    let proof_counter = counter.next()?;
    let message = proof_message(&nonce, context, proof_counter)?;
    let signature = sign_message(keystore, &message)?;
    Ok((proof_counter, STANDARD.encode(signature)))
}

fn sign_message(keystore: &KeystoreState, message: &[u8]) -> Result<Vec<u8>, AuthError> {
    let digest: [u8; 32] = Sha256::digest(message).into();
    keystore
        .lock()
        .map_err(|_| KeystoreError::HardwareUnavailable)?
        .sign(&digest)
        .map_err(AuthError::from)
}

fn public_key(keystore: &KeystoreState) -> Result<Vec<u8>, AuthError> {
    keystore
        .lock()
        .map_err(|_| KeystoreError::HardwareUnavailable)?
        .get_public_key()
        .map_err(AuthError::from)
}

fn device_id(public_key: &[u8]) -> String {
    let digest = Sha256::digest(public_key);
    format!("artemis-{}", hex_lower(&digest[..16]))
}

fn pairing_message(code: &[u8], device_id: &[u8]) -> Result<Vec<u8>, AuthError> {
    let mut message = Vec::with_capacity(2 + code.len() + device_id.len());
    push_len_prefixed(&mut message, code)?;
    message.extend_from_slice(device_id);
    Ok(message)
}

fn proof_message(nonce: &[u8], context: &[u8], counter: u64) -> Result<Vec<u8>, AuthError> {
    let mut message = Vec::with_capacity(2 + nonce.len() + 2 + context.len() + 8);
    push_len_prefixed(&mut message, nonce)?;
    push_len_prefixed(&mut message, context)?;
    message.extend_from_slice(&counter.to_be_bytes());
    Ok(message)
}

fn push_len_prefixed(message: &mut Vec<u8>, value: &[u8]) -> Result<(), AuthError> {
    let len = u16::try_from(value.len()).map_err(|_| AuthError::Encoding)?;
    message.extend_from_slice(&len.to_be_bytes());
    message.extend_from_slice(value);
    Ok(())
}

fn hex_lower(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::sync::Mutex;

    use serde_json::json;
    use tauri_plugin_keystore::Keystore;
    use wiremock::matchers::{body_json, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    use super::*;

    struct FakeKeystore {
        created: bool,
        public_key: Vec<u8>,
        signatures: Vec<Vec<u8>>,
    }

    impl FakeKeystore {
        fn new() -> Self {
            Self {
                created: false,
                public_key: vec![4, 1, 2, 3],
                signatures: Vec::new(),
            }
        }
    }

    impl Keystore for FakeKeystore {
        fn create_key(&mut self) -> Result<(), KeystoreError> {
            self.created = true;
            Ok(())
        }

        fn sign(&mut self, digest: &[u8; 32]) -> Result<Vec<u8>, KeystoreError> {
            let mut signature = vec![0x30, 0x44];
            signature.extend_from_slice(digest);
            self.signatures.push(signature.clone());
            Ok(signature)
        }

        fn get_public_key(&mut self) -> Result<Vec<u8>, KeystoreError> {
            if self.created {
                Ok(self.public_key.clone())
            } else {
                Err(KeystoreError::KeyNotFound)
            }
        }

        fn destroy_key(&mut self) -> Result<(), KeystoreError> {
            self.created = false;
            Ok(())
        }

        fn has_key(&mut self) -> Result<bool, KeystoreError> {
            Ok(self.created)
        }
    }

    fn state_with_server(server: &MockServer) -> AppState {
        let state = AppState::default();
        *state
            .brain_base_url
            .lock()
            .expect("brain base URL mutex poisoned") = Some(server.uri());
        state
    }

    #[test]
    fn signed_message_layouts_are_length_prefixed() {
        assert_eq!(
            pairing_message(b"123456", b"device").unwrap(),
            b"\0\x06123456device"
        );
        assert_eq!(
            proof_message(b"nonce", b"unlock", 9).unwrap(),
            b"\0\x05nonce\0\x06unlock\0\0\0\0\0\0\0\x09"
        );
    }

    #[test]
    fn corrupt_or_missing_counter_aborts_without_reset() {
        let root = std::env::temp_dir().join(format!("artemis-counter-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let counter = CounterStore::new(root.clone());
        assert!(matches!(counter.next(), Err(KeystoreError::Encoding)));
        counter.reset_for_new_key().unwrap();
        let counter_path = root.join("keystore").join("counter");
        fs::write(&counter_path, b"bad").unwrap();
        assert!(matches!(counter.next(), Err(KeystoreError::Encoding)));
        let _ = fs::remove_dir_all(root);
    }

    #[tokio::test]
    async fn pair_connect_unlock_with_fake_signer_advances_counter_and_sets_token() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        let keystore: KeystoreState = Mutex::new(Box::new(FakeKeystore::new()));
        let root = std::env::temp_dir().join(format!(
            "artemis-auth-{}-{}",
            std::process::id(),
            server.address().port()
        ));
        let _ = fs::remove_dir_all(&root);
        let counter = CounterStore::new(root.clone());

        let (device_id, public_key_b64, pair_signature_b64) =
            create_and_sign_pairing(&keystore, &counter, "123456").unwrap();
        Mock::given(method("POST"))
            .and(path("/app/pair"))
            .and(body_json(json!({
                "device_id": device_id,
                "public_key_b64": public_key_b64,
                "pairing_code": "123456",
                "code_signature_b64": pair_signature_b64
            })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "paired": true })))
            .expect(1)
            .mount(&server)
            .await;
        gateway::pair(
            &state,
            PairRequest {
                device_id: device_id.clone(),
                public_key_b64,
                pairing_code: "123456".to_string(),
                code_signature_b64: pair_signature_b64,
            },
        )
        .await
        .unwrap();

        Mock::given(method("POST"))
            .and(path("/app/session/begin"))
            .and(body_json(json!({ "device_id": device_id })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "nonce_b64": STANDARD.encode(b"connect-nonce")
            })))
            .expect(1)
            .mount(&server)
            .await;
        let begin = gateway::session_begin(
            &state,
            SessionBeginRequest {
                device_id: device_id.clone(),
            },
        )
        .await
        .unwrap();
        let (connect_counter, connect_signature_b64) =
            sign_nonce_context(&keystore, &counter, &begin.nonce_b64, CONNECT_CONTEXT).unwrap();
        assert_eq!(connect_counter, 1);

        Mock::given(method("POST"))
            .and(path("/app/session/complete"))
            .and(body_json(json!({
                "device_id": device_id,
                "nonce_b64": begin.nonce_b64,
                "counter": connect_counter,
                "signature_b64": connect_signature_b64
            })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "session_token": "session-token",
                "expires_at": 1
            })))
            .expect(1)
            .mount(&server)
            .await;
        gateway::session_complete(
            &state,
            SessionCompleteRequest {
                device_id,
                nonce_b64: begin.nonce_b64,
                counter: connect_counter,
                signature_b64: connect_signature_b64,
            },
        )
        .await
        .unwrap();
        assert_eq!(state.token().as_deref(), Some("session-token"));

        Mock::given(method("POST"))
            .and(path("/app/unlock/begin"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "nonce_b64": STANDARD.encode(b"unlock-nonce")
            })))
            .expect(1)
            .mount(&server)
            .await;
        let unlock_begin = gateway::unlock_begin(&state, UnlockBeginRequest {})
            .await
            .unwrap();
        let (unlock_counter, unlock_signature_b64) =
            sign_nonce_context(&keystore, &counter, &unlock_begin.nonce_b64, UNLOCK_CONTEXT)
                .unwrap();
        assert_eq!(unlock_counter, 2);

        Mock::given(method("POST"))
            .and(path("/app/unlock/complete"))
            .and(body_json(json!({
                "nonce_b64": unlock_begin.nonce_b64,
                "counter": unlock_counter,
                "signature_b64": unlock_signature_b64
            })))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "unlocked": true })))
            .expect(1)
            .mount(&server)
            .await;
        let unlocked = gateway::unlock_complete(
            &state,
            UnlockCompleteRequest {
                nonce_b64: unlock_begin.nonce_b64,
                counter: unlock_counter,
                signature_b64: unlock_signature_b64,
            },
        )
        .await
        .unwrap();
        assert!(unlocked.ok);
        let _ = fs::remove_dir_all(root);
    }
}
