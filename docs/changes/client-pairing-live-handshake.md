---
status: ready
weight: light
cross_model_review: false
coder_effort: manual
---

# client-pairing-live-handshake — first live pair→connect→unlock verification (GATED, owner-run)

## Identity
Owner-run **verification procedure** (not a code spec) that exercises the never-run live
`auth_pair → auth_connect → auth_unlock` + DER-signature handshake against a real `artemis-brain`
for the first time, proving the client emits a **DER ECDSA-P256** signature and an **X9.63
uncompressed-point** pubkey (NOT SPKI). Executes CLIENT-auth **Task 7** / activation-runbook
**Step 4b**. Like the activation-runbook tails and `client-live-overlay` Task 5, this is a manual
gated acceptance recorded in the build handoff — no code changes unless the encoding fork bites.
Design + risk: `docs/findings/client-pairing-ui-design-brief.md` §4; prior work:
`docs/changes/done/CLIENT-auth.md` (Task 7), `docs/handoff/2026-06-27.md`, `2026-06-28.md`.

## Prerequisites
- `client-pairing-screen` built and running in the dev client (gateway visible on first launch).
- A live brain reachable: `uv run artemis-brain` on `127.0.0.1:{BRAIN_PORT}` (per `win-brain-runtime`).
- The enrolled Windows dev box; accept the ADR-025 dev-wall PIN fallback if Windows Hello biometric
  is unavailable (dev box reports `DEVICE_NOT_PRESENT` under the harness — see §5 of the brief).

## Procedure
1. **Mint a pairing code on the brain host** (loopback-only endpoint, 10-min TTL):
   ```bash
   curl -s http://127.0.0.1:${BRAIN_PORT}/app/admin/pair-code -X POST | jq -r .code
   ```
   Read the 12-char URL-safe code from stdout. Mint *immediately before* pairing (TTL = 600s).
2. **Pair from the client gateway** — type the code into the `PairingScreen` input and submit. The
   client runs `auth_pair → auth_connect → auth_unlock`; on success the gateway unmounts and the
   command-map (`WorldShell`) appears.
3. **Confirm the success path = brain accepted the DER signature.** Reaching connected/unlocked means
   the brain's `SignedKeypairVerifier` (CLIENT-a) accepted the client's signature. If pairing fails,
   capture the brain log line from `_verify_pairing_signature()` (`src/artemis/api_app.py` ~L923).

## What to verify / record (the encoding fork — §4 of the brief)
- ✅ **PASS** = pair→connect→unlock completes against the live brain (gateway → map). This proves the
  client exported its pubkey as **X9.63 uncompressed point, base64** (`to_encoded_point(false)`) and
  normalised the signature to **DER** (`ecdsa::Signature::<NistP256>::to_der()`), matching the brain's
  `ec.EllipticCurvePublicKey.from_encoded_point` decode and the `pairing_message` layout
  (`len(code)·2B ‖ code ‖ device_id`) in `client/src-tauri/src/auth.rs`.
- ❌ **FAIL** = a signature/verify rejection → capture the brain log and route to planning as an
  **encoding mismatch** (suspect SPKI-DER leaking back in, or X9.63 vs SPKI on the pubkey). Do NOT
  patch blind — the CLIENT-auth amendment already dropped the `spki` crate; this run is the proof.
- **Secondary Windows finding (record regardless of pass/fail):** confirm whether the Windows path
  fires a **double Windows Hello prompt** (the `NCryptSignHash` length-query then sign issues two
  `NCryptSignHash` calls — 2026-06-27 Opus review). If two prompts appear, flag to collapse to a
  single 64-byte call. Also confirm the real HRESULT for `MS_PLATFORM_CRYPTO_PROVIDER` — expected
  `NTE_NOT_FOUND`, but the dev box reports `DEVICE_NOT_PRESENT`.

## Acceptance criteria (manual)
1. Pairing code minted via `POST /app/admin/pair-code` and consumed by one pairing attempt. → curl + UI.
2. Handshake outcome recorded as PASS/FAIL in the session handoff, with the brain log captured on FAIL.
3. Double-Hello-prompt behaviour (one prompt vs two) and the observed `MS_PLATFORM_CRYPTO_PROVIDER`
   HRESULT recorded as findings.
4. On PASS: note that DER/X9.63 conformance is proven end-to-end (closes CLIENT-auth Task 7 /
   runbook Step 4b for Windows; SE/Touch-ID/broker-escrow legs remain Mac-gated).

## Commands to run
```bash
# brain host (one terminal)
uv run artemis-brain                                    # :{BRAIN_PORT}
curl -s http://127.0.0.1:${BRAIN_PORT}/app/admin/pair-code -X POST | jq -r .code
# client (dev) — launch, then pair via the gateway UI
cd client && npm run tauri dev
# on FAIL, read the brain log for the _verify_pairing_signature rejection line
```
