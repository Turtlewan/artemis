<!-- amended 2026-06-11 per Decision D4/D5 (contracts.md Seam 10) -->

# ADR-002 — Deployment Method (Mac Mini appliance)

**Status:** Accepted (SP0 deployment-method discussion, 2026-06-03)
**Builds on:** ADR-001 (stack) — this ADR decides *how* that stack is run, supervised, reached, built, and protected on the box. Hardware (48GB Mac Mini M4 Pro appliance) was already decided in ADR-001.

## Context
ADR-001 locked a native polyglot stack (Python brain + Swift app/sidecar + MLX inference + LanceDB +
SQLite/SQLCipher + ntfy) on a dedicated 48GB Mac Mini. Open question carried into this session: the
*operational method* — process model & supervision, where/how AI builds the code, how clients reach
the box, the dev→UAT→PROD lifecycle, and backup wiring. Decided in a single SP0 discussion; this ADR
is the durable home for those calls. Clients are **native apps, never a browser** (per owner; also why
ADR-001 chose SwiftUI).

## Decision
A **native-first single-box appliance**: everything runs directly on macOS under `launchd`; no
container runtime for the live system. Containers are explicitly rejected for the runtime because **no
macOS container runtime (Docker Desktop, OrbStack, Colima/Lima, or Apple's own `container`) can give a
Linux container Metal/GPU access** — and MLX *is* Metal, so the inference layer and Swift audio sidecar
are natively bound regardless. Nothing else in the stack benefits from a container (LanceDB + SQLite
are embedded libraries; ntfy is a single binary).

| Aspect | Decision |
|--------|----------|
| **Runtime / supervision** | All services native, supervised by **`launchd`**. Brain (FastAPI) + `mlx-openai-server` + ntfy as **LaunchDaemons**; Swift audio sidecar as a **LaunchAgent** (needs the user audio session). Boot-start + `KeepAlive` restart-on-crash. |
| **Live vs build mode** | **Mutually exclusive, not concurrent.** Build/test pauses the live assistant (`launchctl` stop), freeing the whole box; resume (`launchctl` start) afterward. Removes all RAM/GPU contention. |
| **Build location** | On the **Mini** (only Apple Silicon can test the MLX/Apple-specific code; the owner's planning PC is Windows). The code-writer's intelligence (DeepSeek) is **cloud**; only a thin Claude Code "hands" tool + occasional test runs are local. |
| **Build-agent isolation** | **Strong (defense in depth):** the build agent runs under a **dedicated macOS user account** (cannot decrypt owner data — SQLCipher keys live in the owner's Keychain, inaccessible cross-user) **+** **Claude Code's OS-level sandbox** (filesystem + network walls; blocks prompt-injection exfiltration). Both native → full MLX test capability retained. Build/test uses **sample data**, never real owner data. |
| **Client reachability** | **Tailscale** private tunnel. Data is end-to-end encrypted + device-to-Mini direct; only coordination metadata touches Tailscale (never data). **At home = direct LAN** (the <1s bar is a LAN target); away = tunnel (a beat slower, accepted). MagicDNS names PROD (`artemis`) vs UAT (`artemis-uat`). **Headscale** recorded as a future zero-third-party swap (same clients; needs a VPS or exposed port). |
| **Client surface** | The Mini serves a **native API** (HTTP + streaming/WebSocket for voice/tokens) — **no web UI, no public reverse proxy**. iPhone/iPad = native SwiftUI tunnel members. Raspberry Pi (maybe) = native, runs Tailscale directly (4G/LTE uplink only if it roams). **CircuitMess "NASA Artemis Watch 2.0" (ESP32-S3, WiFi+BLE, 600mAh) (maybe)** = reaches Artemis via a **phone-Bluetooth bridge** (watch → BLE → phone app → tunnel → Mini), following the cloudless **Gadgetbridge/Bangle.js** pattern — chosen over a watch-hosted tunnel because continuous WiFi/WireGuard drains the 600mAh battery in ~4–8h vs all-day for BLE, and BLE-to-phone is the device's intended model. WireGuard-on-watch kept only as a niche on-charger / phone-absent fallback. |
| **dev → UAT → PROD** | Three **roles/slots on one box** (separate logins/dirs/ports/data), not three machines. **Lean by default** (DEV → PROD + smoke test) for cheap-to-undo changes; **Full** (dedicated UAT instance on sample data, owner hands-on sign-off) **auto-triggered for risky changes** — those that include a **data migration**, touch **sensitive modules** (finance/health/journal/memory), or touch the **security/identity wall**. The "pipeline" is a **local script** (lint → typecheck → unit → integration → migration rehearsal → smoke) — no CI server. **Slots are realized as per-slot git worktrees** (Decision D5, 2026-06-11): one primary clone + one `git worktree` per slot, each pinned to a ref (dev@main, uat@candidate-tag, prod@released-tag). Slots differ by data-root / `.env` / ports AND by their own pinned code worktree. Promotion = `git -C <target-worktree> checkout <next-tag>` (advance the slot's worktree), NOT a redeploy of a shared working tree. |
| **Migrations & rollback** | **Expand/contract** migrations (add → backfill → remove; never rip-and-replace). **Backup-before-migrate** snapshot is the safety net; rollback = restore snapshot + previous code version. The *same* version that passed UAT is promoted to PROD (no rebuild-for-prod). |
| **Backups** | **Clean snapshots only** (`VACUUM INTO` / keyed export — never a raw copy of a live DB); already-encrypted source → encrypted snapshots. **Scheduled via `launchd`** + the pre-migrate hook. **Tested restores.** **At least one append-only/immutable copy** (2026 ransomware-resilience baseline). Local copies: external SSD → NAS later (purchase deferred). **Offsite deferred for now** (local-only); cloud-free rotated drive vs encrypted-cloud chosen at offsite time. |

## Runner-ups ruled out
- **Containers-first / Docker for the runtime** — MLX can't run in the Linux VM (no Metal), so inference
  escapes to native anyway; worst RAM profile on a 48GB box; cuts against simplicity + token/resource
  frugality. Apple's `container` framework (v0.6.0) doesn't change the Metal verdict.
- **Hybrid (containerised side-services)** — no service in the stack genuinely benefits (ntfy = one
  binary; stores = embedded libs); pays a runtime's overhead for nothing.
- **Build on a separate Apple-Silicon box** — cleanest dev/prod split, but needs buying a second Mac
  now; revisit at the future Mac Studio upgrade (old Mini → dedicated build/test box).
- **Devcontainer for the build agent** — strongest namespace isolation, but dev containers are Linux →
  same Metal wall → can't run the AI tests. Dedicated-user + sandbox gives a real boundary natively.
- **Headscale / self-hosted WireGuard now** — Headscale needs a VPS or exposed port (*more* outside
  infrastructure, not less); raw WireGuard is manual + breaks on CGNAT. Tailscale keeps data fully
  local-encrypted with no extra internet-facing box.
- **Encrypted-cloud / rotated-drive offsite now** — deferred with the backup-device purchase.

## Consequences
- **One box, two modes** — the appliance is either *serving* or *being built*, never both. Simple, but
  means a build/test session makes the assistant briefly unavailable (acceptable per owner).
- **`launchd` is the operational spine** — pause/resume, boot-start, crash-restart, and scheduled
  backups all ride it. Plists are version-controlled templates; `uv` lockfiles pin Python deps.
- **Cloud touchpoints are bootstrapping + non-sensitive only** — the build agent (DeepSeek) and teacher
  (Claude subscription, ADR-001) are cloud, but the dedicated-user + sandbox + sample-data discipline
  keeps them off real owner data, consistent with the local-only-for-data posture.
- **No web surface to harden** — native-API-only removes a whole class of attack surface.
- **Deferred (architect-now, buy/decide-later):** backup device (SSD→NAS), offsite strategy, Headscale
  swap, second build box at Studio upgrade, low-power-client (watch) LAN TLS approach, watch hardware
  feasibility.

## Parked (build-phase details)
LAN TLS for low-power clients (plain HTTP on trusted LAN vs local CA) · Litestream continuous WAL
replication vs nightly `VACUUM INTO` (or both) · exact `launchd` job layout & ordering · the deploy
script's promotion/rollback mechanics · Tailscale ACLs (guest devices must not reach PROD).
