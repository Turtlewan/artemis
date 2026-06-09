# ADR-010 — Client-app ↔ brain authentication (paired-device key)

- **Status:** Accepted
- **Date:** 2026-06-08
- **Deciders:** owner + planning
- **Relates:** ADR-005 (owner key broker — the phone `UnlockProof` P-256 SE-signed-keypair primitive + `RegisteredDeviceStore` + counter this reuses); M2-a (broker `pair`/verify side + `MockProver` this replaces with the real phone prover); M1-c (the FastAPI Gateway/API this extends — loopback-only, hard-coded owner scope today); ADR-002 (deployment — Tailscale private tunnel; native clients, no web UI); M7-b (`ReviewSurface` — the first authenticated consumer); overview.md §"Interaction surfaces" (chat app, biometric lock, remote via private tunnel).

## Context

The iPhone/iPad client reaches the brain over the **Tailscale private tunnel** (home = LAN). Three
pieces were deliberately deferred to "the client milestone":

1. **The real phone prover.** M2-a ships only the *verification* side of the vault unlock — a
   `SignedKeypairVerifier` over a P-256 assertion (`nonce ‖ scope ‖ counter`), a `RegisteredDeviceStore`,
   a `pair --device-id --pubkey` IPC command, and a `MockProver` test harness. The phone that produces
   *real* proofs (SE keypair + Face ID + the pairing UX) does not exist yet.
2. **A network-reachable authenticated brain surface.** M1-c's `/ask` + `/ask/stream` + Gateway bind
   **loopback (127.0.0.1)** and attach a **hard-coded** `OWNER_SCOPE`/`OWNER_PERSON_ID` (the single-owner
   stub). M1-c's own FLAG: *"replace the constant owner scope with real per-person resolution + the guest
   wall before any non-owner can reach a surface."*
3. **The owner-approval surface.** M7-b's `ReviewSurface` (list/explain/approve/reject) has no caller;
   IG1=B fixed the caller as the client-app Review screen over "its M2-authenticated connection."

This ADR decides **how the app authenticates to the brain over the tunnel**, which in turn fixes the
phasing of the prover and the shape of the brain-side surface.

## Decision

1. **One device key, two authorities.** The phone generates a **single** Secure-Enclave P-256 keypair at
   pairing. It is registered with **both**: (a) the **broker** — the vault-unlock authority (M2-a's
   `RegisteredDeviceStore`, unchanged), and (b) the **brain's app-auth device registry** — the API-session
   authority (new). One pairing handshake performs both registrations. The **broker stays minimal** (SE +
   DEK only); the brain's app-auth **never touches the SE or any DEK** — it only answers *"is this the
   registered device?"*. Two authorities, one key, clean separation of trusted bases.

2. **Challenge-response API sessions (the WebAuthn assertion model, reusing M2-a's primitive).** To open
   an API session: the brain issues a random **nonce** → the phone signs `(nonce ‖ context ‖ counter)` with
   the SE key **behind Face ID** → the brain verifies the signature against the registered public key and a
   **strictly-increasing per-device counter** → issues a **short-lived opaque session token** held in a
   server-side session store (instantly revocable). Same signature primitive + counter discipline as the
   broker's `UnlockProof`; a **distinct authority and nonce namespace** (an API-session nonce is never a
   vault nonce and vice-versa).

