# Design Brief — Pairing UI for the Artemis Tauri client

**Status:** design brief (not a spec). Author: research pass 2026-06-28.
**Problem owner:** the client boots to a permanent blank screen because no pairing surface exists.

---

## 0. The problem (verified 2026-06-28)

- The connection store (`client/src/state/connection.ts`) initialises to `state: "unpaired"` and **nothing in the running app ever advances it.** No boot code calls `pairDevice()`, `app_status`, or any `connectionStore.on*` transition. (`grep` confirms: `pairDevice` / `onPaired` / `onConnected` are referenced only by tests.)
- `client/src/App.tsx` line 131: `if (!connected) return null;` where `connected = state === "connectedLocked" || state === "unlocked"`. So in `unpaired` (and `disconnected`) the app renders **nothing**.
- `client/src/auth/pairing.ts` (`pairDevice`) and `client/src/auth/recovery.ts` (`recoverWithPassphrase`) are fully built and tested but **never mounted** — no component imports them.

Net: first launch = blank window, no way to pair. This brief specifies the gateway screen that fills the `!connected` branch and exercises the (never-run) live handshake.

---

## 1. Where the pairing code comes from — BUILT (not a gap)

Confirmed brain-side in `src/artemis/api_app.py`.

- **Generator:** `PairingCodeStore.mint()` → `secrets.token_urlsafe(9)` → a **12-char URL-safe base64 token** (alphanumeric + `-` `_`). TTL = **600s / 10 min** (`PAIRING_CODE_TTL_SECONDS`). Single outstanding code; `mint()` invalidates any prior code; single-use via `consume()`. Brain stores only the SHA-256 hash, never the raw code.
- **Issue mechanism:** loopback-only endpoint `POST /admin/pair-code` (mounted under the `/app` router → full path **`/app/admin/pair-code`**), rejects any non-`127.0.0.1`/`::1` caller with 403, returns `{ "code": "<raw>" }`.
- **How the owner gets it (per CLIENT-b spec):**
  ```bash
  curl -s http://127.0.0.1:${BRAIN_PORT}/app/admin/pair-code -X POST | jq -r .code
  ```
  The owner runs this on the brain host, reads the 12-char code from stdout, and types it into the client.

**Verification handler:** `_verify_pairing_signature()` (api_app.py ~L923) decodes the device pubkey via `ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), …)` (X9.63 uncompressed point, base64) and verifies the DER ECDSA-P256-SHA256 signature over `len(code)·2B ‖ code ‖ device_id`. This exactly matches the client's `pairing_message` layout in `client/src-tauri/src/auth.rs`.

**UX implication:** the pairing screen must tell the owner *where the code comes from* — show the exact curl command (or, longer-term, a friendlier "run this on the brain" hint). Today there is **no in-product surfacing** of the code on the brain (no startup print, no QR). That is a minor onboarding gap, not a blocker: the curl path works. Flag for planning: consider printing the code on `artemis-brain` startup or a `just pair-code` helper so the owner isn't hand-rolling curl. The 10-min TTL means the owner should mint *then* pair promptly.

---

## 2. The pairing screen (the `!connected` gateway)

A distinct **pre-connect gateway screen** — same liquid-glass "Holo Tactical" visual system as the map (so it feels like Artemis), but a single centred panel, not the pannable command-map.

### Aesthetic (reuse existing tokens — do NOT hard-code a palette)
From `client/src/theme/tokens.css` + `AmbientProvider`:
- Wrap in the existing `AmbientProvider` + `PhotoBackground` (App.tsx already mounts both above `WorldShell`) so the seasonal `--bg`/`--p`/`--a` palette and decorative photo are live behind the gateway.
- Panel = `.glass` (radius 20, `backdrop-filter: blur(26px)`, `--hair` border, `--p` glow). Optional `.grid-mask` tactical grid behind it.
- Brand mark: the arc-reactor ringed circle stroked in `--p` with soft drop-glow (per design-brief.md), centred above the title.
- Type: Space Grotesk for the title/labels, Inter for body. Text `--text`, hints `--muted`.
- Code input: `.caret-primary` blinking caret + `.glow-primary` focus glow.

### States rendered (driven by `connection.state` + local component state)
1. **`unpaired` — Pair this device** (primary state):
   - Single text input for the pairing code (autofocus, `autocomplete=off`, `spellcheck=false`, monospace; the code is URL-safe base64 so allow letters/digits/`-`/`_`, ~12 chars — do not force digits-only).
   - A short hint: "Get a code on your brain: `POST /app/admin/pair-code` (valid 10 min)" with the curl one-liner.
   - **Submit → `pairDevice(code)`** (the existing `client/src/auth/pairing.ts`, which runs `auth_pair → auth_connect → auth_unlock` and advances the store through `onPaired/onConnected/onUnlocked`).
   - A secondary "Recover with passphrase" affordance → expands a passphrase field → `recoverWithPassphrase()` (`auth/recovery.ts`, calls `auth_recover`). Note: on the Windows dev box `auth_recover` is a no-op stub (broker escrow is Mac-gated, see auth.rs DEV-WALL) — the field clears its ref but does not actually restore a DEK. Keep the path wired but set expectations.
