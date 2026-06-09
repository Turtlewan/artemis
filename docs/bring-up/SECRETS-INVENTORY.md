# Artemis — Secrets Inventory

**Date:** 2026-06-09 (pre-arrival draft)
**Status:** Planning-mode draft — every secret traced to the real spec/component that consumes it,
or parked for resolution. No secret value ever appears in this file.
**Companion:** `BRING-UP-RUNBOOK.md` (cross-references §Provisioning order below when loading
secrets into Keychain on arrival day).

---

## Main inventory

| # | Secret | Purpose | Consumed by (spec / component) | Storage (slot on the Mini) | How to obtain | Sensitivity tier | Rotation |
|---|--------|---------|--------------------------------|---------------------------|---------------|-----------------|----------|
| S1 | `GOOGLE_OAUTH_CLIENT_ID` | Identifies the installed-app OAuth client to Google | M8-a `GoogleOAuthConfig.load_oauth_config()` → `run_installed_app_consent`, `GoogleCredentialsFactory`; also CAL-a `GoogleCalendarClient` (via M8-a credentials factory) and all future Google connector specs | macOS **Keychain** (generic password, service `artemis.google.oauth`, account `client_id`) → injected into the slot `.env` as `GOOGLE_OAUTH_CLIENT_ID`; NEVER committed | Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client IDs (Desktop app type); PRE-ARRIVAL-PREP §A1 | Medium — config, not owner data | On GCP credential rotation; update Keychain and re-run `artemis-google-auth login` |
| S2 | `GOOGLE_OAUTH_CLIENT_SECRET` | Proves the installed-app identity to Google during token exchange (PKCE is the real protection for installed apps) | Same as S1: M8-a `GoogleOAuthConfig`; `GoogleCredentialsFactory`; all Google connector specs | macOS **Keychain** (service `artemis.google.oauth`, account `client_secret`) → slot `.env` as `GOOGLE_OAUTH_CLIENT_SECRET`; NEVER committed | Same credential download as S1 | Medium — config secret; `GoogleOAuthConfig.__repr__` redacts it | Same as S1 |
| S3 | Google OAuth refresh token (per Google account) | Long-lived credential granting standing read access to Calendar + Gmail on the owner's behalf | M8-a `SqlCipherTokenStore`; `GoogleCredentialsFactory.authorized_credentials()`; transitively CAL-a `GoogleCalendarClient` + M8-b `GmailConnector` | **Owner-private SQLCipher DB** at `<vault>/connectors/google/tokens.db`, opened only with the owner DEK (Tier-1; phone-unlock required); NEVER in env/Keychain/logs; `StoredToken.__repr__` redacts | Generated at first run by `artemis-google-auth login` (M8-a CLI; owner-present, on-hardware gated) | **HIGH — Tier-1 owner-private** (read access to all mail + calendar); phone unlock required | On `invalid_grant` → `ReauthRequiredError` → re-run `artemis-google-auth login`; no scheduled rotation |
| S4 | `BRAVE_API_KEY` | Authenticates web-search requests to Brave Search API (default search provider) | DR-b `BraveSearch`; DR-c `DeepResearcher` (STANDARD mode); M7-c Curiosity Loop | macOS **Keychain** (service `artemis.search.brave`, account `api_key`) → slot `.env` as `BRAVE_API_KEY`; constructor-injected | Brave Search API dashboard (brave.com/search/api); PRE-ARRIVAL-PREP §A2 | Medium — non-sensitive API key; auth header stripped before logging | On plan change or compromise |
| S5 | `TAVILY_API_KEY` | Authenticates fallback search requests to Tavily API | DR-b `TavilySearch`; DR-c `DeepResearcher` (Brave fallback) | macOS **Keychain** (service `artemis.search.tavily`, account `api_key`) → slot `.env` as `TAVILY_API_KEY`; constructor-injected | Tavily account (tavily.com); free tier; PRE-ARRIVAL-PREP §A2 | Medium — non-sensitive API key | On compromise |
| S6 | `JINA_API_KEY` (optional) | Authenticates enhanced-fetch requests to Jina Reader API | DR-b `JinaFetcher` (optional; falls back to `TrafilaturaFetcher` if absent) | macOS **Keychain** (service `artemis.search.jina`, account `api_key`) → slot `.env` as `JINA_API_KEY`; constructor-injected | Jina AI account (jina.ai); PRE-ARRIVAL-PREP §A2 | Medium — non-sensitive; optional | On compromise |
| S7 | `DEEPSEEK_API_KEY` | (a) build-agent Claude Code coding sessions (`ANTHROPIC_BASE_URL` → DeepSeek); (b) DR-c `research_orchestrator_standard` role for non-sensitive queries; (c) the distill-datagen pipeline judge (`distill-datagen-pipeline` spec) | Build-agent Claude Code env; DR-c `config/roles.toml` `{ env = "DEEPSEEK_API_KEY" }`; `tools/distill` JudgeAdapter | Build-agent: env var in `artemis-build` shell, NOT owner-runtime Keychain; DR-c + distill runtime: macOS **Keychain** (service `artemis.deepseek`, account `api_key`) → slot `.env` as `DEEPSEEK_API_KEY` (+ optional `DEEPSEEK_BASE_URL`, `DEEPSEEK_JUDGE_MODEL`) | DeepSeek platform (platform.deepseek.com); PRE-ARRIVAL-PREP §A4 | Medium — non-sensitive; hard rule: DeepSeek must NEVER receive sensitive data (ADR-001, brain.md §privacy) | On compromise |
| S8 | Tailscale auth key (device join key) | Headless/scripted join of the Mini to the tailnet on arrival (optional; can join interactively) | Tailscale CLI (`tailscale up --auth-key=…`) at bring-up; no running Artemis service after join | Used once at bring-up; store pre-arrival in password manager; discard after join | Tailscale admin console → Settings → Keys → Generate auth key; PRE-ARRIVAL-PREP §A3 | Medium — one-time device-join credential | Single-use / short-lived ephemeral; discard after join |
| S9 | Tailscale account login session | Keeps Mini + iPhone on the tailnet for the private tunnel (ADR-002) | Tailscale daemon (macOS service); Tailscale app on iPhone; no Artemis code | Tailscale daemon manages its own session credential; not Artemis-provisioned | Log in at tailscale.com; PRE-ARRIVAL-PREP §A3 | Low — managed by Tailscale daemon | Tailscale handles refresh |
| S10 | Claude subscription session (`claude` CLI login) | Enables the `claude-cli` adapter to call the teacher (Claude Opus via subscription quota); also planning-mode + distill-datagen teacher | M0-a `config/roles.toml` `teacher` + `research_orchestrator_deep` roles (`adapter = "claude-cli"`); `ClaudeCliModelPort`; `tools/distill` TeacherAdapter. **NOT an API key** — see §SC1 | Managed by the `claude` CLI (OAuth session in its own config / login keychain of the runtime user); Artemis does NOT provision/store it | `claude login` in the owner-runtime user's terminal on the Mini; PRE-ARRIVAL-PREP §A5; training opt-out set on the account (ADR-001) | Special — subscription OAuth session; §SC1 | Re-run `claude login` on expiry / new device |
| S11 | ntfy topic secret suffix (`ARTEMIS_NTFY_TOPIC_SECRET`) | Random suffix making the ntfy topic (`artemis-{slot}-{rand_hex16}`) unguessable — the topic IS the egress capability | M6-c `NtfyDelivery` (topic construction); ntfy LaunchDaemon plist (M0-b) | **Slot `.env`** under `ARTEMIS_NTFY_TOPIC_SECRET` (≥16-byte hex; M6-c "B1 fix"); NOT committed; Keychain optional | `python3 -c "import secrets; print(secrets.token_hex(16))"` at slot-init (arrival day) | Medium — capability secret | Rotate on suspected exposure; re-subscribe phone |
| S12 | Phone pairing P-256 public key | Phone's SE-backed public key registered with the broker to verify `UnlockProof` assertions | M2-a `RegisteredDeviceStore` → broker `pair` IPC; M2-c `BrokerKeyProvider` (via verified proofs); ADR-010 brain app-auth registry | Broker on-disk store `<data_root>/<slot>/<scope>/keys/`; also brain app-auth registry (ADR-010); **public key — not secret** | Generated on iPhone at pairing (CLIENT milestone; M2 uses `MockProver`); sent via `pair` IPC | LOW — public key; integrity-sensitive at pairing | On phone replacement: re-pair (idempotent); revoke old device |
| S13 | Owner auto-login password / FileVault recovery key | Owner auto-login at boot (ADR-002/005) so the broker LaunchAgent loads headless after a power cut; FileVault recovery if locked out | M2-c `scripts/setup_autologin.sh` (`/etc/kcpassword`); macOS FileVault boot | Password manager (pre-arrival); `/etc/kcpassword` written by `setup_autologin.sh` (root-only); FileVault recovery key in password manager | Owner macOS password (set at OS setup); FileVault recovery key (generated at FileVault setup) | HIGH — macOS boot credentials | On password change; re-run `setup_autologin.sh`; store new recovery key |

