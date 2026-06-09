# BRING-UP RUNBOOK — Artemis on Mac Mini

**Date:** 2026-06-09 (pre-arrival draft)
**Target hardware:** M5 (Pro) Mac Mini, 64 GB (per ADR-001 §Refinement 2026-06-09)
**Status:** pre-arrival; all steps are actionable the day the machine arrives.

> Companion docs this runbook references:
> - `docs/bring-up/PRE-ARRIVAL-PREP.md` — everything done **before** arrival
> - `docs/bring-up/SECRETS-INVENTORY.md` — ✅ every secret → Keychain slot (written 2026-06-09)
> - `docs/technical/adr/ADR-002-deployment-method.md` — deployment architecture
> - `docs/changes/M0-a..e`, `M2-a..d` — the specs coding mode will execute

---

## Step 0 — Pre-flight (before touching the Mini)

Complete this checklist **before power-on**. All items are covered in `docs/bring-up/PRE-ARRIVAL-PREP.md` and `SECRETS-INVENTORY.md`.

- [ ] Google Cloud OAuth `client_id` + `client_secret` in password manager (PRE-ARRIVAL-PREP §A1)
- [ ] Brave API key (PRE-ARRIVAL-PREP §A2)
- [ ] Tavily API key (PRE-ARRIVAL-PREP §A2)
- [ ] Jina API key if desired (PRE-ARRIVAL-PREP §A2)
- [ ] Tailscale account exists; optional pre-generated auth key ready (PRE-ARRIVAL-PREP §A3)
- [ ] DeepSeek API key (PRE-ARRIVAL-PREP §A4)
- [ ] Claude subscription confirmed active (PRE-ARRIVAL-PREP §A5)
- [ ] ntfy decision made: self-hosted (default — nothing to do) or ntfy.sh topic reserved; ntfy app on phone (PRE-ARRIVAL-PREP §A6)
- [ ] Model weights pre-staged on external SSD **(optional)** (PRE-ARRIVAL-PREP §B)
- [ ] All secrets accessible from the password manager during bring-up

**Verify:** every secret in `SECRETS-INVENTORY.md` is present in the password manager.

---

## Step 1 — macOS first-boot and accounts

Per ADR-002 the Mini runs two macOS users: the **owner-runtime user** (runs all services) and the **artemis-build user** (sandboxed build agent, no access to owner data).

### 1a. Initial setup wizard
- [ ] Power on; complete the macOS setup wizard using the owner's Apple ID.
- [ ] Set a strong login password for the owner-runtime user.
- [ ] **FileVault:** enable during setup (or immediately after). Record the recovery key in the password manager.

  **Verify:** `fdesetup status` → `FileVault is On`.

### 1b. Owner auto-login (required for the broker LaunchAgent)
- [ ] Configure owner auto-login — per M2-c (`scripts/setup_autologin.sh`, run later at Step 6e; note the requirement now).
- [ ] **⚠️ Important:** auto-login + FileVault interact — FileVault may prompt the owner passphrase on a cold boot **before** auto-login proceeds. Expected (ADR-005 / M2-c). The broker LaunchAgent depends on the owner session being live; the wall stays intact because data still requires the phone proof.

  **Verify (deferred — Step 8/6e):** after first reboot post-auto-login config, confirm owner session comes up headlessly and the broker LaunchAgent loads.

### 1c. Create the build-agent user
- [ ] System Settings → Users & Groups → Add a **Standard** (non-admin) user named `artemis-build`.
- [ ] `scripts/setup_build_user.sh` (M0-e) applies the deny ACLs walling this user off from `/opt/artemis` and the owner's Keychain. Run it at Step 2c.

  **Verify:** `dscl . -list /Users` shows both the owner-runtime user and `artemis-build`.

### 1d. SSH and remote access
- [ ] Enable SSH: System Settings → General → Sharing → Remote Login (owner user only).
- [ ] Install your SSH public key: `ssh-copy-id <owner>@<mini-local-ip>` from the planning machine.
- [ ] Disable password auth once key auth works (`/etc/ssh/sshd_config` → `PasswordAuthentication no`).

  **Verify:** `ssh <owner>@artemis.local` connects without a password prompt.

---

## Step 2 — Base toolchain

### 2a. Xcode Command Line Tools
- [ ] `xcode-select --install` — required for Swift (M2-a broker) and git.

  **Verify:** `swift --version` prints a version; `git --version` exits 0.

