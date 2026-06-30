# v1 Brain HTTP API Inventory

_Recovered from git tag `archive/v1` (source deleted in the v2 rebuild). Date: 2026-06-30._

This is a complete inventory of the HTTP API the v1 Artemis brain (FastAPI/uvicorn) exposed to the Tauri client. Source read via `git show archive/v1:<path>` — the tag was not checked out.

## Source modules (archive/v1)

| Path | Role |
| --- | --- |
| `src/artemis/main.py` | FastAPI `app`, lifespan composition, mounts routers, health probes |
| `src/artemis/run_brain.py` | uvicorn launcher |
| `src/artemis/api.py` | `m1c_router` — unauthenticated `/ask`, `/ask/stream` (legacy M1-c surface) |
| `src/artemis/api_app.py` | `app_router` (prefix `/app`) — the authenticated client surface (pairing, session, unlock, data, chat, voice) |
| `src/artemis/identity/app_auth.py` | Device registry, challenge/session stores, `AppAuth`, `require_session` dependency |
| `src/artemis/gateway.py` | `Gateway` — scope-attaching front door to the Brain |
| `src/artemis/voice/push_to_talk.py` | `PushToTalkCapture`, `overlay_voice_turn` (voice Ask) |

## Server startup

- **Launcher:** `run_brain.py` → `uvicorn.run("artemis.main:app", host="127.0.0.1", port=settings.brain_port, reload=False)`.
- **Bind:** loopback `127.0.0.1` only.
- **Port:** `settings.brain_port`, default **8030** (configurable, range 1024–65535). Related ports: mlx 8040, ntfy 8050, audio sidecar 8060.
- **Workers:** single uvicorn worker (the `PairingCodeStore` and rate limiter comment explicitly rely on single-worker in-memory state; no cross-process/thread locking).
- **App assembly:** `FastAPI(lifespan=lifespan)` mounts `m1c_router` (legacy `/ask`) and `app_router` (prefix `/app`). Plus two bare health probes.
- **Lifespan composition** builds and stashes on `app.state`: `gateway` (Gateway over composed brain), `app_auth` (AppAuth), `key_provider` (WindowsKeyProvider on win32 with Hello unlock provision/unlock; BrokerKeyProvider over a unix socket elsewhere), `review_surface`, `action_staging` (ActionStagingService over PendingActionStore + tool registry), `pairing_codes`, `rate_limiter`, `layout_store`, `domain_read_source` (DefaultDomainReadSource typed-fake), voice components (`speak_sink`, `voice_capture` built from SidecarAudioFrontend + ParakeetWhisperSTT + KokoroTTS), and an optional proactive `heartbeat_task`.
- **Prod guardrails:** `slot == "prod"` requires `require_hello_unlock=True` (else startup `RuntimeError`) and requires the real `WindowsKeyProvider` / `BrokerKeyProvider`. Voice and heartbeat failures are non-fatal (logged, startup continues).

## Endpoints

### Bare app (no prefix)

| Method | Path | Auth | Purpose | Deps |
| --- | --- | --- | --- | --- |
| GET | `/healthz` | none | Liveness probe; returns `{status, slot}` | settings |
| GET | `/readyz` | none | Readiness stub; `{status:"ok", checks:{}}` | none |

### Legacy M1-c router (`api.py`) — UNAUTHENTICATED, unscoped

| Method | Path | Auth | Purpose | Deps |
| --- | --- | --- | --- | --- |
| POST | `/ask` | none | `{text}` → `{text,path,tool_used,escalated}` via `gateway.handle_text` (no scope) | Gateway → Brain |
| POST/GET | `/ask/stream` | none | SSE stream of brain chunks via `gateway.handle_text_stream`; terminal `data: [DONE]` | Gateway → Brain |

### Authenticated client surface (`api_app.py`, prefix `/app`)

Pairing / session / unlock (handshake):

| Method | Path | Auth | Purpose | Deps |
| --- | --- | --- | --- | --- |
| POST | `/app/admin/pair-code` | loopback-only (127.0.0.1/::1) | Mint raw pairing code | PairingCodeStore |
| POST | `/app/pair` | rate-limited; code+signature | Register a new device pubkey after verifying pairing code signature; relays to broker on Mac | PairingCodeStore, AppAuth.registry (DeviceRegistry), broker_client |
| POST | `/app/session/begin` | rate-limited | Issue a 32-byte challenge nonce for a known device | AppAuth (ChallengeStore) |
| POST | `/app/session/complete` | rate-limited | Verify ECDSA-P256 signature over nonce+counter; mint opaque bearer session token | AppAuth (SessionStore, DeviceRegistry counter) |
| POST | `/app/unlock/begin` | `require_session` | Begin vault-unlock relay; returns broker nonce for session-derived scope | key_provider.begin_unlock |
| POST | `/app/unlock/complete` | `require_session` | Complete vault-unlock relay; passes phone proof (device_id, counter, signature) to broker | key_provider.complete_unlock |
| GET | `/app/status` | `require_session` | `{connected, vault_unlocked, device_id}` (works while locked) | key_provider.is_owner_unlocked |
| POST | `/app/lock` | `require_session` | Zeroize cached owner DEKs (keeps session) | key_provider.lock_all |
| POST | `/app/logout` | `require_session` | Revoke current bearer session token | AppAuth.logout |

