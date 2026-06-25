# Research: Tauri 2.x stack (for the `apex-tauri` skill + the Artemis CLIENT rewrite)

**Date:** 2026-06-24
**Confidence:** HIGH (Tier-1: v2.tauri.app via context7 + MS Learn + crate docs; frontend recipe empirically run)
**Re-research after:** 2026-07-24 (frontend-framework clock — 30d)
**Phase-2 detail:** `docs/research/2026-06-24-tauri2-stack/agent-{A,B,C,D}.md` (full cited findings).

## Summary
Tauri 2.x (stable 2.11.x, June 2026) is a major break from Tauri 1 — config schema restructured, the
v1 **allowlist** replaced by a **capabilities/permissions (ACL)** system, most built-in APIs moved to
plugins, and a `main.rs`/`lib.rs` split for mobile. A frontier model trained on Tauri 1 gets ~12
concrete things wrong (config keys, import paths, Rust types). For the Artemis client the load-bearing
findings are: (1) a clean **layered Verification Recipe** (Rust ⊂ frontend ⊂ tauri); (2) `backdrop-filter`
on a **transparent** Tauri window is **broken on both WebView2 and WKWebView** — but the in-content
mitigation preserves the liquid-glass look; (3) the ADR-025 hardware-keystore FFI (Win CNG/TPM, mac SE)
is **buildable** with named crates + an `ecdsa`-crate signature normalization. **Recommend** authoring
`apex-tauri` as a stack skill (SKILL.md + impl.md) with the recipe below as its core.

## Key findings

### Verification Recipe (the skill's impl.md core) — layered language ⊂ framework
**Frontend layer** (project root) — *empirically run on the pilot scaffold 2026-06-24, converges:*
- `npx tsc --noEmit` (typecheck) `[VERIFIED — run, exit 0]`
- `npm run build` = `tsc && vite build` `[VERIFIED — run, exit 0]`
- `npx eslint . --max-warnings 0` + `npx vitest run` — **NOT in the base scaffold** (only `dev/build/preview/tauri` ship); these are **project add-ons** the skill must tell the coder to install + wire. `[VERIFIED — pilot package.json had neither]`

**Rust layer** (run inside `src-tauri/`):
- `cargo fmt --check` · `cargo clippy -- -D warnings` · `cargo check` · `cargo test` `[VERIFIED — see pilot run]`

**Tauri integration layer:**
- `npm run tauri info` (env doctor) · `npm run tauri build -- --no-bundle` (compile gate, no installer — the CI gate) · `npm run tauri build` (full, slow, needs WebView2). Prefer `npm run tauri` over `cargo tauri` (pre-compiled, version-locked). `[VERIFIED]`
- Rust command unit tests need `tauri = { features = ["test"] }` + `tauri::test::mock_builder()` (no WebView launched). `[VERIFIED]`

### v1→v2 gotchas a bare coder gets wrong `[VERIFIED]`
`tauri`→`app` config key · `distDir`→`frontendDist` · `devPath`→`devUrl` (URLs only) · `package.{productName,version}`→top-level + new top-level `identifier` · `allowlist`→`capabilities/*.json` · Rust `Window`→`WebviewWindow`, `get_window()`→`get_webview_window()` · JS `@tauri-apps/api/tauri`→`@tauri-apps/api/core` · built-in APIs (`fs/dialog/http/shell/...`)→separate plugins · `build.withGlobalTauri`→`app.withGlobalTauri` · all logic in `main.rs`→`lib.rs` + thin `main.rs` · Vitest not Jest · `cargo test` runs from `src-tauri/`.

### Security model `[VERIFIED]`
Default-deny ACL: `src-tauri/capabilities/*.json` bundle **permissions** (`<plugin>:<perm>` / `core:<perm>`) and bind them to named **windows**. **All** files in `capabilities/` compile in by default (a stray dev file over-grants in prod). Plugins autogenerate `allow-<cmd>`/`deny-<cmd>` from a `build.rs` `COMMANDS` const; scopes are typed `allow[]`/`deny[]` (deny wins). Strict CSP for a no-remote-content client: `default-src 'self'`, `connect-src` **must** include both `ipc:` and `http://ipc.localhost`, `object-src/frame-src 'none'`; never `"csp": null`, never `dangerousDisableAssetCspModification`. Secrets stay in Rust Core — expose only derived outputs (signatures/ciphertexts) over IPC; the webview is untrusted.

