# Owner-manual activation runbook (Windows-host v1)

Everything the build **cannot** do for itself — the live, interactive, hardware-gated tails left after
the full Tauri client runway was built (2026-06-27). All code is committed; these steps are **owner-run**
on *this* enrolled Windows box. Walk them in order — each step depends on the one before it.

Read tonight; run when you have time at the keyboard. Record pass/fail for each gated step in the next
build handoff (`docs/handoff/YYYY-MM-DD.md`) so the gated spec Tasks can be closed.

> **Convention:** all Python entry points run under `uv run <cmd>` from the repo root
> (`C:\Users\User\artemis`). The client runs from `client/`.

---

## Step 0 — Pre-flight (5 min, do once)

Confirm the environment before touching anything live.

| Check | Command | Expected |
|-------|---------|----------|
| Windows Hello enrolled | Settings → Accounts → Sign-in options → **Windows Hello** (face/fingerprint/PIN) | At least one biometric enrolled. **⚠ The build box has historically reported `DEVICE_NOT_PRESENT`** — if Hello isn't really enrolled, Steps 2 & 4a fall back to PIN (accepted dev-wall downgrade, ADR-025), and **Step 1 needs the `ARTEMIS_REQUIRE_HELLO_UNLOCK=False` fallback** (see Step 1). |
| Python deps synced | `uv sync --group agentic` | exit 0. **Use `--group agentic`** — bare `uv sync` *uninstalls* the agentic group (openhands-sdk + ~141 deps), which the brain imports. |
| Owner-private data root (Windows) | `config/.env.dev` → `ARTEMIS_DATA_ROOT` must be under `%LOCALAPPDATA%` (e.g. `C:\Users\User\AppData\Local\Artemis`) | Path under AppData. The DPAPI `WindowsKeyProvider` **refuses** a key store outside `%APPDATA%`/`%LOCALAPPDATA%` (`InsecureKeyStoreError`). The original corpus default `/opt/artemis` fails this guard on Windows. _(Also fix the stale Mac `ARTEMIS_WORKTREE_ROOT` while here.)_ |
| MSVC toolchain (client) | `cd client && npm run tauri info` | no missing-toolchain errors |
| Local model server | `ollama list` | reachable (needed for Step 5 / Google) |

---

## Step 1 — Run the brain  *(win-brain-runtime ⑤a — confirm live)*

The brain is the thing everything else connects to. This also starts the proactive heartbeat.

```
uv run artemis-brain
```

- Serves on **http://127.0.0.1:8030** (loopback only).
- **Verify:** in a second terminal → `curl http://127.0.0.1:8030/healthz` → **200** (`{"status":"ok","slot":"dev"}`).
- The startup log should show the **proactive heartbeat starting**.
- Leave this running in its own terminal for Steps 4–5.

