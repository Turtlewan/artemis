# Tauri 2.x Stack Research — Structure & Verification Recipe

**Agent:** A (Structure + Recipe)
**Date:** 2026-06-24
**Target stack:** Tauri 2 + React + TypeScript + Vite + Rust (Artemis desktop client)

---

## Summary

Tauri 2.x (current stable: 2.11.x as of June 2026) is a major architectural break from Tauri 1.x.
The config schema was completely restructured, the security model replaced (allowlist → capabilities),
and most of the built-in Rust API surface moved to separate plugins. The verification recipe for this
stack has two clearly separated layers: Rust (run inside `src-tauri/`) and Frontend (run at project
root). A full `npm run tauri build` requires WebView2 on Windows and is too slow for a fast verify
loop; the recipe below separates compile-only checks from full build.

---

## Key Findings

### 1. Project Scaffold

**Scaffold command (Tauri 2):** [VERIFIED]

```bash
npm create tauri-app@latest
# or
pnpm create tauri-app
# or with template preset skipping prompts:
npm create tauri-app@latest my-app -- --template react-ts --manager npm
```

Interactive prompts:
1. Project name
2. Bundle identifier (e.g. `com.example.myapp`)
3. Frontend language: "TypeScript / JavaScript"
4. Package manager: npm / yarn / pnpm / bun
5. UI template: React
6. UI flavor: TypeScript

After scaffold: `npm install && npm run tauri dev`

**Tauri 1 note:** In Tauri 1, the scaffold was `npm create tauri-app` (no `@latest` tag was required
and the template names differed). The `--template react-ts` preset is the same name in v2. [VERIFIED]

---

### 2. Generated Project Layout [VERIFIED]

Source: https://v2.tauri.app/start/project-structure/

```
my-app/
├── package.json
├── index.html
├── vite.config.ts
├── tsconfig.json
├── src/                          # React frontend source
│   ├── main.tsx
│   ├── App.tsx
│   └── assets/
└── src-tauri/                    # Rust crate root
    ├── Cargo.toml
    ├── Cargo.lock
    ├── build.rs
    ├── tauri.conf.json           # PRIMARY config file (v2 schema)
    ├── src/
    │   ├── main.rs               # Desktop entry point (calls lib::run())
    │   └── lib.rs                # Shared logic + mobile entry point
    ├── icons/
    │   ├── icon.png
    │   ├── icon.icns
    │   └── icon.ico
    └── capabilities/
        └── default.json          # NEW in v2: replaces allowlist
```

**Key structural difference from v1:** Tauri 2 splits `src/main.rs` into `main.rs` (thin desktop
entry) + `lib.rs` (shared logic), because mobile targets need a `lib` crate type. `Cargo.toml` must
declare `crate-type = ["staticlib", "cdylib", "rlib"]` for mobile support. [VERIFIED]

---

### 3. `tauri.conf.json` v2 Schema [VERIFIED]

Source: https://v2.tauri.app/reference/config

```json
{
  "productName": "my-app",
  "version": "0.1.0",
  "identifier": "com.example.my-app",
  "build": {
    "beforeDevCommand": "npm run dev",
    "beforeBuildCommand": "npm run build",
    "devUrl": "http://localhost:5173",
    "frontendDist": "../dist"
  },
  "app": {
    "security": {
      "csp": null,
      "capabilities": ["default"]
    },
    "windows": [
      {
        "title": "My App",
        "width": 800,
        "height": 600,
        "resizable": true,
        "fullscreen": false
      }
    ]
  },
  "bundle": {
    "active": true,
    "targets": "all",
    "identifier": "com.example.my-app",
    "icon": ["icons/32x32.png", "icons/128x128.png", "icons/128x128@2x.png", "icons/icon.icns", "icons/icon.ico"]
  },
  "plugins": {}
}
```