### 2b. Install uv
- [ ] `curl -LsSf https://astral.sh/uv/install.sh | sh`; restart shell or `source ~/.zshrc`.

  **Verify:** `uv --version` exits 0.

### 2c. Clone the repo and apply build-agent isolation
- [ ] `git clone git@github.com:<owner>/artemis.git /Users/artemis-build/artemis` — from the **private GitHub remote** (decision 2026-06-09). Requires an SSH deploy key (or the owner's key) on the Mini's `artemis-build` user; add the Mini's public key to the GitHub repo as a read/write deploy key first. (Steady-state origin may later migrate to self-hosted git over Tailscale — see `homelab-control-plane.md` ACI.)
- [ ] As admin: `sudo bash /Users/artemis-build/artemis/scripts/setup_build_user.sh` — creates `artemis-build` (idempotent) + deny ACLs on `/opt/artemis` and owner Keychain (M0-e Task 1).
- [ ] Apply the Claude Code OS-sandbox config for the build agent (M0-e Task 2). **PARK:** exact sandbox config schema/filename confirmed on-hardware — see Parked §P2.

  **Verify (M0-e):** `ls -le /opt/artemis/prod/owner-private` shows a deny ACL for `artemis-build`; `sudo bash -n scripts/setup_build_user.sh` exits 0.

### 2d. Python environment
- [ ] `cd /Users/artemis-build/artemis && uv sync` — installs Python 3.12 (uv-managed, pinned) + runtime + dev deps (M0-a Task 1).

  **Verify (M0-a):** `uv run python -c "import artemis"` exits 0.

### 2e. mlx-openai-server + ntfy
- [ ] `bash scripts/install_mlx.sh` — installs `mlx-openai-server==1.8.1` + `brew install ntfy` + creates `${ARTEMIS_MODEL_DIR:-/opt/artemis/models}` (M0-c Task 1).

  **Verify (M0-c):** the M0-c import check exits 0; `/opt/homebrew/bin/ntfy` exists.

### 2f. Swift toolchain check
- [ ] `swift build` in `swift/ArtemisBroker/` — confirms the broker compiles (M2-a Task 1).

  **Verify:** `swift build` exits 0 in `swift/ArtemisBroker/`.

---

## Step 3 — Data root

Per M0-a (`/opt/artemis`, fixed absolute root outside any user home so the build agent cannot read it):

- [ ] Run the data-dir setup for each slot:
  ```
  sudo bash scripts/setup_data_dir.sh --slot dev  --data-root /opt/artemis
  sudo bash scripts/setup_data_dir.sh --slot uat  --data-root /opt/artemis
  sudo bash scripts/setup_data_dir.sh --slot prod --data-root /opt/artemis
  ```
  Creates `owner-private/{memory,relational,vectors,keys}`, `general/{...}`, `backups/`, `logs/` under each slot at `chmod 700` (M0-a Task 5).
- [ ] `sudo chown -R <runtime-user>:staff /opt/artemis` (owner-runtime user, NOT build-agent).

  **Verify (M0-a):** the script is idempotent for `--slot dev`; `stat -f '%Lp' /opt/artemis/dev/owner-private/memory` → `700`; `.artemis-scope` files exist.

---

## Step 4 — Slot environment files

Per M0-a Task 7 (distinct ports per slot):

| Slot | Brain | MLX  | ntfy | Audio |
|------|-------|------|------|-------|
| dev  | 8030  | 8040 | 8050 | 8060  |
| uat  | 8031  | 8041 | 8051 | 8061  |
| prod | 8032  | 8042 | 8052 | 8062  |

- [ ] `cp config/.env.{dev,uat,prod}.example config/.env.{dev,uat,prod}`; set `ARTEMIS_DATA_ROOT=/opt/artemis` and `ARTEMIS_RUNTIME_USER=<runtime-user>` in each.

  **Verify (M0-a):** `ARTEMIS_ENV_FILE=config/.env.dev uv run python -c "from artemis.config import get_settings; print(get_settings().slot)"` prints `dev`.

---

## Step 5 — Secrets → Keychain

Load every secret from the password manager into the owner-runtime user's macOS Keychain. The slot-by-slot list of **what goes where** is in `SECRETS-INVENTORY.md` — follow it exactly (this runbook does not re-list, to stay DRY). Categories:

- [ ] Google OAuth credentials (S1, S2) — used by M8-a at consent time
- [ ] Search provider keys (S4, S5, optional S6) — used by DR-a/b
- [ ] DeepSeek API key (S7) — build-agent coding sessions + DR-c + distill judge
- [ ] Tailscale auth key (S8, if pre-generated) — used at Step 7
- [ ] Generate + write the ntfy topic secret (S11) into the slot `.env`

Standard Keychain load: `security add-generic-password -a <account> -s <service> -w <secret>` (exact service/account names per `SECRETS-INVENTORY.md`).

**Verify:** `security find-generic-password -s <service> -a <account>` returns the item.

**⚠️ Cross-cutting gap (SECRETS-INVENTORY §P5):** the launchd→Keychain `.env`-injection script that wires these into running services is referenced by several specs but not yet itself specced. Resolve before this step is fully automatable.

---

## Step 6 — Crypto wall init (Secure Enclave key-broker first run)

Requires M2-a/b/c built (coding mode). **Gated on M2-a..c.**

### 6a. Verify the SE environment
- [ ] `ARTEMIS_SE_AVAILABLE=1 swift test` in `swift/ArtemisBroker/` with the SE-guarded test (M2-a Task 9).

  **Verify (M2-a):** real SE gen/wrap/unwrap round-trips; the `.userPresence` degradation question is answered + recorded in handoff. If it degrades to login-unlock, adopt the proof-gated fallback (SE key WITHOUT `.userPresence`; phone proof = sole human factor).

### 6b. Provision per-scope wrapped DEKs (dev slot)
```
ARTEMIS_DATA_ROOT=/opt/artemis ARTEMIS_SLOT=dev swift run -c release artemis-broker provision-scope --scope owner-private
ARTEMIS_DATA_ROOT=/opt/artemis ARTEMIS_SLOT=dev swift run -c release artemis-broker provision-scope --scope general
ARTEMIS_DATA_ROOT=/opt/artemis ARTEMIS_SLOT=dev swift run -c release artemis-broker provision-scope --scope proactive --no-proof
```
Generates a fresh 32-byte DEK per scope, ECIES-wraps with the scope SE key, writes `dek.wrapped` (`0600`), zeroizes plaintext (M2-a Tasks 2–3). Repeat for `uat` and `prod`.

  **Verify (M2-a):** `ls -l /opt/artemis/dev/owner-private/keys/dek.wrapped` exists, perms `0600`, no ASCII-readable plaintext.

### 6c. Register the MockProver device (bring-up without the phone app)
```
ARTEMIS_DATA_ROOT=/opt/artemis ARTEMIS_SLOT=dev swift run -c release artemis-broker pair --device-id mock-bring-up --pubkey <b64-pubkey>
```
**PARK:** exact CLI to extract the MockProver public key (M2-a Task 7) — see Parked §P3.

  **Verify (M2-a):** broker `status` shows the device registered.

### 6d. Install + start the broker LaunchAgent
```
ARTEMIS_RUNTIME_USER=<runtime-user> ARTEMIS_BROKER_BIN=/Users/artemis-build/artemis/swift/ArtemisBroker/.build/release/artemis-broker \
  uv run python scripts/render_plists.py --slot dev --out-dir deploy/launchd/rendered/dev/
cp deploy/launchd/rendered/dev/com.artemis.dev.broker.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.artemis.dev.broker.plist
```
(LaunchAgent = owner session, required for SE access, ADR-005 / M2-c Task 5.)

  **Verify:** `launchctl print gui/$(id -u)/com.artemis.dev.broker` shows running; `/opt/artemis/dev/run/broker.sock` exists.

### 6e. Auto-login config
- [ ] `sudo bash scripts/setup_autologin.sh` (M2-c Task 5); read the FileVault interaction warning.

  **Verify (M2-c):** reboot; owner session comes up; broker running; data still LOCKED until a MockProver proof unlocks it (M2-c Task 8).

---

## Step 7 — Networking (Tailscale)

Per ADR-002 (Tailscale private tunnel; direct LAN at home):

- [ ] `brew install tailscale` (or the Mac app).
- [ ] `sudo tailscale up --authkey <auth-key> --hostname artemis` (use S8; or browser-auth if no key).
- [ ] MagicDNS: PROD = `artemis`, UAT = `artemis-uat` (ADR-002). **PARK:** Tailscale ACLs ensuring guest devices cannot reach PROD — deferred (ADR-002 §Parked) — see Parked §P4.

  **Verify:** `tailscale status` shows the Mini enrolled; `ping artemis` resolves from another member.

---

## Step 8 — Services (launchd daemons)

M0-b writes the plist templates + `render_plists.py`; M0-c wires the mlx launch.

### 8a. Render all plists for dev
```
ARTEMIS_RUNTIME_USER=<runtime-user> \
ARTEMIS_BROKER_BIN=/Users/artemis-build/artemis/swift/ArtemisBroker/.build/release/artemis-broker \
NTFY_BIN=/opt/homebrew/bin/ntfy \
  uv run python scripts/render_plists.py --slot dev --out-dir deploy/launchd/rendered/dev/
```
Produces brain, mlx, ntfy (LaunchDaemons) + audio, broker (LaunchAgents) + backup (M0-e).
- [ ] `plutil -lint deploy/launchd/rendered/dev/*.plist` → each `OK` (M0-b).

### 8b. Download model weights (if not pre-staged) — GATED on-hardware (M0-c Task 4)
Pull into `${ARTEMIS_MODEL_DIR:-/opt/artemis/models}` (from `config/roles.toml`):
- `Qwen3-4B-Instruct-2507` (MLX 4-bit) — responder; always-resident
- `Qwen3-Embedding-0.6B` — embedder; on-demand
- `Qwen3-Reranker-0.6B` — reranker; on-demand
- `Qwen3.6-27B` — sensitive reasoner; on-demand (~18 GB 4-bit)

**PARK:** exact pull CLI (mlx-openai-server 1.8.1 weight-loading) — see Parked §P5. If pre-staged on SSD: copy into `/opt/artemis/models/`.

  **Verify (M0-c):** the model directories exist under `${ARTEMIS_MODEL_DIR}`.

### 8c. Bootstrap the LaunchDaemons (brain, mlx, ntfy) — `sudo`
```
sudo launchctl bootstrap system deploy/launchd/rendered/dev/com.artemis.dev.brain.plist
sudo launchctl bootstrap system deploy/launchd/rendered/dev/com.artemis.dev.mlx.plist
sudo launchctl bootstrap system deploy/launchd/rendered/dev/com.artemis.dev.ntfy.plist
```
  **Verify (M0-b/M0-c):**
  - `curl http://127.0.0.1:8030/healthz` → 200 `{"status":"ok","slot":"dev"}`
  - `curl http://127.0.0.1:8040/v1/models` → lists model ids
  - kill the brain PID → launchd restarts it within ~10s (KeepAlive)

### 8d. Bootstrap the LaunchAgents (audio, broker)
- [ ] Broker already running (Step 6d): `launchctl print gui/$(id -u)/com.artemis.dev.broker`.
- [ ] The audio LaunchAgent fail-restarts until the Swift sidecar binary exists (M5). Expected (M0-b Task 4). Do NOT block.

### 8e. Bootstrap the backup daemon
```
sudo launchctl bootstrap system deploy/launchd/rendered/dev/com.artemis.dev.backup.plist
sudo launchctl kickstart system/com.artemis.dev.backup
```
  **Verify (M0-e):** a snapshot appears under `/opt/artemis/dev/backups/`; `bash scripts/restore_test.sh --slot dev --data-root /opt/artemis` exits 0.

### 8f. On-hardware SQLCipher + mlock spikes (M2-c Tasks 6, 8)
- [ ] **SQLCipher keyed open:** `sqlcipher_open` opens with the correct hex DEK (succeeds) and a wrong key (fails); `PRAGMA cipher_memory_security` ON.
- [ ] **mlock:** `libc.mlock` on the DEK buffer succeeds (no EPERM); page resident.
- [ ] **Full brain→broker→DEK→SQLCipher end-to-end** via broker IPC.

  **Verify:** all three spiked and recorded in `docs/handoff/YYYY-MM-DD.md`.

---

## Step 9 — M2-d Security gate (BLOCKING — M3/M4 cannot start until PASS)

- [ ] M2-a/b/c built; all off-hardware acceptance green; all on-hardware spikes (Steps 6, 8f) recorded.
- [ ] Invoke `apex-security` in a planning session → M2-d threat-model pass.
- [ ] Produces `docs/technical/security/M2-wall-threat-model.md` with PASS / CONDITIONAL-PASS / FAIL.
- [ ] CONDITIONAL-PASS → track follow-up hardening specs. FAIL → build hardening before M3/M4.

  **Verify (M2-d):** gate record exists, ends with a verdict, all five ADR-005 residual risks addressed, M2-a/b/c commit SHAs recorded.

---

## Step 10 — Bring-up and health check

### 10a. Brain health
- [ ] `curl http://127.0.0.1:8030/healthz` → 200 `{"status":"ok","slot":"dev"}` (M0-b).

### 10b. Readiness
- [ ] `curl http://127.0.0.1:8030/readyz` → 200 (M0 stub; gains real engine checks post-M2/M3/M4).

### 10c. SSE / gateway (post-M1)
```
curl -N http://127.0.0.1:8030/app/chat/stream -H "Content-Type: application/json" -d '{"text":"hello"}'
```
Without an unlocked owner session the Gateway returns `LOCKED` (M2-b Task 4); with a MockProver unlock it routes to the Brain. **PARK:** exact endpoint/auth/shape is M1-c — see Parked §P6.

### 10d. Voice acknowledgement smoke test
**PARK:** requires the Swift audio sidecar (M5). Deferred to the M5 bring-up pass — see Parked §P7. At M0/M2 the bring-up smoke is the `/healthz` + SSE text round-trip above.

---

## Step 11 — Promote dev → UAT → PROD

Per ADR-002 (lean-default pipeline; full-UAT auto-triggered for risky changes):

- [ ] `ARTEMIS_DEPLOY_DRYRUN=1 bash scripts/deploy.sh --from dev --to uat` (review planned actions; remove the var to execute).
- [ ] deploy.sh: `pipeline.sh` (lint→typecheck→unit→integration→migration-rehearsal-stub→smoke); backup target slot; record rollback point (`git tag -f artemis-prod-prev`); render plists; `launchctl bootout`→`bootstrap` (M0-b Task 7).
- [ ] **Risky changes** (globs in `deploy/risky_paths.txt`): full-UAT — live UAT instance + "owner sign-off required" → wait for `touch deploy/.uat-approved`.
- [ ] Promote UAT → PROD: same sequence; PROD = MagicDNS `artemis`.

  **Verify:** `curl http://127.0.0.1:8032/healthz` (PROD) → 200 `{"status":"ok","slot":"prod"}`.

---

## Step 12 — Rollback / if-it-fails

- [ ] **Service won't start:** logs at `<data-root>/<slot>/logs/brain.{out,err}.log`; `launchctl print system/com.artemis.<slot>.brain`.
- [ ] **Rollback a bad promotion:** `bash scripts/deploy.sh --rollback --to prod` (checks out `artemis-prod-prev`, re-renders, re-bootstraps, restores pre-promote backup; PROD briefly unavailable).
- [ ] **Restore from backup:** `bash scripts/restore_test.sh --slot prod --data-root /opt/artemis` (confirms latest snapshot passes `PRAGMA integrity_check`; follow M0-e's restore procedure to restore in place).
- [ ] **Crypto wall locked / broker unreachable:** confirm broker LaunchAgent running; if not, re-bootstrap it; then issue a MockProver unlock proof.

---

## Parked (planning must resolve)

| # | Question | Blocking which step |
|---|----------|---------------------|
| ~~P1~~ | ✅ RESOLVED 2026-06-09 — **private GitHub remote, clone over SSH** (deploy key on the Mini's `artemis-build` user). Migrate origin to self-hosted Tailscale git later if desired. | Step 2c |
| P2 | **Claude Code OS-sandbox config schema** — M0-e Task 2: confirm settings schema/filename against installed Claude Code on the Mini. | Step 2c |
| P3 | **MockProver public key extraction CLI** — exact command to get the base-64 pubkey for `pair` (M2-a Task 7). | Step 6c |
| P4 | **Tailscale ACLs for guest isolation** — ADR-002 §Parked; policy file not in any M0–M2 spec. Resolve before any guest device joins. | Step 7 |
| P5 | **Exact MLX model pull command** — M0-c Task 4 GATED on-hardware; mlx-openai-server 1.8.1 weight-loading mechanism. | Step 8b |
| P6 | **SSE / Gateway smoke-test command** — `/app/chat/stream` shape is M1-c; replace illustrative command with the M1-c acceptance test. | Step 10c |
| P7 | **Voice ack smoke test** — needs the M5 audio sidecar + STT/TTS. Deferred to M5 bring-up. | Step 10d |
| P8 | **Launchd→Keychain `.env`-injection script** (also SECRETS-INVENTORY §P5) — referenced by M8-a/M0-b/DR-b but the injection script itself is unspecced. | Step 5, Step 8 |

> Hardware note: targets the **M5 (Pro) Mac Mini, 64 GB** (ADR-001 §Refinement 2026-06-09). All M0–M2 specs were written to the 48 GB floor and are compatible; the extra headroom is pure upside (local non-sensitive teacher path opens up — parked to build).
