use serde::ser::{SerializeStruct, Serializer};
use serde::Serialize;
use thiserror::Error;

/// Closed IPC-facing error set for key custody failures.
///
/// Backend status codes are intentionally not serialized across IPC; callers only learn the
/// stable class needed for fail-closed auth UX.
#[derive(Debug, Error)]
pub enum KeystoreError {
    #[error("biometric prompt was cancelled")]
    BiometricCancelled,
    #[error("hardware key storage is unavailable")]
    HardwareUnavailable,
    #[error("device key was not found")]
    KeyNotFound,
    #[error("key or signature encoding failed")]
    Encoding,
}

impl Serialize for KeystoreError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let kind = match self {
            Self::BiometricCancelled => "biometricCancelled",
            Self::HardwareUnavailable => "hardwareUnavailable",
            Self::KeyNotFound => "keyNotFound",
            Self::Encoding => "encoding",
        };
        let mut state = serializer.serialize_struct("KeystoreError", 1)?;
        state.serialize_field("kind", kind)?;
        state.end()
    }
}