**For Vite + React specifically:** [VERIFIED]
- `devUrl`: `"http://localhost:5173"` (Vite's default port)
- `frontendDist`: `"../dist"` (Vite output directory, relative to `src-tauri/`)
- `beforeDevCommand`: `"npm run dev"` (starts Vite dev server)
- `beforeBuildCommand`: `"npm run build"` (runs `tsc && vite build`)

**Platform-specific overrides:** Tauri 2 supports `tauri.windows.conf.json`, `tauri.macos.conf.json`,
`tauri.linux.conf.json` which merge via JSON Merge Patch (RFC 7396). [VERIFIED]

---

### 4. v1 → v2 Config Schema Differences (THE CRITICAL GOTCHA LIST) [VERIFIED]

Source: https://v2.tauri.app/start/migrate/from-tauri-1/ and https://v2.tauri.app/blog/tauri-20/

| v1 field | v2 field | Notes |
|---|---|---|
| `package.productName` | top-level `productName` | `package` object removed |
| `package.version` | top-level `version` | `package` object removed |
| `tauri` (object) | `app` (object) | Entire `tauri` key renamed |
| `tauri.allowlist` | `src-tauri/capabilities/*.json` | Completely replaced by capabilities system |
| `build.distDir` | `build.frontendDist` | Renamed; must be a path |
| `build.devPath` | `build.devUrl` | Renamed; **v2 only accepts URLs, not paths** |
| `build.withGlobalTauri` | `app.withGlobalTauri` | Moved |
| `tauri.bundle` | top-level `bundle` | Promoted to top level |
| `tauri.cli` | `plugins.cli` | Moved to plugins |
| `tauri.updater` | `plugins.updater` | Moved to plugins |
| `tauri.systemTray` | `app.trayIcon` | Renamed |
| `tauri.pattern` | `app.security.pattern` | Moved |
| New in v2 | top-level `identifier` | Required; was under bundle in v1 |
| New in v2 | top-level `mainBinaryName` | Must match productName if set |

**Security model change:** `tauri.allowlist` (v1) → `src-tauri/capabilities/default.json` (v2).
The `tauri migrate` CLI command auto-converts v1 allowlist to v2 capability files. [VERIFIED]

**Windows scheme change:** The default webview origin changed from `https://tauri.localhost` (v1) to
`http://tauri.localhost` (v2). If using IndexedDB or localStorage, set
`app.windows[].useHttpsScheme: true`. [VERIFIED]

---

### 5. Rust API Breaking Changes (v1 → v2) [VERIFIED]

| v1 Rust API | v2 migration path |
|---|---|
| `Window` type | `WebviewWindow` |
| `WindowBuilder` | `WebviewWindowBuilder` |
| `Manager::get_window()` | `get_webview_window()` |
| `api::dialog` | `tauri-plugin-dialog` |
| `api::http` | `tauri-plugin-http` |
| `api::fs` | `tauri-plugin-fs` |
| `api::shell` | `tauri-plugin-shell` |
| `api::process::Command` | `tauri-plugin-shell` |
| `App::clipboard_manager` | `tauri-plugin-clipboard-manager` |
| `updater` module | `tauri-plugin-updater` |

### JavaScript API Breaking Changes (v1 → v2) [VERIFIED]

| v1 import | v2 import |
|---|---|
| `@tauri-apps/api/tauri` | `@tauri-apps/api/core` |
| `@tauri-apps/api/window` | `@tauri-apps/api/webviewWindow` |
| `@tauri-apps/api/clipboard` | `@tauri-apps/plugin-clipboard-manager` |
| `@tauri-apps/api/dialog` | `@tauri-apps/plugin-dialog` |
| `@tauri-apps/api/fs` | `@tauri-apps/plugin-fs` |
| `@tauri-apps/api/http` | `@tauri-apps/plugin-http` |
| `@tauri-apps/api/os` | `@tauri-apps/plugin-os` |
| `@tauri-apps/api/shell` | `@tauri-apps/plugin-shell` |

### Environment Variable Renames (v1 → v2) [VERIFIED]

| v1 | v2 |
|---|---|
| `TAURI_PRIVATE_KEY` | `TAURI_SIGNING_PRIVATE_KEY` |
| `TAURI_KEY_PASSWORD` | `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` |
| `TAURI_DEV_SERVER_PORT` | `TAURI_CLI_PORT` |
| Platform variables | now use `TAURI_ENV_` prefix |

---

### 6. Dependency Versions [VERIFIED]

**Current stable (June 2026):**
- `tauri` crate: `2.11.x` (latest: 2.11.0 confirmed from docs.rs)
- `tauri-build` crate: `2.x` (must match minor version of `tauri`)
- `tauri-cli`: `2.11.3` (latest npm, published ~June 2026)
- `@tauri-apps/cli` npm: `^2.11.3`
- `@tauri-apps/api` npm: `^2.11.1`

**Version pairing rule [VERIFIED]:** `@tauri-apps/api` and `tauri` crate must align on minor version.
Plugins must match the same minor (e.g., both at `2.x.x`). Use `^2` in Cargo.toml to allow patch
updates; Cargo.lock provides reproducible builds.

**Minimal `src-tauri/Cargo.toml` for Tauri 2 + React/TS/Vite desktop:** [VERIFIED from official docs + community templates]

```toml
[package]
name = "my-app"
version = "0.1.0"
edition = "2021"

[lib]
name = "my_app_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = [] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"

[profile.release]
codegen-units = 1
lto = true
opt-level = "s"
panic = "abort"
strip = true
```

**`package.json` devDependency (minimal):**
```json
{
  "devDependencies": {
    "@tauri-apps/cli": "^2"
  },
  "dependencies": {
    "@tauri-apps/api": "^2"
  }
}
```

Lock files (`Cargo.lock`, `package-lock.json` / `pnpm-lock.yaml`) should be committed for
reproducible builds. [VERIFIED]

---

### 7. `vite.config.ts` for Tauri 2 + React [VERIFIED]

Source: https://v2.tauri.app/start/frontend/vite/

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: host || false,
    hmr: host
      ? { protocol: "ws", host, port: 1421 }
      : undefined,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  envPrefix: ["VITE_", "TAURI_ENV_*"],
  build: {
    // Tauri uses Chromium on Linux/Mac, WebView2 (Chromium-based) on Windows
    target: process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome105" : "safari13",
    minify: !process.env.TAURI_ENV_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
  },
});
```

**Key:** `watch.ignored: ["**/src-tauri/**"]` prevents Vite from re-triggering on Rust file changes.
`TAURI_DEV_HOST` is set by the Tauri CLI during `tauri dev` for mobile targets. [VERIFIED]

---

### 8. CLI Commands Reference [VERIFIED]

Source: https://v2.tauri.app/reference/cli/

| Command | Invocation | Notes |
|---|---|---|
| Dev with HMR | `npm run tauri dev` | Starts frontend dev server + Rust hot-reload |
| Production build | `npm run tauri build` | Full compile + bundle/installer |
| Build no-bundle | `npm run tauri build -- --no-bundle` | Binary only, no installer; faster for CI compile-check |
| Environment info | `npm run tauri info` | Shows Rust/Node/WebView2 versions + config |
| Add plugin | `npm run tauri add <plugin>` | Adds Tauri plugin to both Cargo.toml + package.json |
| Migrate from v1 | `npm run tauri migrate` | Auto-converts allowlist → capabilities |
| Generate icons | `npm run tauri icon <path.png>` | Generates all platform icon sizes |
| Manage permissions | `npm run tauri permission <new\|add\|rm\|ls>` | ACL management |
| Manage capabilities | `npm run tauri capability new` | Create new capability file |

**`cargo tauri` vs `npm run tauri`:** [VERIFIED]
- `npm run tauri` uses the pre-compiled npm binary — faster installs, version-locked in `package.json`.
- `cargo tauri` compiles from source — slower, useful if avoiding Node.js entirely.
- For CI: strongly prefer `npm run tauri build` (pre-compiled, no source compile overhead).
- The GitHub Actions `tauri-action` uses the npm CLI.

**`tauri build --no-bundle`:** Builds the Rust binary + runs `beforeBuildCommand` but skips
producing installers. Much faster. Use in CI for compile verification without full bundle step. [VERIFIED]

---

### 9. Prerequisites (Windows) [VERIFIED]

Source: https://v2.tauri.app/start/prerequisites/

- **Rust MSVC toolchain** — `rustup default stable-msvc` (must use MSVC, not GNU)
  - Target: `x86_64-pc-windows-msvc` or `aarch64-pc-windows-msvc`
- **Microsoft C++ Build Tools** — "Desktop development with C++" workload
- **WebView2** — pre-installed on Windows 10 1803+ and Windows 11 (dev machine: already present)
  - The Tauri installer bundles WebView2 for end-users; not a build-time requirement
- **Node.js** — LTS version (>=20 recommended)
- For MSI building: VBSCRIPT optional Windows feature must be enabled

---

## Recommended Verification Recipe

**Run from project root unless otherwise specified.**

### Layer 1 — Rust (run inside `src-tauri/`)

```bash
# 1. Format check (non-mutating)
cd src-tauri && cargo fmt --check