2. **In-flight — Pairing… / Connecting… / Unlocking…**: disable the form, show a calm pulse on the brand mark. (`pairDevice` runs all three invokes in sequence; a single "Connecting…" affordance is acceptable, or map sub-steps if we add progress callbacks later.)
3. **`disconnected`** (was paired, key exists, tunnel down): show "Reconnecting…" with a **Connect** retry that runs `auth_connect → auth_unlock` (without re-pairing). Optional for v1 — can fold into the same panel.
4. **Error feedback** — map the four `PairingError.kind` values (from `toPairingError`) to plain-English, non-leaky messages:
   - `wrongOrExpiredCode` → "That code didn't work or has expired. Mint a new one and try again." (covers brain 400/401/403/404/410 + `pairingRejected`).
   - `offTunnel` → "Can't reach your brain. Check the tunnel/connection." (network + `hardwareUnavailable`).
   - `biometricCancelled` → "Biometric check was cancelled. Try again." (Windows Hello / SE prompt dismissed).
   - `network` → "Something went wrong reaching your brain. Try again."
   - On error, store stays `unpaired` (verified: `pairDevice` does not advance on throw), so the form re-enables for retry. Surface errors via `role="alert"` / `aria-live`.

### Accessibility / behaviour
- Labelled form, `aria-live` status region (mirror the `StatusDetail`/`screen-status` pattern).
- Enter submits; respect `prefers-reduced-motion` (AmbientProvider already does for palette).
- Never render the raw code back or log it; never echo the passphrase (recovery.ts already zeroes its ref — keep the input controlled and clear on unmount).

---

## 3. Wiring — exactly where App.tsx branches

Today (`App.tsx`):
```tsx
function WorldShell() {
  const connection = useConnection();
  const connected = connection.state === "connectedLocked" || connection.state === "unlocked";
  ...
  if (!connected) return null;   // ← line 131: blank screen
  return ( <main className="artemis-shell"> … </main> );
}
```

Change: replace the `null` with the gateway screen. Two clean options:

**Option A (minimal, recommended):** at line 131, `if (!connected) return <PairingScreen state={connection.state} />;`. Keep `AmbientProvider`/`PhotoBackground` where they already are (in `App`, above `WorldShell`) so the gateway inherits ambient + photo with no extra wiring.

**Option B:** branch one level up in `App()` — render `<PairingScreen/>` vs `<WorldShell/>` based on `useConnection()`. Cleaner separation but moves the `useConnection` read up; A is fewer moving parts.

**Transitions (already implemented in the store — no new state machine needed):**
- `pairDevice()` success drives `unpaired → disconnected → connectedLocked → unlocked`; on reaching `unlocked`, `connected` flips true and `WorldShell` mounts the map automatically (the gateway unmounts). No manual navigation.
- `disconnected` (e.g. revoke→re-pair, or a future boot `app_status` probe) also renders the gateway (since `!connected`), so the same component covers reconnect.
- Lock/sign-out from inside the app already call `onLocked`/`onRevoked`; `onRevoked` → `unpaired` → gateway reappears. So the gateway is the single home for every `!connected` state — no extra routing.

**New file:** `client/src/auth/PairingScreen.tsx` (+ test + a small CSS block or reuse of `.glass`/screen classes). All five Tauri commands are already registered in `client/src-tauri/src/lib.rs` (`auth_pair/connect/unlock/recover`), so no Rust changes are required for the UI itself.

**Optional boot probe (separate, smaller concern):** there is currently no startup call to reconcile state with the brain. A future enhancement: on mount, call `app_status` and, if the device is already paired/connected, drive `onConnected`/`onUnlocked` to skip the gateway. Not required to fix the blank screen; note as a follow-up.

---

## 4. The live-handshake risk (never run — the real reason this is gated)

Wiring the UI **exercises the `auth_pair → auth_connect → auth_unlock` + DER-signature handshake against the live brain for the first time** (CLIENT-auth **Task 7** / activation-runbook **Step 4b**). It has only ever passed against `wiremock`/`FakeKeystore` in `auth.rs` tests.

What to verify when first run live (Step 4b — "the important one"):
- Complete pair → connect → unlock against a live `uv run artemis-brain`. Success = handshake reaches **connected/unlocked**, which means the brain's `SignedKeypairVerifier` (CLIENT-a) **accepted the client's DER signature**.
- ❌ failure → capture the brain log, route to planning as an **encoding mismatch**.