---

## Special cases

### SC1 — Claude subscription teacher session (not a static API key)
The `teacher` and `research_orchestrator_deep` roles use `adapter = "claude-cli"` (ADR-001) — an **interactive OAuth login** maintained by the `claude` CLI on the owner-runtime user's session, NOT a static `ANTHROPIC_API_KEY`. The `ClaudeCliModelPort` (and the `tools/distill` TeacherAdapter) call `claude -p …` as a child process inheriting the CLI session.
- No `CLAUDE_API_KEY` env var to load into Keychain.
- Arrival day: run `claude login` in the owner-runtime user's terminal; confirm `claude -p "ping" --output-format json` works (verified working on the Windows planning machine 2026-06-09).
- CLI session lives in `~/.claude/` of the owner-runtime user (not the build-agent).
- The subprocess must use a **sanitised env** (no credential vars inherited).
- **Training opt-out** set on the Claude account (ADR-001); teacher sees non-sensitive data only.

### SC2 — SQLCipher per-scope DEKs (SE-derived, not manually provisioned)
Each scope's SQLCipher DEK is a 32-byte random key generated by the broker (`provision-scope`) and SE-ECIES-wrapped; only the ciphertext `dek.wrapped` is stored. The owner never handles a plaintext DEK. Auto-provisioned at build time by `artemis-broker provision-scope`. **Not a bring-up loading item.**

