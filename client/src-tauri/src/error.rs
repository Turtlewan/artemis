use serde::ser::{SerializeStruct, Serializer};
use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Error)]
pub(crate) enum GatewayError {
    #[error("unauthenticated")]
    Unauthenticated,
    #[error("vault locked")]
    VaultLocked,
    #[error("http status {status}")]
    Http { status: u16 },
    #[error("network error")]
    Network,
}

impl GatewayError {
    pub(crate) fn from_status(status: reqwest::StatusCode) -> Self {
        match status.as_u16() {
            401 => Self::Unauthenticated,
            423 => Self::VaultLocked,
            code => Self::Http { status: code },
        }
    }
}

impl From<reqwest::Error> for GatewayError {
    fn from(_: reqwest::Error) -> Self {
        Self::Network
    }
}

impl Serialize for GatewayError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self {
            Self::Unauthenticated => {
                let mut state = serializer.serialize_struct("GatewayError", 1)?;
                state.serialize_field("kind", "unauthenticated")?;
                state.end()
            }
            Self::VaultLocked => {
                let mut state = serializer.serialize_struct("GatewayError", 1)?;
                state.serialize_field("kind", "vaultLocked")?;
                state.end()
            }
            Self::Http { status } => {
                let mut state = serializer.serialize_struct("GatewayError", 2)?;
                state.serialize_field("kind", "http")?;
                state.serialize_field("status", status)?;
                state.end()
            }
            Self::Network => {
                let mut state = serializer.serialize_struct("GatewayError", 1)?;
                state.serialize_field("kind", "network")?;
                state.end()
            }
        }
    }
}
