# Live bring-up runbook — pairing handshake + voice (Windows-host v1)

The two owner-run live tails that became exercisable on 2026-06-28, after
`client-pairing-screen`, `client-auth-windows-bringup` (proof-contract reconcile + Windows
unlock short-circuit), and `voice-ask-wiring` shipped. All code is committed; these steps are the
first real-hardware acceptance the build cannot run for itself. Run on *this* enrolled Windows box.

**In plain terms:** start the brain, open the client, and for the first time on real hardware prove
that (A) the device handshake actually connects the client to the brain end-to-end (it previously died
at `session/complete 401`), and (B) you can hold the mic, ask out loud, hear a spoken answer — and that
locking the vault mid-sentence cuts the voice off instantly.

> **⚠ The rule that bites everyone:** every Windows Hello / PIN prompt anchors to a **real terminal
> window**. Run the brain and unlock commands in a standalone **Windows Terminal / PowerShell** window
> you opened yourself — not an IDE pipe or an agent `!` runner, or Hello fails with
> `no console window for the Hello prompt`. **PIN counts as Hello** (the accepted ADR-025 dev-wall
> downgrade).

Convention: Python entry points run under `uv run <cmd>` from the repo root
(`C:\Users\User\artemis`); the client runs from `client/`.

---

## Step 0 — Pre-flight (once)

| Check | Command | Expected |
|-------|---------|----------|
| Deps synced | `uv sync --group agentic` | exit 0 (bare `uv sync` *removes* the agentic deps the brain imports) |
| Data root under AppData | inspect `config/.env.dev` → `ARTEMIS_DATA_ROOT` | a path under `%LOCALAPPDATA%` (e.g. `C:\Users\User\AppData\Local\Artemis`). The DPAPI `WindowsKeyProvider` refuses anything outside `%APPDATA%`/`%LOCALAPPDATA%` (`InsecureKeyStoreError`). |
| Hello or PIN enrolled | Settings → Accounts → Sign-in options | at least a **PIN** enrolled |
| Client toolchain | `cd client && npm run tauri info` | no missing-toolchain errors |
| Local model up (only if asking real questions) | `ollama list` | reachable |

---

## Part A — Live pair → connect → unlock handshake  *(client-pairing-live-handshake, D3 / CLIENT-auth Task 7 step 4b)*

The handshake that previously died at `session/complete 401`. The proof-contract reconciliation
(`client-auth-windows-bringup`) aligned both sides to the length-prefixed `b"session"` framing and
added the Windows unlock short-circuit, so this should now reach **connected/unlocked**.

**A1 — Start the brain** (terminal A, a real window):
```
uv run artemis-brain
```
- Serves on `http://127.0.0.1:8030` (loopback only).
- A **Hello/PIN prompt** appears at startup and unseals the owner-private vault.
- If this box reports Hello unavailable, fall back to
  `$env:ARTEMIS_REQUIRE_HELLO_UNLOCK="False"; uv run artemis-brain` — but that boots with owner-private
  scopes **locked** (connecting works; domain reads return 423).
- **Verify** (second window): `curl http://127.0.0.1:8030/healthz` → `200 {"status":"ok","slot":"dev"}`.

**A2 — Mint a pairing code** (loopback-only, 10-min TTL — mint immediately before pairing):
```
curl -s http://127.0.0.1:8030/app/admin/pair-code -X POST
```
Copy the 12-char `code` from the response.

**A3 — Launch the client** (terminal B):
```
cd client
npm run tauri dev
```
A Tauri window opens, auto-targets `127.0.0.1:8030`, and boots to the **pairing screen**.

**A4 — Pair.** Type the code into the pairing input and submit. The client runs
`auth_pair → auth_connect → auth_unlock`.
- ✅ **PASS** = the pairing screen unmounts and the command-map (`WorldShell`) appears. This proves the
  brain accepted the client's **DER ECDSA-P256** signature against its **X9.63 uncompressed-point**
  pubkey, *and* the reconciled length-prefixed `b"session"` session-proof framing now matches on both
  sides.
- ❌ **FAIL** = a signature/verify rejection. **Do not patch blind** — capture the brain log line from
  `_verify_pairing_signature()` (`src/artemis/api_app.py` ~L923) and route to planning as an encoding
  mismatch (suspect SPKI vs X9.63 on the pubkey, or raw-concat framing leaking back in).

**A5 — Record two secondary findings regardless of outcome:**
- **Hello modality** — biometric prompt vs **PIN-only**? PIN-only is the accepted dev-wall downgrade
  (production root of trust is the Mac Secure Enclave). Just note it.
- **Double-prompt** — did you see **two** Hello prompts (the `NCryptSignHash` length-query then sign)?
  If so, flag to collapse to a single 64-byte call.

---

## Part B — Voice real-audio bring-up  *(voice-ask-wiring, Task 8)*

Requires the brain (A1) running **co-located with a working mic + speaker** (audio is brain-side per
ADR-034) and the client connected (A4 passed). The `/app/ask/voice` route and the mic button are now
wired.

**B1.** With the client connected and the vault unlocked, press the global **Ask hotkey**
(⌥Space / Alt+Space) to open the Ask popup.

**B2.** **Hold the mic button, speak a short question, release.** Expected: the transcript drives the
brain; the answer renders as display text **and** plays as **spoken audio on the brain-host speaker**.

**B3 — The security test (the important half).** Start a question that yields a multi-sentence spoken
answer, then **lock the vault mid-answer** (`uv run artemis-unlock` flips state, or lock from the
client). Expected: **speech stops immediately** — no further sentences play. This proves the
per-sentence fail-closed vault recheck (`speak_overlay_answer` / `compose_speak_sink`).

- ✅ **PASS** = spoken output heard **and** mid-answer cutoff confirmed on real hardware.
- ❌ No audio → a missing sidecar/mic is logged and skipped by design (the brain still boots); check
  terminal A's startup log for the voice-construction `try/except` warning.

---

## What to record

Jot pass/fail into `docs/handoff/<today>.md` so planning can close the gated Tasks:
- **A** → closes CLIENT-auth **Task 7 (b)** / activation-runbook Step 4b (live DER conformance) +
  records Hello modality (4a) and the double-prompt finding.
- **B** → closes `voice-ask-wiring` **Task 8**.
- Any failure → route to planning with the captured brain log; do **not** hand-patch crypto/encoding.

Still gated after this (Mac Mini only): macOS Secure Enclave / Touch-ID legs and the broker-escrow path.

---

## Quick order-of-operations

```
0. uv sync --group agentic; check .env.dev data root; PIN enrolled
A1. uv run artemis-brain            → /healthz 200, vault unsealed   [terminal A, leave running]
A2. curl -X POST .../app/admin/pair-code  → copy 12-char code
A3. cd client && npm run tauri dev  → pairing screen                 [terminal B, leave running]
A4. enter code → pair               → command-map appears = PASS (live DER + session framing)
B1. ⌥Space → Ask popup
B2. hold mic, speak                 → spoken answer on brain-host speaker
B3. lock vault mid-answer           → speech stops immediately = PASS
```
