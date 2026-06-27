#![cfg(target_os = "macos")]

use crate::Keystore;
use crate::error::KeystoreError;

/// Gated Secure Enclave implementation.
///
/// The production path will use a non-exportable P-256 Secure Enclave key with biometric private
/// key usage. It is compiled only on macOS and intentionally not exercised on the Windows dev wall.
pub struct MacosKeystore;

impl MacosKeystore {
    pub fn new() -> Self {
        Self
    }
}

impl Keystore for MacosKeystore {
    fn create_key(&mut self) -> Result<(), KeystoreError> {
        Err(KeystoreError::HardwareUnavailable)
    }

    fn sign(&mut self, _digest: &[u8; 32]) -> Result<Vec<u8>, KeystoreError> {
        Err(KeystoreError::HardwareUnavailable)
    }

    fn get_public_key(&mut self) -> Result<Vec<u8>, KeystoreError> {
        Err(KeystoreError::HardwareUnavailable)
    }

    fn destroy_key(&mut self) -> Result<(), KeystoreError> {
        Err(KeystoreError::HardwareUnavailable)
    }

    fn has_key(&mut self) -> Result<bool, KeystoreError> {
        Err(KeystoreError::HardwareUnavailable)
    }
}