# 2. Clippy lint (treat warnings as errors)
cd src-tauri && cargo clippy -- -D warnings

# 3. Compile check (fast, no linking)
cd src-tauri && cargo check

# 4. Unit tests
cd src-tauri && cargo test

# Combined (single shell session):
cd src-tauri && cargo fmt --check && cargo clippy -- -D warnings && cargo check && cargo test
```

**Notes:**
- Run ALL of these from inside `src-tauri/` (where `Cargo.toml` lives), NOT from project root.
- `cargo check` is faster than `cargo build` — no linking. Catches type errors and API misuse.
- `cargo clippy` requires the clippy component: `rustup component add clippy`.
- `cargo fmt --check` requires: `rustup component add rustfmt`.
- `cargo test` in Tauri context tests pure Rust logic; it does NOT launch a WebView.
  Tauri provides a mock runtime for command unit tests via `tauri::test::mock_builder()`.

### Layer 2 — Frontend TypeScript + React

```bash
# 1. TypeScript typecheck (no emit)
npx tsc --noEmit

# 2. ESLint (zero warnings in strict mode)
npx eslint . --max-warnings 0

# 3. Vite build (produces dist/ for frontendDist)
npm run build
# equivalent: npx tsc && npx vite build

# 4. Unit tests (Vitest)
npx vitest run