### IPC / state `[VERIFIED]`
`invoke` (command) for ~90% request-response · `emit`/`listen` for backend→frontend push · **`Channel`** (new in v2) for ordered streaming (the right primitive for SSE-style brain token streams). State: `app.manage(Mutex::new(..))` — Tauri wraps in `Arc` (don't double-wrap); managed-type/`State<'_,T>` mismatch is a **runtime panic, not a compile error**; `tokio::sync::Mutex` only when holding a guard across `.await`. Errors crossing IPC need a serializable error type (`thiserror` + `impl Serialize`; `anyhow::Error` is not serializable).

### WebKit-safe rendering — the highest-value client finding `[VERIFIED/COMMUNITY]`
- **`backdrop-filter` + transparent window is broken on WebView2 (#12437) AND WKWebView (#13801).** **Mitigation (preserves the design-brief look):** keep the window **non-transparent**, render the bundled **photo background as an in-webview DOM element**, give glass panels a `background: rgba(...)` so `backdrop-filter` samples the **in-content** layer — not the OS desktop. (OS-level blur alt: `window-vibrancy` crate — mica/acrylic Win, vibrancy mac — but that samples the desktop, wrong for a photo-bg design.)
- **Animate only `transform`/`opacity`/`filter`/`clip-path`** — anything else falls off the WKWebView compositor. **No SMIL** (zero HW accel) — use WAAPI/`@keyframes`/rAF. Avoid `mix-blend-mode`+`backdrop-filter` on one element (WebKit #176830) and non-separable blend modes on WKWebView. `will-change` only on actively-animating nodes (layer-budget). 100+ animated nodes → Canvas/WebGL, SVG for static. WKWebView caps rAF at 60fps on macOS 13–15 (lifted in macOS 26).

### Native crypto FFI (for CLIENT-auth, ADR-025) `[VERIFIED]`
- **Windows — feasible:** `windows-sys` (Win32_Security_Cryptography) → `NCryptOpenStorageProvider(MS_PLATFORM_CRYPTO_PROVIDER)` → `NCryptCreatePersistedKey(NCRYPT_ECDSA_P256_ALGORITHM)` → set `NCRYPT_UI_POLICY` **before** `NCryptFinalizeKey` (read-only after) → `NCryptSignHash` → raw 64-byte `r‖s`. **Windows Hello `KeyCredentialManager` is RSA-only — confirmed** (validates ADR-025's NCrypt choice).
- **macOS — feasible:** `security-framework`/`objc2-security` → `SecKeyGeneratePair` with `kSecAttrTokenIDSecureEnclave` + EC 256 + `SecAccessControl(biometryAny)` → `SecKeyCreateSignature(...X962SHA256)` with a pre-evaluated `LAContext` → DER.
- **Signature normalization:** Win raw `r‖s` ↔ mac DER via the `ecdsa` crate (`Signature::from_bytes`/`to_der`, `from_der`/`to_bytes`). A dedicated **plugin** (own ACL namespace) is the right home, not an inline command.

## Recommended approach
**Author `apex-tauri` (stack skill: SKILL.md + impl.md).** impl.md core = the Verification Recipe (above, layered) + NEVER/ALWAYS (security + WebKit-safe + v1/v2) + a Common-errors→fix table; references/ for the FFI plugin walk-through + the full v1→v2 table. Bind into `stack_skills` alongside `apex-python`/`apex-swift`. The 7 CLIENT specs cite it; the recipe is what `apex-code` unions and runs per task.

## Assumptions / gaps
- `[ASSUMED]` `cargo check` as the fast compile gate + Vitest as the test runner + `--max-warnings 0` strictness — synthesized from Tauri CI + community templates (the official scaffold prescribes no recipe).
- **Pilot validation (run 2026-06-24 on the Windows dev box):** scaffold + `npm install` succeeded; **frontend layer converges live** (`tsc --noEmit`, `npm run build` → exit 0); `cargo fmt --check` → exit 0. **Rust compile (`cargo check`/`clippy`/`test`) BLOCKED** — the box's Rust host is `x86_64-pc-windows-gnu` (GNU) which fails `windows-sys`/`parking_lot_core` with `dlltool.exe not found`; the `msvc` toolchain is installed but the **MSVC C++ Build Tools are absent** (no `cl.exe`/MSVC `link.exe`). **→ Tauri-on-Windows prereq, not a recipe defect:** install VS C++ Build Tools + `rustup default stable-msvc`, then re-run the Rust layer. This gates the *entire* Windows-first CLIENT build (dev-machine-first lens), not just skill validation.
- macOS SE / Windows-Hello-prompt behaviour from a Tauri process = ADR-025 build-time spikes (real hardware needed) — not closeable by research.

## Sources
- context7 `/websites/v2_tauri_app` (Tier-1, 4444 snippets) · v2.tauri.app (config/cli/security/migrate/vite) · MS Learn (NCrypt, KeyCredentialManager) · docs.rs (windows-sys, objc2-security, security-framework, ecdsa) · tauri-apps/tauri issues #12437/#13801 · WebKit #176830 · github.com/dannysmith/tauri-template. Full per-claim citations in the agent-{A,B,C,D}.md files.
