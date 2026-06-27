use std::sync::Mutex;

use tauri::{Manager, Runtime, plugin::TauriPlugin};

pub mod counter;
mod commands;
pub mod error;
#[cfg(target_os = "macos")]
mod macos;
pub mod sig;
#[cfg(windows)]
mod windows;

use error::KeystoreError;

/// Keystore abstraction for a non-exportable P-256 device signing key.
///
/// Implementations must never expose private key bytes. `sign` accepts an externally computed
/// SHA-256 digest and returns only a DER-encoded ECDSA signature.
pub trait Keystore: Send {
    fn create_key(&mut self) -> Result<(), KeystoreError>;
    fn sign(&mut self, digest: &[u8; 32]) -> Result<Vec<u8>, KeystoreError>;
    fn get_public_key(&mut self) -> Result<Vec<u8>, KeystoreError>;
    fn destroy_key(&mut self) -> Result<(), KeystoreError>;
    fn has_key(&mut self) -> Result<bool, KeystoreError>;
}

pub type KeystoreState = Mutex<Box<dyn Keystore>>;

#[cfg(windows)]
pub fn platform_keystore() -> Box<dyn Keystore> {
    Box::new(windows::WindowsKeystore::new())
}

#[cfg(target_os = "macos")]
pub fn platform_keystore() -> Box<dyn Keystore> {
    Box::new(macos::MacosKeystore::new())
}

#[cfg(not(any(windows, target_os = "macos")))]
pub fn platform_keystore() -> Box<dyn Keystore> {
    Box::new(UnsupportedKeystore)
}

#[cfg(not(any(windows, target_os = "macos")))]
struct UnsupportedKeystore;

#[cfg(not(any(windows, target_os = "macos")))]
impl Keystore for UnsupportedKeystore {
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

/// Initialize the Artemis keystore plugin and its process-local hardware key handle owner.
pub fn init<R: Runtime>() -> TauriPlugin<R> {
    tauri::plugin::Builder::<R>::new("keystore")
        .setup(|app, _api| {
            app.manage(KeystoreState::new(platform_keystore()));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::create_key,
            commands::sign,
            commands::get_public_key,
            commands::destroy_key,
            commands::has_key
        ])
        .build()
}