# Combined:
npm run typecheck && npm run lint && npm run test:run && npm run build
```

**Notes:**
- `tsc --noEmit` catches TypeScript errors without producing output files.
- `npm run build` = `tsc && vite build` in the default Vite+React+TS template.
  The `tsc` pass here DOES emit (it's the build step); use `tsc --noEmit` for a pure type-check.
- Vitest is the standard test runner for Vite-based projects; Jest is NOT typically used with Tauri 2 + Vite.
- Tauri JS API calls can be mocked in Vitest using `vi.mock('@tauri-apps/api/core', ...)`.

### Layer 3 — Tauri Integration

```bash
# 1. Environment/dependency check
npm run tauri info

# 2. Compile-check without producing installer (faster than full build)
npm run tauri build -- --no-bundle

# 3. Full build (produces installer; requires all platform prerequisites)
npm run tauri build
```

**Notes:**
- `npm run tauri info` is the "environment doctor" — shows Rust version, Node version, WebView2
  version, `@tauri-apps/cli` version, and parsed config. Run this first when debugging.
- `npm run tauri build -- --no-bundle` still runs `beforeBuildCommand` (Vite build) and compiles
  the full Rust binary in release mode, but skips bundler/installer step. Good for CI compile gate.
- Full `npm run tauri build` on Windows requires WebView2, MSVC toolchain, and C++ build tools.
- Do NOT use `cargo tauri build` in npm-managed projects; use `npm run tauri build` to ensure
  the version-locked CLI from `package.json` is used.

### Full Verification Stack (ordered, fast-to-slow)

```bash
# Stage 1: Static checks (fastest — no compilation)
cd src-tauri && cargo fmt --check && cd ..
npx tsc --noEmit
npx eslint . --max-warnings 0