3. **Scope from the session, never from the client.** The Gateway resolves the owner scope from the
   **authenticated session** (replacing M1-c's hard-coded constant). No surface ever accepts a
   scope/person from a request parameter or body (the tenant-from-session invariant, apex-auth hard block
   #4). In M1 single-owner, the session maps to `OWNER_SCOPE`; the seam is now real so the future
   guest/multi-person wall drops in here without touching the Brain.

4. **Connect + unlock is one owner-initiated *gesture* — but session ≠ vault-unlock.** Opening the app →
   **one Face-ID prompt** drives **two distinct handshakes** behind that single biometric context: (a) the
   API-session challenge-response (signs `nonce ‖ "artemis-api-session" ‖ counter`) **and** (b) the vault
   unlock — the brain relays a broker-issued nonce to the phone, which signs the **vault** proof
   (`nonce ‖ scope ‖ counter`, M2-a's existing shape) and the brain submits it to unlock the scope for the
   broker's **session window** (M2-c idle/lock re-proof model). Two signatures over two domain-separated
   messages, one Face-ID gesture (the app reuses the `LAContext` within its reuse window). The
   brain **never pushes to the phone**; unlock is owner-initiated and time-boxed. Two independent lifetimes:
   the **API session** (longer-lived, opaque token) and the **vault unlock** (broker session window, shorter,
   idle-expiring). So a real state is **"Connected but vault-locked"** (API session valid, vault idle-locked) —
   in it, any endpoint that reads owner data **prompts a fresh Face-ID re-unlock**. This includes **both Chat**
   (memory/knowledge) **and Review**: recipes live on the M2 per-scope encrypted volume (M7-a1 / ADR-007 — a
   `touches-data`/`takes-action` recipe's instructions can encode sensitive structure), so listing/approving
   them needs the vault open. Only **Status** (broker `status` + the app-auth session) works on the API session
   alone — it *is* the lock/connection UI.

5. **Transport: extend the M1-c FastAPI app — no new server.** The same app additionally binds the
   **Tailscale interface** for the authenticated app surface; **loopback is retained** for the dev CLI. An
   app-auth dependency guards **every** app endpoint; only **pairing-bootstrap** and **health** are
   unauthenticated. Tailscale provides the encrypted path (home = LAN; remote allowed a beat slower per
   ADR-002).

6. **Session ≠ data access — the DEK is the data gate.** The API session is a **reachability/identity
   token only**; it grants **no** data access by itself. Owner data is gated by the **vault DEK**, which the
   broker zeroizes on idle/lock (M2-c). So an **idle vault-lock does NOT revoke the session** (this *is* the
   *Connected·Vault-locked* state) — it zeroizes the DEK, and any data endpoint then fails closed (423 →
   re-unlock). Sessions are revoked only on **explicit logout** and on **brain restart** (in-memory store).
   Consequence: a stolen session token without the phone can reach Status and *begin* an unlock, but cannot
   produce a vault proof (needs the SE key) → no data. **Storage** — brain-side: server-side in-memory
   session store; phone-side: session token in the **iOS keychain**, private key **non-exportable in the
   Secure Enclave**. **Tokens and keys are never logged** (apex-auth hard block #2).

## Consequences

- **The real unlock-prover is no longer optional for v1 — it *is* the auth mechanism.** This resolves the
  mock-vs-real phasing: the Swift app must ship the SE prover in v1. On-hardware SE behaviour (`.userPresence`,
  real signing) stays **gated on-hardware**, mirroring M2.
- **Pairing writes to two stores** (broker `pair` + brain app-auth registry). A half-completed pairing must
  be **detectable and re-runnable** → `pair` is **idempotent**; revoking a device removes it from **both**.
- **The brain app-auth registry is a new small persisted store** (`device_id → public_key, counter,
  paired_at`). It holds **public keys only** (not secret) and must be readable **before any vault unlock**
  (it authenticates the unlock itself) → it lives in the brain's identity/config dir, **integrity-sensitive,
  not confidential**. The counter it tracks is the **API-session** counter, separate from the broker's
  vault-unlock counter (two namespaces, one key).
- **Lost phone = re-pair + revoke the old device** — the same blast radius the unlock key already carries.
  Acceptable for single-owner; the registry supports N devices so a replacement is additive.
- **`overview.md` §Interaction surfaces gains an authenticated network API edge** — folded into the tracked
  consolidated overview refresh (status.md), not patched per-spec.

## Alternatives considered

- **Tailscale-only network trust** (on the tunnel = owner; no app credential) — *rejected*: coarse (any
  device on the tailnet gets full owner access), no per-device identity to revoke, weakens the future
  guest/multi-person wall, and makes the overview's "biometric lock" cosmetic.
- **Separate app login** (passkey/OAuth/password distinct from the unlock pairing) — *rejected*: redundant
  with the device key already required for unlock; two credential systems to maintain; more onboarding
  friction; OAuth/cloud-IdP dependency conflicts with the no-cloud-data posture.
- **Brain delegates API-session verification to the broker** (broker verifies *all* assertions) —
  *rejected*: overloads the deliberately minimal SE-only trusted base with a non-SE concern. The brain
  holding its own copy of the public key keeps the broker's attack surface minimal and lets session-only
  endpoints (Status) authenticate without involving the SE/DEK path at all.