**The encoding fork to watch (X9.63 vs SPKI):** the client plugin must export its pubkey as **X9.63 uncompressed point, base64** (`p256::PublicKey::to_encoded_point(false)`) and normalise its signature to **DER** (`ecdsa::Signature::<NistP256>::to_der()`) — **NOT SPKI-DER**. The brain registry decodes via `ec.EllipticCurvePublicKey.from_encoded_point` (uncompressed) and the M2-a broker `pair --pubkey` expects X9.63; SPKI-DER would break both. The CLIENT-auth amendment already dropped the `spki` crate and confirmed this against live brain code — but it has not been *executed* end-to-end, so Step 4b is the proof.
- Secondary Windows risk (from the 2026-06-27 Opus review): the Windows path issues a **double `NCryptSignHash`** (length-query then sign) which may fire **two Windows Hello prompts** — confirm/collapse to a single 64-byte call. Also confirm the real `NTE_NOT_FOUND` HRESULT for `MS_PLATFORM_CRYPTO_PROVIDER` (dev box reports `DEVICE_NOT_PRESENT`).

---

## 5. Windows-dev vs Mac-gated coverage

**Testable now on the Windows dev box:**
- The entire `PairingScreen` React component: rendering per state, submit→`pairDevice`, all four `PairingError` mappings, recovery field — via `vitest` with mocked `invoke` (the existing `pairing.test.ts` already mocks `@tauri-apps/api/core`).
- The Rust auth orchestration against `wiremock` + `FakeKeystore` (already green: 12 cargo tests, 60 vitest).
- The live handshake against a real local brain **provided** the TPM/NCrypt key path is reachable. The dev box currently reports `DEVICE_NOT_PRESENT` under the harness and has no console window — the live Hello gesture needs a real terminal (`ARTEMIS_HELLO_MANUAL=1` path), so the *biometric* leg may degrade to PIN (the accepted ADR-025 dev-wall downgrade) or be deferred.

**Mac-gated (cannot verify on Windows):**
- Secure Enclave key path (`macos.rs` is a `HardwareUnavailable` stub; production is `#[cfg(target_os="macos")]`).
- Touch ID prompt from a Tauri/Rust process; SE entitlements/code-signing (Task 7c).
- The real broker escrow relay behind `auth_recover` (Argon2id-wrapped DEK) — dev uses a fake broker; the recovery field is wired but the DEK restore is Mac-gated.

So: **build + unit-test the screen fully on Windows now; run Step 4b live on Windows to prove DER conformance (PIN fallback acceptable); defer SE/Touch-ID/broker-escrow legs to the Mac.**

---

## 6. Suggested spec breakdown (rough — not specs)

1. **`client-pairing-screen`** — new `client/src/auth/PairingScreen.tsx` + styles + `PairingScreen.test.tsx`; render-per-state, submit→`pairDevice`, the four error mappings, recovery-passphrase sub-field. (~2-3 files, pure frontend, fully Windows-testable.)
2. **`client-pairing-wiring`** — the `App.tsx` branch (`!connected → <PairingScreen/>`) + connecting/disconnected affordance; keep AmbientProvider/PhotoBackground placement. Small, can merge into #1 if kept ≤3 files.
3. **`client-pairing-live-handshake` (verification, gated)** — execute CLIENT-auth Task 7 / runbook Step 4b against a live brain on the enrolled Windows box: mint a code, pair→connect→unlock, confirm DER/X9.63 conformance, capture pass/fail in the handoff; record the double-Hello-prompt finding. No code unless the encoding fork bites.
4. **(optional) `brain-paircode-surfacing`** — print the pair code on `artemis-brain` startup or add a `just pair-code` helper so the owner isn't hand-rolling curl. Onboarding nicety, brain-side, decoupled.
5. **(optional, follow-up) `client-boot-status-probe`** — on mount call `app_status` to skip the gateway when already paired/connected.

---

### Key file pointers
- Blank-screen gate: `client/src/App.tsx:131`
- State machine: `client/src/state/connection.ts`
- Existing (unmounted) auth logic: `client/src/auth/pairing.ts`, `client/src/auth/recovery.ts`
- Rust commands (registered): `client/src-tauri/src/auth.rs`, `client/src-tauri/src/gateway.rs`, `client/src-tauri/src/lib.rs:47-67`
- Brain pairing + code mint + verify: `src/artemis/api_app.py` (`/app/pair`, `/app/admin/pair-code`, `_verify_pairing_signature`)
- Aesthetic tokens: `client/src/theme/tokens.css`, `AmbientProvider.tsx`, `PhotoBackground.tsx`; `docs/technical/architecture/design-brief.md`
- Gated handshake: `docs/changes/done/CLIENT-auth.md` (Task 7, Step 4b), `docs/handoff/2026-06-27.md`, `docs/handoff/2026-06-28.md`