# Stage 2: Compile + test
cd src-tauri && cargo clippy -- -D warnings && cargo test && cd ..
npx vitest run

# Stage 3: Integration compile (slow — full Rust + Vite build)
npm run tauri build -- --no-bundle
```

### Recommended `package.json` scripts section

Based on the production template at github.com/dannysmith/tauri-template: [COMMUNITY - verified against official docs]

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit",
    "lint": "eslint . --max-warnings 0",
    "test": "vitest",
    "test:run": "vitest run",
    "test:coverage": "vitest run --coverage",
    "rust:fmt:check": "cd src-tauri && cargo fmt --check",
    "rust:clippy": "cd src-tauri && cargo clippy -- -D warnings",
    "rust:test": "cd src-tauri && cargo test",
    "tauri": "tauri",
    "tauri:dev": "npm run tauri dev",
    "tauri:build": "npm run tauri build",
    "tauri:check": "npm run tauri build -- --no-bundle",
    "check:all": "npm run typecheck && npm run lint && npm run rust:fmt:check && npm run rust:clippy && npm run test:run && npm run rust:test"
  }
}
```

---

## Gotchas — Where Frontier Models Get Tauri Wrong

1. **`tauri` object renamed to `app` in `tauri.conf.json`** — Any model trained on Tauri 1 docs
   will emit `"tauri": { ... }` but v2 requires `"app": { ... }`. This is the #1 schema error. [VERIFIED]

2. **`build.distDir` / `build.devPath` are v1-only** — v2 uses `frontendDist` and `devUrl`.
   Additionally, `devUrl` in v2 ONLY accepts URLs (e.g., `http://localhost:5173`), not filesystem
   paths. Using a path here silently breaks `tauri dev`. [VERIFIED]

3. **Allowlist is gone** — Any reference to `tauri.allowlist` in v2 is invalid. The security model
   is now `src-tauri/capabilities/*.json`. You cannot enable IPC commands without a capability file.
   Missing capabilities = commands silently fail with permission errors at runtime. [VERIFIED]

4. **`Window` type is now `WebviewWindow`** — Rust code using `Window`, `WindowBuilder`, or
   `get_window()` won't compile in v2. [VERIFIED]

5. **`@tauri-apps/api/tauri` import is v1-only** — v2 uses `@tauri-apps/api/core` for `invoke()`.
   `@tauri-apps/api/window` is now `@tauri-apps/api/webviewWindow`. [VERIFIED]

6. **The `package` object in `tauri.conf.json` is gone** — `productName` and `version` are now
   at the top level. Models often emit `"package": { "productName": "..." }` for v2, which is wrong. [VERIFIED]

7. **`cargo tauri` is slower than `npm run tauri`** — The npm CLI is pre-compiled. `cargo tauri`
   recompiles the CLI itself. For CI and daily use in npm-managed projects, always use
   `npm run tauri` (or pnpm/yarn equivalent). [VERIFIED]

8. **`vitest` not `jest`** — Tauri 2 + Vite projects use Vitest. Models may suggest Jest config,
   which doesn't work with Vite's ESM-first approach without extra transformation config. [COMMUNITY]

9. **Rust tests must run from `src-tauri/`, not project root** — Running `cargo test` at project
   root fails unless there's a workspace `Cargo.toml`. The `src-tauri/Cargo.toml` is the crate root. [VERIFIED]

10. **`tauri build` requires `beforeBuildCommand` output** — The Vite `dist/` directory must exist
    at `frontendDist` before the Tauri bundler runs. `npm run tauri build` handles this via
    `beforeBuildCommand`; but if you run `cargo build` directly in `src-tauri/`, the frontend won't
    be built and the binary will fail to embed the frontend. [VERIFIED]