Layout (vault may be locked):

| Method | Path | Auth | Purpose | Deps |
| --- | --- | --- | --- | --- |
| GET | `/app/layout` | `require_session` | Return stored layout or default seed | LayoutStore |
| PUT | `/app/layout` | `require_session` | Persist layout (last-writer-wins) | LayoutStore |

Recipe review (require **unlocked** vault):

| Method | Path | Auth | Purpose | Deps |
| --- | --- | --- | --- | --- |
| GET | `/app/review/pending` | `require_unlocked` | List recipes awaiting owner review | ReviewSurface |
| GET | `/app/review/auto-enabled` | `require_unlocked` | List auto-enabled recipes | ReviewSurface |
| POST | `/app/review/approve` | `require_unlocked` | Approve a recipe by name (409 on retired/signature) | ReviewSurface (promotion/signing) |
| POST | `/app/review/reject` | `require_unlocked` | Reject a recipe by name | ReviewSurface |

Pending actions (require unlocked):

| Method | Path | Auth | Purpose | Deps |
| --- | --- | --- | --- | --- |
| GET | `/app/actions/pending` | `require_unlocked` | List one-off actions awaiting approval | ActionStagingService |
| POST | `/app/actions/approve` | `require_unlocked` | Execute approved action once (404/409/423) | ActionStagingService + tool registry |
| POST | `/app/actions/reject` | `require_unlocked` | Reject pending action without executing | ActionStagingService |

Task suggestions (require unlocked + rate-limited):

| Method | Path | Auth | Purpose | Deps |
| --- | --- | --- | --- | --- |
| POST | `/app/tasks/suggestion/accept` | `require_unlocked`, rate-limited | Accept suggestion → create task via ProductivityStore | ProductivityStore |
| POST | `/app/tasks/suggestion/reject` | `require_unlocked`, rate-limited | Reject suggestion (idempotent) | ProductivityStore |

Chat (require unlocked, scoped):

| Method | Path | Auth | Purpose | Deps |
| --- | --- | --- | --- | --- |
| POST | `/app/ask` | `require_unlocked` | `{text,speak}` → scoped answer via `gateway.handle_text_scoped(scope)` | Gateway (scoped) → Brain |
| POST | `/app/ask/stream` | `require_unlocked` | SSE scoped stream; re-checks vault before/between every chunk (fail-closed); optional speak branch via `handle_ask_unified` | Gateway, key_provider, speak_sink |
| POST | `/app/ask/voice` | `require_unlocked` | Capture one push-to-talk utterance, stream scoped answer as SSE; optional TTS | Gateway, PushToTalkCapture (`overlay_voice_turn`), key_provider, speak_sink |

Owner domain data (require unlocked) — all served from `DefaultDomainReadSource` (typed fakes) behind a `DomainReadSource` injection seam in the dev tree:

| Method | Path | Auth | Purpose | Deps |
| --- | --- | --- | --- | --- |
| GET | `/app/calendar` | `require_unlocked` | CalendarRead (events + tasks_due_by_day) | domain_read_source |
| GET | `/app/tasks` | `require_unlocked` | TasksRead (overdue/today/upcoming/suggestions) | domain_read_source |
| GET | `/app/projects` | `require_unlocked` | ProjectsRead | domain_read_source |
| GET | `/app/email` | `require_unlocked` | GmailRead (needs_you + signal) | domain_read_source |
| GET | `/app/finance` | `require_unlocked` | FinanceRead (totals, daily, categories, transactions, bills, anomalies) | domain_read_source |

## Auth / session / pairing model