**⚠ Hello-at-startup gate.** The brain calls `win_kp.unlock()` at startup with `require_hello_unlock=True` (default). Two outcomes:
- **Hello available** → a gesture prompt appears; authenticate → brain runs with owner-private scopes **UNLOCKED** (full memory/finance). This is the intended path.
- **Hello unavailable** (this box's `DEVICE_NOT_PRESENT`) → startup **fails closed** (`UnlockUnavailableError`). Dev fallback:
  ```
  $env:ARTEMIS_REQUIRE_HELLO_UNLOCK="False"; uv run artemis-brain
  ```
  Brain boots with owner-private scopes **LOCKED** — `/healthz`, heartbeat, and non-private paths work; memory/finance are disabled (`compose_brain: memory unavailable` is expected, not a crash). `slot=prod` hard-blocks this flag.

**Records:** win-brain-runtime Task 1 (live `/healthz` 200 on-box — note whether Hello unlocked or you used the dev fallback).

> **Smoke-tested 2026-06-28:** brain boots → `/healthz` 200 via the dev fallback (Hello reported unavailable in a non-interactive process — confirm interactively at Step 2). Two activation blockers were fixed first: the `artemis-brain` entry point (was misrouted to the unpackaged `scripts/run_brain.py`) and `ARTEMIS_DATA_ROOT` (was the Mac `/opt/artemis`).

---

## Step 2 — Live Windows Hello unlock  *(m2-win-b — `artemis-unlock`)*

Proves the owner-private vault unlocks behind a real Hello gesture. This is the gate every owner-private
CLI (incl. Google auth) sits behind.

> **⚠ Run in a REAL terminal window.** Windows Hello anchors its prompt to the console window
> (`GetConsoleWindow()` must be non-zero). A windowless/piped host — e.g. an agent's in-session
> `!` runner, a CI pipe, or some IDE-integrated terminals without a conhost — fails with
> `UnlockUnavailableError: no console window for the Hello prompt`. Open a standalone Windows
> Terminal / PowerShell window and run from `C:\Users\User\artemis`. **Applies to every Hello-gated
> command:** `artemis-unlock`, plain `artemis-brain` (startup unlock), `artemis-google-auth login`.
>
> **PIN counts as Hello.** Enrolling a Windows Hello *PIN* (Settings → Accounts → Sign-in options →
> PIN) flips `CheckAvailabilityAsync` to Available — the box does not need a fingerprint/face. The
> live gesture is then a PIN tap (the accepted ADR-025 dev-wall downgrade).

```
uv run artemis-unlock
```

- A **Windows Hello prompt appears** (console-window HWND) — provide your gesture.
- On success: the CLI provisions + verifies and reports OK (**no DEK is ever printed**).
- On a denied/cancelled gesture: it raises `UnlockDeniedError` and unseals **nothing** (fail-closed).
- If Hello is unavailable on the box: `UnlockUnavailableError` — see the Step 0 ⚠ note.

**Records:** m2-win-b — live gesture path (the unit tests mock this; this is the real-hardware confirm).

---

## Step 3 — Build + launch the client  *(prereq for Steps 4–5)*

> **✅ UNBLOCKED 2026-06-28 (later same day) — pairing UI built + proof contract reconciled.**
> `client-pairing-screen` wired the gateway/pairing surface into `App.tsx`, and
> `client-auth-windows-bringup` reconciled the client↔brain session-proof framing (length-prefixed
> `b"session"`) and added the Windows unlock short-circuit — the two gaps that had stalled the live
> handshake at `session/complete 401`. Steps 3–5 are now exercisable. **For the focused
> pairing + voice walkthrough, see `docs/technical/setup/live-bring-up-runbook.md`** (Part A = the
> live `auth_pair`/`auth_connect`/`auth_unlock` handshake = Step 4b below; Part B = voice real-audio
> bring-up from `voice-ask-wiring`).

With the brain running (Step 1):

```
cd client
npm run tauri dev
```

- A live Tauri window opens; it **auto-targets the local brain** at `127.0.0.1:8030` (no manual config).
- Connection-gating is by design — the window stays gated until paired/connected (Step 4).

---

## Step 4 — CLIENT-auth real-hardware spikes  *(CLIENT-auth Task 7 — GATED)*

Three things to confirm with the live brain (Step 1) + client (Step 3). Record each pass/fail.

**4a — Hello-vs-PIN modality from Tauri.**
Trigger a pairing/connect from the client (enter the pairing code in the client's pairing screen). A
**biometric** Hello prompt should surface from the Tauri process (via `NCRYPT_UI_FORCE_HIGH_PROTECTION`),
**not** PIN-only.
- ✅ Biometric prompt → pass.
- ⚠ PIN-only prompt → the accepted **dev-wall downgrade** (ADR-025); record it — production root of
  trust is the Mac Secure Enclave, not a PIN.
- Note: the signer may fire **two** Hello prompts on this path (length-query + sign) — a known flag; note
  if you see it.

**4b — Signature-encoding conformance (the important one).**
Complete pair → connect against the **live brain**. The client normalizes its P-256 signature to **DER**
and exports its pubkey as **X9.63 uncompressed point** (not SPKI-DER). A successful handshake = the brain's
`SignedKeypairVerifier` (CLIENT-a) accepted the client DER signature.
- ✅ Handshake reaches **connected/unlocked** → DER conformance confirmed.
- ❌ Handshake fails → capture the brain log; route to planning (encoding mismatch).

**4c — macOS Secure Enclave / Touch ID** — **N/A on Windows.** Gated for the Mac Mini.

**Records:** CLIENT-auth Task 7 (a) Hello modality, (b) live DER conformance, (c) deferred to Mac.

---

## Step 5 — Game-overlay Ask demo  *(client-live-overlay Task 5 — the headline demo)*

The payoff. Brain running (Step 1) + client paired/connected (Step 4):

1. Launch a game in **borderless / windowed-fullscreen** mode (exclusive-fullscreen may not show the
   overlay — a Windows limitation; if so, record that behaviour and use borderless).
2. Press the global **Ask hotkey** (⌥Space / Alt+Space) — the floating Ask window appears over the game.
3. Type a question → it round-trips `invoke("ask")` → Rust `ask` → brain `POST /app/ask` → you get the
   **brain's real answer** over the game.

**Records:** client-live-overlay Task 5 — pass/fail + the exclusive-fullscreen behaviour note.

---

## Step 6 — Google spoke go-live  *(separate runbook — now unblocked)*

Take Gmail/Calendar from fake-tested to **live**, then exercise the email-rules reactions harness. Its
prerequisites (m2-win-b Hello, win-owner-cli-keyprovider) are now built, so it's ready to run.

→ **Follow `docs/technical/setup/google-go-live-runbook.md` in full** (Google Cloud project → OAuth
consent → desktop credentials → `GOOGLE_OAUTH_CLIENT_ID/SECRET` env → `artemis-google-auth login`
behind a Hello gesture → `ollama pull qwen3:4b` → `artemis-dev-email-rules --once` in observe mode).

**Use a dedicated test Google account for the first run.** Reactions ship **dormant** (`observe`) — the
go-live flip to `reactions_mode = live` is a deliberate, later, manual choice.

---

## Quick order-of-operations recap

```
0. Pre-flight                  (Hello enrolled? uv sync? tauri info? ollama?)
1. uv run artemis-brain        → /healthz 200, heartbeat up   [terminal A, leave running]
2. uv run artemis-unlock       → live Hello gesture unseals    [m2-win-b]
3. cd client && npm run tauri dev                              [terminal B, leave running]
4. pair/connect from client    → 4a Hello modality · 4b live DER handshake   [CLIENT-auth T7]
5. borderless game + ⌥Space    → live brain answer over the game             [overlay T5]
6. google-go-live-runbook.md   → OAuth + artemis-dev-email-rules --once       [observe]
```

After running: jot pass/fail per gated step into `docs/handoff/<today>.md` so planning can close the
gated Tasks (CLIENT-auth T7, overlay T5) and advance the Google harness.