11. **Capabilities have an identifier field** — The `default.json` capability file must have an
    `"identifier"` field matching how it's referenced in `app.security.capabilities`. New projects
    often fail on first run because the capability file schema is unfamiliar. [VERIFIED]

12. **`main.rs` vs `lib.rs` split** — Tauri 2 templates put shared logic in `lib.rs` and have
    `main.rs` call `app_lib::run()`. Placing all code in `main.rs` (v1 pattern) breaks mobile
    targets and conflicts with the `crate-type` declaration. [VERIFIED]

---

## Code Examples

### Minimal `src-tauri/capabilities/default.json` (v2)

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Default capability for the main window",
  "windows": ["main"],
  "permissions": [
    "core:default"
  ]
}
```

Reference in `tauri.conf.json`:
```json
{
  "app": {
    "security": {
      "capabilities": ["default"]
    }
  }
}
```

### Minimal `src-tauri/src/lib.rs` (v2 pattern)

```rust
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

### Minimal `src-tauri/src/main.rs` (v2 pattern)

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    app_lib::run();
}
```

---

## Assumptions & Gaps

- **[ASSUMED]** `cargo check` is the right fast-path compile gate. The official Tauri docs don't
  prescribe a specific verification recipe; this is synthesized from Tauri's own CI workflows +
  community templates + Rust standard practice.
- **[ASSUMED]** Vitest is the test runner (inferred from Vite ecosystem; Tauri docs don't mandate
  a specific JS test runner).
- **[ASSUMED]** `--max-warnings 0` for ESLint is the right strict mode (from dannysmith/tauri-template;
  the official scaffold may not set this by default).
- **Gap:** Exact `tauri-cli` version that ships with `create-tauri-app` React-TS scaffold could not
  be verified (GitHub 404 on raw template files). Version pinning guidance uses current stable.
- **Gap:** Tauri's mock runtime for `cargo test` (unit testing Tauri commands) requires
  `tauri = { version = "2", features = ["test"] }` — not documented in the main recipe above.
  Worth a follow-up research pass.
- **NEEDS-DOMAIN:** `v2.tauri.app` — most pages were accessible via WebFetch redirects but some
  returned thin content (authentication walls not present, but the site appears to serve JS-rendered
  content for some sections). The context7 `/websites/v2_tauri_app` source compensated for this.

---

## Sources

### Tier-1 / Primary (VERIFIED)
- Context7 `/websites/v2_tauri_app` — v2.tauri.app official docs (4444 code snippets, High reputation)
- https://v2.tauri.app/start/create-project/ — Scaffold command
- https://v2.tauri.app/start/project-structure/ — Directory layout
- https://v2.tauri.app/develop/configuration-files/ — Config files reference
- https://v2.tauri.app/reference/config/ — Full `tauri.conf.json` schema
- https://v2.tauri.app/reference/cli/ — CLI commands reference
- https://v2.tauri.app/start/frontend/vite/ — Vite integration guide
- https://v2.tauri.app/start/migrate/from-tauri-1/ — Migration guide (v1→v2 breaking changes)
- https://v2.tauri.app/blog/tauri-20/ — Tauri 2.0 stable release announcement
- https://v2.tauri.app/start/prerequisites/ — Prerequisites (Windows)
- https://v2.tauri.app/security/capabilities/ — Capabilities system

### Community (COMMUNITY)
- https://github.com/dannysmith/tauri-template — Production Tauri 2 + React 19 + TS template
  (package.json scripts verified by raw fetch)
- https://www.npmjs.com/package/@tauri-apps/cli — npm latest version (2.11.3)
- https://www.npmjs.com/package/@tauri-apps/api — npm latest version (2.11.1)
- https://github.com/tauri-apps/tauri/releases — Tauri crate release history (latest: 2.11.3)
