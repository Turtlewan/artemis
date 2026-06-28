#![cfg(windows)]

use std::ffi::c_void;
use std::mem::size_of;
use std::ptr::{null, null_mut};

use windows_sys::Win32::Security::Cryptography::{
    BCRYPT_ECCKEY_BLOB, BCRYPT_ECCPUBLIC_BLOB, MS_KEY_STORAGE_PROVIDER,
    NCRYPT_ECDSA_P256_ALGORITHM, NCRYPT_HANDLE, NCRYPT_KEY_HANDLE, NCRYPT_PROV_HANDLE,
    NCryptCreatePersistedKey, NCryptDeleteKey, NCryptExportKey, NCryptFinalizeKey, NCryptFreeObject,
    NCryptOpenKey, NCryptOpenStorageProvider, NCryptSignHash,
};
use windows_sys::core::w;

use crate::error::KeystoreError;
use crate::{Keystore, sig};

const KEY_NAME: windows_sys::core::PCWSTR = w!("ArtemisDeviceSigningKey");
const S_OK: i32 = 0;
const NTE_NOT_FOUND: i32 = unchecked_hresult(0x80090011);
// CNG providers (Platform Crypto Provider AND the software KSP) return NTE_BAD_KEYSET, not
// NTE_NOT_FOUND, when a persisted key has not been created yet — treat it as "key not found"
// so has_key() returns false and create_key() proceeds (first-pairing bootstrap).
const NTE_BAD_KEYSET: i32 = unchecked_hresult(0x80090016);
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

/// Windows P-256 device signer using NCrypt. DEV-TWIN: the device key lives in the software Key
/// Storage Provider (see `open_provider`); the hardware-bound, gesture-gated key is the Mac Secure
/// Enclave path (`macos.rs`, ADR-025).
pub struct WindowsKeystore;

impl WindowsKeystore {
    pub fn new() -> Self {
        Self
    }

    /// Open the device-key storage provider.
    ///
    /// DEV-TWIN (Windows dev box): uses the software Key Storage Provider. The TPM Platform
    /// Crypto Provider opens on this AMD fTPM box, but its key operations fail with NTE_BAD_KEYSET,
    /// so the Windows dev twin keeps the device key in software. The hardware-bound, gesture-gated
    /// device key is the Mac Secure Enclave's job in production (ADR-025; see macos.rs) — the
    /// software key here is the Windows-dev accommodation only, NOT the Mac/production custody.
    /// See docs/handoff/2026-06-28.md (CLIENT-auth Task 7).
    fn open_provider(&self) -> Result<NcryptHandle, KeystoreError> {
        let mut provider: NCRYPT_PROV_HANDLE = 0;
        // SAFETY: NCrypt writes a provider handle to the out pointer on success.
        let status =
            unsafe { NCryptOpenStorageProvider(&mut provider, MS_KEY_STORAGE_PROVIDER, 0) };
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
        // Software-KSP dev-twin key: no NCRYPT_UI_POLICY gesture gate (a software key can't offer
        // the hardware-bound high-protection guarantee anyway). The gesture-gated hardware key is
        // the Mac Secure Enclave path (macos.rs, ADR-025).
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
        NTE_NOT_FOUND | NTE_BAD_KEYSET => Err(KeystoreError::KeyNotFound),
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

    // Headless end-to-end proof of the software-KSP device key (no Hello gesture). Exercises the
    // NTE_BAD_KEYSET -> KeyNotFound bootstrap fix and verifies the DER signature against the
    // exported X9.63 public key over the prehashed digest — the same check the brain performs.
    #[test]
    fn software_ksp_roundtrip_create_sign_verify() {
        use p256::ecdsa::signature::hazmat::PrehashVerifier;
        use p256::ecdsa::{Signature as P256Signature, VerifyingKey};

        let mut keystore = WindowsKeystore::new();
        let _ = keystore.destroy_key();
        // A not-yet-created key must report false (not error) — the pairing bootstrap depends on it.
        assert!(!keystore
            .has_key()
            .expect("has_key on a missing key must not error"));

        keystore.create_key().expect("create_key on software KSP");
        assert!(keystore.has_key().expect("has_key after create"));

        let pub_x963 = keystore.get_public_key().expect("get_public_key");
        let digest = [42u8; 32];
        let der = keystore.sign(&digest).expect("sign");

        let verifying_key = VerifyingKey::from_sec1_bytes(&pub_x963).expect("parse public key");
        let signature = P256Signature::from_der(&der).expect("parse DER signature");
        verifying_key
            .verify_prehash(&digest, &signature)
            .expect("device signature verifies against the exported public key");

        keystore.destroy_key().expect("destroy_key");
        assert!(!keystore.has_key().expect("has_key after destroy"));
    }
}
