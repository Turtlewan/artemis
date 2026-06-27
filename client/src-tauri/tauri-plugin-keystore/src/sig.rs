use ecdsa::Signature;
use p256::NistP256;
use p256::elliptic_curve::sec1::{FromEncodedPoint, ToEncodedPoint};

use crate::error::KeystoreError;

/// Normalize a Windows NCrypt raw `r || s` P-256 signature into ASN.1 DER.
pub fn to_der(raw_rs: &[u8; 64]) -> Result<Vec<u8>, KeystoreError> {
    let signature =
        Signature::<NistP256>::from_bytes(raw_rs.into()).map_err(|_| KeystoreError::Encoding)?;
    Ok(signature.to_der().as_bytes().to_vec())
}

/// Validate and normalize an X9.63 uncompressed point.
pub fn pubkey_to_x963(point: &[u8]) -> Result<Vec<u8>, KeystoreError> {
    let encoded =
        p256::EncodedPoint::from_bytes(point).map_err(|_| KeystoreError::Encoding)?;
    let public_key =
        p256::PublicKey::from_encoded_point(&encoded).into_option().ok_or(KeystoreError::Encoding)?;
    Ok(public_key.to_encoded_point(false).as_bytes().to_vec())
}

#[cfg(test)]
mod tests {
    use p256::ecdsa::signature::{Signer, Verifier};
    use p256::ecdsa::{Signature as P256Signature, SigningKey, VerifyingKey};

    use super::*;

    #[test]
    fn raw_windows_signature_normalizes_to_der_and_verifies() {
        let signing_key = SigningKey::from_bytes((&[7u8; 32]).into()).unwrap();
        let verifying_key = VerifyingKey::from(&signing_key);
        let message = b"artemis-client-auth-known-vector";
        let raw_signature: P256Signature = signing_key.sign(message);
        let raw_bytes = raw_signature.to_bytes();
        let mut raw = [0u8; 64];
        raw.copy_from_slice(&raw_bytes);

        let der = to_der(&raw).unwrap();
        let parsed = P256Signature::from_der(&der).unwrap();

        verifying_key.verify(message, &parsed).unwrap();
    }

    #[test]
    fn x963_public_key_round_trips() {
        let signing_key = SigningKey::from_bytes((&[9u8; 32]).into()).unwrap();
        let verifying_key = VerifyingKey::from(&signing_key);
        let point = verifying_key.to_encoded_point(false);

        let normalized = pubkey_to_x963(point.as_bytes()).unwrap();
        let decoded = p256::EncodedPoint::from_bytes(&normalized).unwrap();
        let round_trip = p256::PublicKey::from_encoded_point(&decoded).unwrap();

        assert_eq!(
            round_trip.to_encoded_point(false).as_bytes(),
            point.as_bytes()
        );
    }
}