### SC3 — Brain app-auth session tokens (ADR-010)
Short-lived opaque API-session tokens issued by the brain to the authenticated phone app — generated in memory, validated against S12, stored in the iOS keychain by the app. Not owner-provisioned. **Not a bring-up loading item.**

---

## Provisioning order (cross-reference BRING-UP-RUNBOOK.md)

1. **Pre-arrival (password manager, off-Mini):** S1, S2, S4, S5, S6 (optional), S7, S8.
2. **Arrival — OS setup:** macOS accounts (owner-runtime + `artemis-build`); owner password + FileVault recovery key + auto-login (S13).
3. **Arrival — Keychain loading (before any service start):** S1, S2, S4, S5, S6, S7 → owner Keychain. Generate + write S11 to the slot `.env`.
4. **Arrival — Tailscale join:** S8 → `tailscale up --auth-key=…`; discard S8 after join.
5. **Arrival — Broker bring-up (owner-runtime session):** `artemis-broker provision-scope` for `owner-private`, `general`, `proactive --no-proof` → SE-wrapped DEKs (SC2).
6. **Arrival — Google OAuth consent (on-hardware, owner-present):** `artemis-google-auth login` → creates S3 in the owner-private SQLCipher store. Requires broker running + vault unlocked (MockProver at bring-up).
7. **Arrival — Claude CLI login:** `claude login` (S10); confirm `claude -p "ping"` works.
8. **CLIENT milestone (later):** real phone pairing registers S12. Until then, `MockProver`.

---

## Parked (planning must resolve)

| ID | Parked item | Why parked | Who resolves |
|----|------------|-----------|-------------|
| P1 | Exact Keychain service/account slot names for S1–S7 | Names above are proposed conventions; the launchd env-injection `security find-generic-password` invocation isn't confirmed on the Mini | Planning + M0-b follow-up or runbook |
| P2 | `ARTEMIS_NTFY_TOPIC_SECRET` — slot `.env` vs separate Keychain slot | M6-c says "non-public Settings"; exact mechanism unspecced (listed as `.env`, S11) | Planning |
| P3 | ntfy.sh topic token (if ntfy.sh chosen over self-hosted) | PRE-ARRIVAL-PREP §A6 offers both; ntfy.sh adds a secret; self-hosted (default) needs none beyond S11 | Owner at bring-up |
| P4 | `ARTEMIS_BROKER_SKIP_CODESIGN` dev flag | M2-a dev bypass for the broker IPC peer code-signing check; not a secret but must be ABSENT in PROD | Runbook authoring |
| P5 | **Launchd env-injection mechanism for secrets** | The Keychain → slot `.env` injection seam is referenced (M8-a, M0-b, DR-b/c) but the script that reads Keychain and writes the `.env` at service start is **not yet specced** | Planning ⚠️ (the biggest gap) |
| P6 | DeepSeek `roles.toml` env-reference dereference | DR-c uses `api_key = { env = "DEEPSEEK_API_KEY" }`; the M0-a `ModelRole` pydantic model must dereference env at Settings-load (M0-a says "No secrets are read here") | Coding mode at DR-c build |
| P7 | APNs / push credential (watch / future mobile push) | If a native push path is ever needed beyond ntfy→Tailscale | Park until CLIENT milestone |

---

## Out of scope (explicitly not secrets)
- MLX model weights — large files, not secrets.
- Per-scope SQLCipher DEKs — SE-derived, auto-provisioned (SC2).
- Brain app-auth session tokens — ephemeral, in-memory (SC3).
- Phone SE private key — non-exportable from the iPhone SE.
- Tailscale coordination metadata — managed by the daemon.
- macOS user passwords (`artemis-build`) — operational credential set at OS setup.