- **Device identity:** P-256 (SECP256R1) keypairs. Client keeps the private key; brain stores the public key (base64 X9.63 uncompressed point) in a `DeviceRegistry` JSON file (`devices_file`), atomic write with file lock, `0o600` perms, per-device monotonic `counter`.
- **Pairing (`/app/pair`):** loopback mints a short-lived code (`admin/pair-code`, SHA-256 hashed, single-slot, 600s TTL, constant-time compare, one-shot consume). Client signs `len(code)||code||device_id` with ECDSA-P256-SHA256; brain verifies signature + consumes code, then registers the device (and relays the key to the Mac Secure Enclave broker; skipped on the Windows host per ADR-033).
- **API session (`/app/session/begin`+`/complete`):** challenge-response. Brain issues a single-use 32-byte nonce (120s TTL, ChallengeStore). Client signs the canonical frame `len(nonce)||nonce||len("session")||"session"||counter_u64be` with ECDSA-P256-SHA256 (DER). Brain verifies signature, enforces strictly-increasing counter, and mints an **opaque** bearer token (`secrets.token_urlsafe(32)`, 1h TTL, in-memory `SessionStore`). `require_session` reads `Authorization: Bearer <token>`. Sessions are revocable (logout, or `revoke_all` on vault lock).
- **Scope:** single-owner — every authenticated principal resolves to `OWNER_PERSON_ID` / `OWNER_SCOPE` (`resolve_scope`). Scope is always session-derived, never client-supplied (unlock request bodies intentionally carry no scope).
- **Rate limiting:** in-memory sliding window (5 attempts / 900s) keyed by peer IP; loopback (127.0.0.1/::1/localhost) is exempt (ADR-033 local-trust note).

## Vault / unlock model

- **Two-stage gate:** authenticating (`require_session`) is distinct from unlocking owner data (`require_unlocked`, HTTP **423** when locked). Owner data + chat + domain reads require unlock; status/layout/lock/logout do not.
- **Key custody:** `KeyProvider` abstraction. On win32 → `WindowsKeyProvider` (DPAPI-backed, **Windows Hello-enforced** unlock at startup; `require_hello_unlock` hard-required in prod). Elsewhere → `BrokerKeyProvider` talking to a Mac Secure Enclave key-broker over a unix socket (`broker.sock`).
- **Unlock relay (`/app/unlock/begin`+`/complete`):** brain returns a broker nonce for the session scope; client returns phone proof (device_id, counter, signature) which the brain passes through to the broker via `complete_unlock`. `lock` zeroizes cached DEKs.
- **Fail-closed streaming:** `/app/ask/stream` and `/app/ask/voice` re-check `is_owner_unlocked()` before the first chunk and between every chunk, emitting `{"error":"vault_locked"}` and stopping if the vault locks mid-stream; any exception emits `{"error":"stream_failed"}` rather than truncating silently.

## Voice model

- **Surface:** `POST /app/ask/voice` (scoped, unlocked). One push-to-talk utterance per call.
- **Capture/answer:** `PushToTalkCapture` (SidecarAudioFrontend + ParakeetWhisperSTT) → `overlay_voice_turn(gateway, capture, scope, speak)` returns a display iterator + speak iterator. Display streams as SSE; the speak branch is fed to a `speak_sink` (KokoroTTS via the audio sidecar) as a retained background asyncio task.
- **Components (lifespan):** SidecarAudioFrontend (IPC to audio sidecar on port 8060), ParakeetWhisperSTT, KokoroTTS, `compose_speak_sink` gated on `is_owner_unlocked`. Voice setup failures are non-fatal.

## Subsystem dependency map (for v2 re-impl)

- **Gateway → Brain:** all `/ask*` endpoints (`handle_text`, `handle_text_scoped`, `handle_text_stream_scoped`, `handle_ask_unified`). Brain carries the registry/model/retrieval.
- **Identity (`app_auth`, `key_provider`):** pairing, session, unlock, every authenticated/unlocked route. DeviceRegistry (file), ChallengeStore + SessionStore (in-memory), WindowsKeyProvider/BrokerKeyProvider + broker_client.
- **Recipes (ReviewSurface, RecipeStore, Promoter, signing):** `/app/review/*`.
- **Staging (ActionStagingService, PendingActionStore, tool registry):** `/app/actions/*`.
- **Productivity (ProductivityStore):** `/app/tasks/suggestion/*`.
- **Domain readers (DomainReadSource seam):** `/app/calendar|tasks|projects|email|finance` — fakes in dev; real readers needed broker owner DEKs + Google OAuth on the Mini.
- **Voice (push_to_talk, sidecar_client, stt, tts, voice_loop):** `/app/ask/voice` + speak branch of `/app/ask/stream`.
- **Proactive (compose_proactive heartbeat):** background task, not an endpoint, but shares brain registry/model + key_provider.
- **Layout (LayoutStore):** `/app/layout`.
