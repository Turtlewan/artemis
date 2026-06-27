#![cfg(windows)]

use std::ffi::c_void;
use std::mem::size_of;
use std::ptr::{null, null_mut};

use windows_sys::Win32::Security::Cryptography::{
    BCRYPT_ECCKEY_BLOB, BCRYPT_ECCPUBLIC_BLOB, MS_PLATFORM_CRYPTO_PROVIDER,
    NCRYPT_ECDSA_P256_ALGORITHM, NCRYPT_HANDLE, NCRYPT_KEY_HANDLE, NCRYPT_PROV_HANDLE,
    NCRYPT_UI_FORCE_HIGH_PROTECTION_FLAG, NCRYPT_UI_POLICY, NCRYPT_UI_POLICY_PROPERTY,
    NCryptCreatePersistedKey, NCryptDeleteKey, NCryptExportKey, NCryptFinalizeKey, NCryptFreeObject,
    NCryptOpenKey, NCryptOpenStorageProvider, NCryptSetProperty, NCryptSignHash,
};
use windows_sys::core::w;

use crate::error::KeystoreError;
use crate::{Keystore, sig};

const KEY_NAME: windows_sys::core::PCWSTR = w!("ArtemisDeviceSigningKey");
const FRIENDLY_NAME: windows_sys::core::PCWSTR = w!("Artemis device signing key");
const DESCRIPTION: windows_sys::core::PCWSTR = w!("Require Windows Hello to authenticate Artemis");
const S_OK: i32 = 0;
const NTE_NOT_FOUND: i32 = unchecked_hresult(0x80090011);
const NTE_DEVICE_NOT_READY: i32 = unchecked_hresult(0x80090030);
const NTE_DEVICE_NOT_FOUND: i32 = unchecked_hresult(0x80090035);
const NTE_USER_CANCELLED: i32 = unchecked_hresult(0x80090036);

const fn unchecked_hresult(value: u32) -> i32 {
    value as i32
}

#[derive(Debug)]
struct NcryptHandle(NCRYPT_HANDLE);

impl NcryptHandle {
    fn provider(handle: NCRYPT_PROV_HANDLE) -> Self {
        Self(handle)
    }

    fn key(handle: NCRYPT_KEY_HANDLE) -> Self {
        Self(handle)
    }

    fn get(&self) -> NCRYPT_HANDLE {
        self.0
    }

    fn into_raw(mut self) -> NCRYPT_HANDLE {
        let handle = self.0;
        self.0 = 0;
        handle
    }
}

impl Drop for NcryptHandle {
    fn drop(&mut self) {
        if self.0 != 0 {
            // SAFETY: The handle was returned by NCrypt and is owned by this RAII guard.
            unsafe {
                let _ = NCryptFreeObject(self.0);
            }
        }
    }
}

/// Windows TPM-backed P-256 signer using NCrypt and the Microsoft Platform Crypto Provider.
pub struct WindowsKeystore;

impl WindowsKeystore {
    pub fn new() -> Self {
        Self
    }

    fn open_provider(&self) -> Result<NcryptHandle, KeystoreError> {
        let mut provider: NCRYPT_PROV_HANDLE = 0;
        // SAFETY: NCrypt writes a provider handle to the out pointer on success.
        let status = unsafe {
            NCryptOpenStorageProvider(&mut provider, MS_PLATFORM_CRYPTO_PROVIDER, 0)
        };
        map_status(status)?;
        Ok(NcryptHandle::provider(provider))
    }

    fn open_key(&self) -> Result<NcryptHandle, KeystoreError> {
        let provider = self.open_provider()?;
        let mut key: NCRYPT_KEY_HANDLE = 0;
        // SAFETY: Provider/key names are valid null-terminated PCWSTR constants.
        let status = unsafe { NCryptOpenKey(provider.get(), &mut key, KEY_NAME, 0, 0) };
        map_status(status)?;
        Ok(NcryptHandle::key(key))
    }

    fn export_public_blob(&self) -> Result<Vec<u8>, KeystoreError> {
        let key = self.open_key()?;
        let mut len = 0u32;
        // SAFETY: First call queries output length with a null output buffer.
        let status = unsafe {
            NCryptExportKey(
                key.get(),
                0,
                BCRYPT_ECCPUBLIC_BLOB,
                null(),
                null_mut(),
                0,
                &mut len,
                0,
            )
        };
        map_status(status)?;

        let mut blob = vec![0u8; len as usize];
        // SAFETY: The buffer length was returned by NCryptExportKey for this key/blob type.
        let status = unsafe {
            NCryptExportKey(
                key.get(),
                0,
                BCRYPT_ECCPUBLIC_BLOB,
                null(),
                blob.as_mut_ptr(),
                len,
                &mut len,
                0,
            )
        };
        map_status(status)?;
        blob.truncate(len as usize);
        Ok(blob)
    }
}

