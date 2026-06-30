---
slice: client-revival
status: done
coder_effort: operational
---

# CR-6 — Launchable app (one double-click, no terminals)

**Identity:** Final client-revival slice. Owner chose the **"launcher on this machine"** packaging (not a portable PyInstaller bundle): a double-click that starts the brain in the background + opens the built Tauri client. Needs uv/Python on the box (present on the dev machine).

## Delivered

1. **`client/` release build** — `npm run tauri build --no-bundle` produced `client/src-tauri/target/release/artemis-client.exe` (~12.8 MB) in ~2m on MSVC Build Tools 2022. (Confirms the Rust/Tauri toolchain builds cleanly here — the old "pending MSVC" gate is gone.)
2. **`scripts/launch-artemis.ps1`** — (a) start `uv run artemis serve` hidden if not already up, (b) poll `/healthz` until ready (90s budget), (c) open the built client exe (or fall back to `npm run tauri dev`). ASCII-only (Windows PowerShell 5.1 misreads UTF-8 non-ASCII in a no-BOM file).
3. **`Launch Artemis.cmd`** (repo root) — the double-click entry point: runs the PowerShell launcher with `-ExecutionPolicy Bypass`.

## Verified

End-to-end run of the launcher: brain came up (`/healthz` → `{"status":"ok"}`), client launched (`artemis-client.exe` process running). No terminals.

## Notes / scope boundaries

- **Not a portable installer.** The brain runs via the local uv/Python; moving to another machine = the PyInstaller-freeze path (deferred).
- **Proactivity not auto-started by the launcher.** `artemis serve` runs the HTTP API for the client; the proactivity loop is the separate `artemis run` (or Telegram go-live). Wiring the scheduler into the `serve` lifespan (one process = API + proactivity) is a clean follow-up.
- **The brain `serve` process is hidden and persists** after the client window closes (matches the always-on brain model). Stop via Task Manager or `taskkill`.
- The built exe lives under the git-ignored `target/` — not committed; rebuild with `npm run tauri build --no-bundle` from `client/`.
