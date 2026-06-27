use tauri::State;

use crate::{KeystoreState, error::KeystoreError};

/// Create or replace the hardware-backed Artemis device signing key.
#[tauri::command]
pub async fn create_key(state: State<'_, KeystoreState>) -> Result<(), KeystoreError> {
    state
        .lock()
        .map_err(|_| KeystoreError::HardwareUnavailable)?
        .create_key()
}

/// Sign an externally computed SHA-256 digest and return a DER ECDSA signature.
#[tauri::command]
pub async fn sign(
    state: State<'_, KeystoreState>,
    digest: [u8; 32],
) -> Result<Vec<u8>, KeystoreError> {
    state
        .lock()
        .map_err(|_| KeystoreError::HardwareUnavailable)?
        .sign(&digest)
}

/// Return the device public key as an X9.63 uncompressed point.
#[tauri::command]
pub async fn get_public_key(state: State<'_, KeystoreState>) -> Result<Vec<u8>, KeystoreError> {
    state
        .lock()
        .map_err(|_| KeystoreError::HardwareUnavailable)?
        .get_public_key()
}

/// Destroy the persisted device signing key.
#[tauri::command]
pub async fn destroy_key(state: State<'_, KeystoreState>) -> Result<(), KeystoreError> {
    state
        .lock()
        .map_err(|_| KeystoreError::HardwareUnavailable)?
        .destroy_key()
}

/// Report whether the persisted device signing key is present.
#[tauri::command]
pub async fn has_key(state: State<'_, KeystoreState>) -> Result<bool, KeystoreError> {
    state
        .lock()
        .map_err(|_| KeystoreError::HardwareUnavailable)?
        .has_key()
}