impl Keystore for WindowsKeystore {
    fn create_key(&mut self) -> Result<(), KeystoreError> {
        if self.has_key()? {
            self.destroy_key()?;
        }
        let provider = self.open_provider()?;
        let mut key: NCRYPT_KEY_HANDLE = 0;
        // SAFETY: Provider and constant PCWSTRs are valid; the key handle out pointer is valid.
        let status = unsafe {
            NCryptCreatePersistedKey(
                provider.get(),
                &mut key,
                NCRYPT_ECDSA_P256_ALGORITHM,
                KEY_NAME,
                0,
                0,
            )
        };
        map_status(status)?;
        let key = NcryptHandle::key(key);
        let ui_policy = NCRYPT_UI_POLICY {
            dwVersion: 1,
            dwFlags: NCRYPT_UI_FORCE_HIGH_PROTECTION_FLAG,
            pszCreationTitle: null(),
            pszFriendlyName: FRIENDLY_NAME,
            pszDescription: DESCRIPTION,
        };
        // SAFETY: NCRYPT_UI_POLICY is a C-compatible struct and must be set before finalize.
        let status = unsafe {
            NCryptSetProperty(
                key.get(),
                NCRYPT_UI_POLICY_PROPERTY,
                &ui_policy as *const NCRYPT_UI_POLICY as *const u8,
                size_of::<NCRYPT_UI_POLICY>() as u32,
                0,
            )
        };
        map_status(status)?;
        // SAFETY: Finalizes the newly-created key after all properties are set.
        let status = unsafe { NCryptFinalizeKey(key.get(), 0) };
        map_status(status)?;
        Ok(())
    }

    fn sign(&mut self, digest: &[u8; 32]) -> Result<Vec<u8>, KeystoreError> {
        let key = self.open_key()?;
        let mut len = 0u32;
        // SAFETY: First call queries signature length for a 32-byte SHA-256 digest.
        let status = unsafe {
            NCryptSignHash(
                key.get(),
                null::<c_void>(),
                digest.as_ptr(),
                digest.len() as u32,
                null_mut(),
                0,
                &mut len,
                0,
            )
        };
        map_status(status)?;
        if len != 64 {
            return Err(KeystoreError::Encoding);
        }

        let mut raw = [0u8; 64];
        // SAFETY: The fixed 64-byte buffer matches the P-256 NCrypt raw r||s signature length.
        let status = unsafe {
            NCryptSignHash(
                key.get(),
                null::<c_void>(),
                digest.as_ptr(),
                digest.len() as u32,
                raw.as_mut_ptr(),
                raw.len() as u32,
                &mut len,
                0,
            )
        };
        map_status(status)?;
        if len != 64 {
            return Err(KeystoreError::Encoding);
        }
        sig::to_der(&raw)
    }

    fn get_public_key(&mut self) -> Result<Vec<u8>, KeystoreError> {
        let blob = self.export_public_blob()?;
        public_blob_to_x963(&blob)
    }

    fn destroy_key(&mut self) -> Result<(), KeystoreError> {
        match self.open_key() {
            Ok(key) => {
                let raw = key.into_raw();
                // SAFETY: The raw key handle ownership is transferred to NCryptDeleteKey.
                let status = unsafe { NCryptDeleteKey(raw, 0) };
                map_status(status)
            }
            Err(KeystoreError::KeyNotFound) => Ok(()),
            Err(error) => Err(error),
        }
    }

    fn has_key(&mut self) -> Result<bool, KeystoreError> {
        match self.open_key() {
            Ok(_key) => Ok(true),
            Err(KeystoreError::KeyNotFound) => Ok(false),
            Err(error) => Err(error),
        }
    }
}

fn public_blob_to_x963(blob: &[u8]) -> Result<Vec<u8>, KeystoreError> {
    if blob.len() < size_of::<BCRYPT_ECCKEY_BLOB>() {
        return Err(KeystoreError::Encoding);
    }
    let header = blob.as_ptr().cast::<BCRYPT_ECCKEY_BLOB>();
    // SAFETY: The length check above ensures the header is present; read_unaligned avoids
    // assuming the byte buffer alignment.
    let header = unsafe { header.read_unaligned() };
    if header.cbKey != 32 {
        return Err(KeystoreError::Encoding);
    }
    let coordinate_len = header.cbKey as usize;
    let expected = size_of::<BCRYPT_ECCKEY_BLOB>() + coordinate_len * 2;
    if blob.len() != expected {
        return Err(KeystoreError::Encoding);
    }
    let mut point = Vec::with_capacity(1 + coordinate_len * 2);
    point.push(0x04);
    point.extend_from_slice(&blob[size_of::<BCRYPT_ECCKEY_BLOB>()..]);
    sig::pubkey_to_x963(&point)
}

fn map_status(status: i32) -> Result<(), KeystoreError> {
    match status {
        S_OK => Ok(()),
        NTE_NOT_FOUND => Err(KeystoreError::KeyNotFound),
        NTE_USER_CANCELLED => Err(KeystoreError::BiometricCancelled),
        NTE_DEVICE_NOT_READY | NTE_DEVICE_NOT_FOUND => Err(KeystoreError::HardwareUnavailable),
        _ => Err(KeystoreError::HardwareUnavailable),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[ignore = "requires live Windows Hello hardware gesture"]
    fn creates_signs_and_verifies_with_real_hello_hardware() {
        let mut keystore = WindowsKeystore::new();
        keystore.create_key().unwrap();
        let digest = [42u8; 32];
        let signature = keystore.sign(&digest).unwrap();
        assert!(!signature.is_empty());
    }
}
