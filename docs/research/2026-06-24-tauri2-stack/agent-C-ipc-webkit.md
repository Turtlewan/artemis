# Agent C — Tauri 2.x IPC, State, Frontend Integration & WebKit Rendering

**Date:** 2026-06-24
**Scope:** Tauri 2.x IPC primitives, managed state, @tauri-apps/api v2 frontend setup, and cross-platform WebKit-safe rendering for a liquid-glass spatial map UI.
**Sources:** context7 (/websites/v2_tauri_app), v2.tauri.app official docs, GitHub issues, motion.dev, caniwebview.com.

---

## 1. IPC Primitives: Command / Event / Channel

### Decision Rule

| Pattern | Initiator | Return value | Ordered | Use when |
|---|---|---|---|---|
| `invoke` + `#[tauri::command]` | Frontend | Yes (Promise) | N/A | Frontend-initiated request-response (90% of cases) |
| `emit` / `listen` | Either | No | No | Backend push (lifecycle, state-change notifications); fire-and-forget |
| `Channel` | Frontend invokes; backend streams | No per-message | **Yes** (index-based) | Ordered streaming — large data, progress events, chunked file reads |

**Source:** [v2.tauri.app IPC concepts](https://v2.tauri.app/concept/inter-process-communication/) [verified], [DEV.to IPC decision article](https://dev.to/hiyoyok/ipc-in-tauri-tauri-commands-vs-custom-ipc-what-to-use-when-2ab4) [verified]

### Commands (`invoke`)

```typescript
// Frontend — @tauri-apps/api/core (NOT @tauri-apps/api/tauri — that is v1)
import { invoke } from '@tauri-apps/api/core';
const result = await invoke<CustomResponse>('my_custom_command', { number: 42 });
```

```rust
// Rust — serde::Serialize required on all return types
#[derive(serde::Serialize)]
struct CustomResponse { message: String, other_val: usize }

#[tauri::command]
async fn my_custom_command(
    window: tauri::WebviewWindow,
    number: usize,
    database: tauri::State<'_, Database>,
) -> Result<CustomResponse, String> {
    // ...
}

// Registration — ONE call only; multiple invoke_handler calls = last wins (silent bug)
tauri::Builder::default()
    .manage(Database {})
    .invoke_handler(tauri::generate_handler![my_custom_command])
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
```

**Source:** [v2.tauri.app calling-rust](https://v2.tauri.app/develop/calling-rust/) [verified via context7]

### Events (`emit` / `listen`)

```rust
// Backend → all frontends (global broadcast)
use tauri::{AppHandle, Emitter};
#[tauri::command]
fn download(app: AppHandle, url: String) {
    app.emit("download-started", &url).unwrap();
    app.emit("download-progress", 50u8).unwrap();
    app.emit("download-finished", &url).unwrap();
}
```

```typescript
// Frontend listen — always unlisten on component unmount
import { listen } from '@tauri-apps/api/event';
const unlisten = await listen<string>('download-started', (event) => {
    console.log(event.payload);
});
// In React: call unlisten() in useEffect cleanup
```

**Source:** [v2.tauri.app calling-frontend](https://v2.tauri.app/develop/calling-frontend) [verified via context7]

### Channels (Tauri 2 new primitive — ordered streaming)

```rust
use tauri::{AppHandle, ipc::Channel};
#[tauri::command]
async fn load_image(path: std::path::PathBuf, reader: Channel<&[u8]>) {
    // streams 4 KB chunks; order guaranteed by internal index
    let mut file = tokio::fs::File::open(path).await.unwrap();
    let mut chunk = vec![0; 4096];
    loop {
        let len = file.read(&mut chunk).await.unwrap();
        if len == 0 { break; }
        reader.send(&chunk).unwrap();
    }
}
```

```typescript
import { invoke, Channel } from '@tauri-apps/api/core';
const onEvent = new Channel<Uint8Array>();
onEvent.onmessage = (chunk) => { /* render progress */ };
await invoke('load_image', { path: '/some/file', onEvent });
```

Use Channel (not repeated events) when emitting hundreds of progress messages — lower serialisation overhead, preserved ordering. **Source:** [v2.tauri.app calling-rust channels](https://v2.tauri.app/develop/calling-rust) [verified]

---

## 2. Managed State

### Pattern

```rust
use std::sync::Mutex;
use tauri::{Builder, Manager, State};

#[derive(Default)]
struct AppState { counter: u32 }

fn main() {
    Builder::default()
        .setup(|app| {
            // Tauri wraps in Arc automatically — do NOT wrap in Arc yourself
            app.manage(Mutex::new(AppState::default()));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![increase_counter])
        .run(tauri::generate_context!())
        .unwrap();
}

// Sync command — std::sync::Mutex is fine
#[tauri::command]
fn increase_counter(state: State<'_, Mutex<AppState>>) -> u32 {
    let mut s = state.lock().unwrap();
    s.counter += 1;
    s.counter
}

// Async command — MUST use tokio::sync::Mutex to hold guard across await
// (also re-exported as tauri::async_runtime::Mutex)
#[tauri::command]
async fn increase_counter_async(state: State<'_, Mutex<AppState>>) -> Result<u32, ()> {
    let mut s = state.lock().await;
    s.counter += 1;
    Ok(s.counter)
}
```

**Key rules:**
- `tauri::Builder::manage()` OR `app.manage()` in `.setup()` — same effect.
- No `Arc` needed: Tauri injects Arc internally.
- Type mismatch (`State<'_, T>` where T wasn't managed) → **runtime panic**, not compile error.
- Async commands: use `tokio::sync::Mutex` when you `.await` while holding the guard; `std::sync::Mutex` is fine for sync-only access.

**Source:** [v2.tauri.app state-management](https://v2.tauri.app/develop/state-management/) [verified]

---

## 3. Error Handling Across the IPC Boundary

```rust
// All command return types must implement serde::Serialize — including errors.
// anyhow::Error does NOT implement Serialize — using it directly is a silent compile failure.

use thiserror::Error;

#[derive(Debug, Error)]
pub enum AppError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Any(#[from] anyhow::Error),  // wrap anyhow here, not expose directly
}

impl serde::Serialize for AppError {
    fn serialize<S: serde::ser::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(self.to_string().as_ref())
    }
}

#[tauri::command]
async fn risky_op() -> Result<String, AppError> { Ok("ok".into()) }
```

Frontend receives the error as a rejected Promise; catch with `.catch()` or `try/catch` in async functions.

**Source:** [tauritutorials.com error handling](https://tauritutorials.com/blog/handling-errors-in-tauri) [verified], context7 docs [verified]

---

## 4. Frontend Integration (@tauri-apps/api v2)

### Module layout (v2 — breaking change from v1)

| Import path | Contents |
|---|---|
| `@tauri-apps/api/core` | `invoke`, `Channel`, `convertFileSrc` — **replaces v1 `@tauri-apps/api/tauri`** |
| `@tauri-apps/api/event` | `listen`, `once`, `emit` |
| `@tauri-apps/api/window` | `Window`, `getCurrentWindow` |
| `@tauri-apps/api/webviewWindow` | `WebviewWindow`, `getCurrentWebviewWindow` — **v2 renamed from `Window`** |
| `@tauri-apps/api/path` | path utilities |
| `@tauri-apps/api/app` | app metadata |

**v1 → v2 breaking rename:** `@tauri-apps/api/tauri` → `@tauri-apps/api/core`. Forgetting this gives a silent runtime failure (import resolves but `invoke` is undefined).

**Source:** [v2.tauri.app JS API reference](https://v2.tauri.app/reference/javascript/api/) [verified]

### Vite config (`vite.config.ts`)

```typescript
import { defineConfig } from 'vite';
const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
    clearScreen: false,               // show Rust errors in terminal
    server: {
        port: 5173,
        strictPort: true,
        host: host || false,
        hmr: host ? { protocol: 'ws', host, port: 1421 } : undefined,
        watch: { ignored: ['**/src-tauri/**'] },
    },
    envPrefix: ['VITE_', 'TAURI_ENV_*'],
    build: {
        // Target the correct engine per platform — critical for CSS compat
        target: process.env.TAURI_ENV_PLATFORM === 'windows' ? 'chrome105' : 'safari13',
        minify: !process.env.TAURI_ENV_DEBUG ? 'esbuild' : false,
        sourcemap: !!process.env.TAURI_ENV_DEBUG,
    },
});
```

### tauri.conf.json

```json
{
    "build": {
        "beforeDevCommand": "npm run dev",
        "beforeBuildCommand": "npm run build",
        "devUrl": "http://localhost:5173",
        "frontendDist": "../dist"
    },
    "app": {
        "withGlobalTauri": false
    }
}
```

`withGlobalTauri` (v2: moved from `build` to `app`) exposes `window.__TAURI__` for vanilla JS; **not needed when using `@tauri-apps/api` ESM imports in React/Vite** — leave false to avoid globals pollution.

**Source:** [v2.tauri.app/start/frontend/vite](https://v2.tauri.app/start/frontend/vite/) [verified]

---

## 5. WebKit-Safe Rendering — The Critical Half

### Engine map

| Platform | Engine | Key constraint |
|---|---|---|
| Windows | WebView2 (Chromium / Edge) | Full Chromium feature set; GPU accelerated SVG |
| macOS | WKWebView (WebKit / Safari) | Core Animation compositor; 60fps cap (macOS 13–15); narrower CSS feature support |
| Linux | WebKitGTK | backdrop-filter expected June 2026 per caniwebview.com; treat as unsupported |

### A. `backdrop-filter` / blur — the biggest gotcha

**Findings (all confirmed via GitHub issues, Tauri 2.x):**

1. **Transparent window + `backdrop-filter` is broken on both platforms in Tauri 2.** When `"transparent": true` is set in `tauri.conf.json`, the blur effect degrades or behaves incorrectly on Windows (issue #12437, Tauri 2.2.2, Jan 2025) and on macOS (issue #13801, Tauri 2.1.1, macOS 15.5, July 2025). Status of both: "needs triage" / unresolved.

2. **The correct approach for liquid-glass effects is NOT CSS `backdrop-filter` on a transparent Tauri window.** Use either:
   - **`window-vibrancy` crate** (official Tauri companion, Tauri-apps org): `apply_vibrancy()` on macOS (10.10+), `apply_mica()` on Windows 11, `apply_acrylic()` on Windows 10/11. This uses OS-native blur APIs, not CSS.
   - **In-content frosted glass**: add a semi-transparent background (`background: rgba(...)`) to the element using `backdrop-filter` — this sidesteps the transparent-window bug because the CSS backdrop has something to sample. Confirmed workaround in issues.
   - **Avoid** relying on `backdrop-filter` over the OS desktop (requires transparent window); use it only within-page where the backdrop is your own content.

3. **`window-vibrancy` caveats:**
   - `apply_blur` / `apply_acrylic` on Windows 11 build 22621+: bad perf during resize/drag.
   - `apply_mica` (Windows 11): no resize perf issues.
   - macOS: requires `"macOSPrivateApi": true` in tauri.conf.json.
   - Linux: unsupported; compositor-controlled.
   - CSS `html, body { background: transparent; }` required alongside `"transparent": true`.

**Source:** [window-vibrancy README](https://github.com/tauri-apps/window-vibrancy/blob/dev/README.md) [verified], GitHub issues #12437, #13801 [verified]

### B. CSS transforms and compositing

- **Safe composite properties everywhere:** `transform`, `opacity`, `filter` (blur/brightness), `clip-path`. Animate only these — they run on the GPU compositor on both WebView2 and WKWebView.
- **`will-change: transform`:** Promotes elements to their own layer. Use sparingly — over-use (e.g. every node in a 500-node SVG graph) causes layer memory exhaustion especially on WKWebView which sits inside Apple's compositing budget.
- **WKWebView uses Core Animation, not a dedicated compositor engine.** This means: when a requested feature isn't natively supported by Core Animation (e.g. non-1.0 `playbackRate`), WebKit silently drops GPU acceleration and falls back to main-thread rendering. Motion.dev disables hardware acceleration by default in WebKit for this reason; use their `allowWebkitAcceleration` opt-in only after testing.
- **CSS transitions on large surfaces (e.g. full-window blur or large transform groups):** WKWebView's composition pipeline is inside the WebKit process and cannot be driven from outside. Composition stalls show as dropped frames, not jank — harder to diagnose.

**Source:** [motion.dev animation performance tier list](https://motion.dev/magazine/web-animation-performance-tier-list) [verified], [CSS performance macOS issue #6577](https://github.com/tauri-apps/tauri/issues/6577) [verified]

### C. 60fps cap on macOS (WKWebView)

WKWebView on macOS 13–15 (Ventura–Sequoia) hard-caps `requestAnimationFrame` at 60fps regardless of display refresh rate. **macOS 26 removed the cap.** For users on 13–15:

- **`tauri-plugin-macos-fps`**: sets `PreferPageRenderingUpdatesNear60FPSEnabled = false` via WebKit's private `_features` API. Works on macOS 13–15; no-op on 26+. **Not App Store safe** — uses undocumented API. Falls back gracefully if API changes.
- For a pannable spatial map, 60fps is generally fine unless targeting 120Hz ProMotion displays. Assess before pulling in a private API dependency.

**Source:** [tauri-plugin-macos-fps](https://github.com/userFRM/tauri-plugin-macos-fps) [verified]

### D. SVG animation

- **SMIL (`<animate>`, `<animateMotion>`):** Not hardware accelerated anywhere. Avoid for animated neural-web lines.
- **CSS transform on SVG elements:** Chromium/WebView2 has full GPU-accelerated SVG transforms. WebKit's new SVG engine (LBSE) landed in WebKit 2024+; `transform` on SVG elements is now properly repainted but compositing support is not on par with Chromium.
- **Recommendation for neural-web SVG animations:** Use CSS custom properties + `transform`/`opacity` only. Animate via `@keyframes` or the Web Animations API (WAAPI). For line/path morphing, use JS-driven `d` attribute changes at rAF — not SMIL. Pre-promote animated layers with `will-change: transform` but only nodes that actually animate.
- **Canvas/WebGL:** Available on both WebView2 and WKWebView. For 100+ animated nodes, a Canvas 2D or WebGL layer beneath SVG label overlays is significantly more performant on WKWebView than pure SVG animation.

**Source:** [wpewebkit.org SVG engine status](https://wpewebkit.org/blog/05-new-svg-engine.html) [verified], [xyris.app SVG animation methods](https://xyris.app/blog/svg-animation-methods-compared-css-smil-and-javascript/) [verified]

### E. `mix-blend-mode`

- Supported on both WebView2 and WKWebView.
- **WebKit bug #176830:** Combining `mix-blend-mode` with `-webkit-backdrop-filter` on the same element produces unexpected results.
- Non-separable blend modes (`hue`, `saturation`, `color`, `luminosity`) can render differently or drop entirely on WebKit due to stacking context bugs.
- **Mitigation:** Avoid `mix-blend-mode` on the same element as `backdrop-filter`. Separate them into sibling layers. Prefer `multiply`, `screen`, `overlay` (separable modes) — more reliable across both engines.

**Source:** [WebKit bug 176830](https://bugs.webkit.org/show_bug.cgi?id=176830) [verified], search results [verified]

### F. Font rendering

WebView2 uses ClearType/DirectWrite (Windows). WKWebView uses Core Text (macOS). Font metrics can differ by 1–2px for the same CSS `font-size`. For a spatial map where node labels are positioned with absolute transforms, test that text doesn't overflow label bounds on both platforms with the same CSS.

### G. Scroll/gesture behaviour

WKWebView applies iOS-style momentum scrolling by default inside Tauri on macOS. For a pannable canvas implemented with `overflow: hidden` + pointer events, this is not directly an issue. But if any inner scroll container exists, add `-webkit-overflow-scrolling: touch` and `overscroll-behavior: contain` to prevent scroll bleed.

---

## 6. Gotchas a Frontier Model Gets Wrong About Tauri 2

1. **`@tauri-apps/api/tauri` no longer exists in v2** — it's `@tauri-apps/api/core`. Models trained on v1 examples will generate broken imports silently.
2. **`invoke_handler` can only be called once.** Calling it twice — e.g. to add commands in stages — means only the last set is registered. All commands must go into one `tauri::generate_handler![...]` macro call.
3. **No `Arc` wrapper around managed state** — Tauri does this. Double-wrapping with `Arc<Mutex<T>>` compiles but causes `State<'_, Arc<Mutex<T>>>` type mismatches if you access it as `State<'_, Mutex<T>>`.
4. **`anyhow::Error` can NOT be returned from commands** — requires a custom `Serialize` impl.
5. **Async commands must return `Result<T, E>`** — non-Result async commands compile but panic at runtime.
6. **`backdrop-filter` on a transparent Tauri window is broken** (both platforms, as of mid-2025). Using `window-vibrancy` is the correct path for OS-blur glass effects.
7. **WKWebView 60fps cap exists on macOS 13–15** — a spatial map with animation that looks smooth in Chrome dev tools will be capped at 60fps on macOS users' hardware until macOS 26 adoption grows.
8. **`withGlobalTauri` moved from `build` to `app` in v2** — models will put it under `build` based on v1 knowledge.
9. **Events have no return value and are not type-safe** — unlike commands, there is no TypeScript guarantee on event payload shape without manual discipline.
10. **Channel is new to Tauri 2** — v1-trained models may try to stream via repeated `emit()` calls (works but unordered, higher overhead).

---

## 7. WebKit-Safe Checklist for the Liquid-Glass Spatial Map

### AVOID

- `backdrop-filter` on a transparent Tauri window — broken both platforms [#12437, #13801]
- SMIL animations (`<animate>`, `<animateTransform>`) — no hardware acceleration anywhere
- Stacking `backdrop-filter` + `mix-blend-mode` on the same element — WebKit bug #176830
- Non-separable `mix-blend-mode` values (`hue`, `saturation`, `color`, `luminosity`) — unreliable on WKWebView
- Animating anything other than `transform`/`opacity`/`filter`/`clip-path` via JS/CSS — falls off compositor on WKWebView
- `will-change: transform` on every SVG node — layer budget exhaustion on WKWebView
- Assuming `requestAnimationFrame` runs at >60fps on macOS — use `tauri-plugin-macos-fps` if needed, accept App Store exclusion
- Multiple `backdrop-filter: blur()` layers stacked — compositing cost multiplies; each blur requires a separate GPU pass

### DO INSTEAD

- For OS-blur glass: use `window-vibrancy` crate (`apply_vibrancy` macOS, `apply_mica` Windows 11)
- For in-content frosted-glass panels: give the element a semi-opaque `background` so `backdrop-filter` samples your own content, not OS desktop
- For neural-web SVG animations: animate only `transform` and `opacity` via WAAPI or CSS keyframes; drive path morphing with rAF + `setAttribute('d', ...)`
- For 100+ animated nodes: prefer Canvas 2D or WebGL for the animation layer; overlay SVG only for static/labelled elements
- Promote only actively-animated elements with `will-change: transform`, remove it after animation ends
- Separate `mix-blend-mode` and `backdrop-filter` onto sibling elements, not co-located
- Test font metrics on both platforms — label bounding boxes may differ by 1–2px

---

## NEEDS-DOMAIN Flags

- `NEEDS-DOMAIN: caniuse.com` — backdrop-filter version support table (blocked by site policy)
- `NEEDS-DOMAIN: v2.tauri.app` — direct fetch returned redirect; all content verified via context7 mirror and official GitHub source instead

---

## Sources

- [Tauri 2 Calling Rust (commands, channels)](https://v2.tauri.app/develop/calling-rust/)
- [Tauri 2 Calling Frontend (events, channels)](https://v2.tauri.app/develop/calling-frontend)
- [Tauri 2 State Management](https://v2.tauri.app/develop/state-management/)
- [Tauri 2 IPC Concepts](https://v2.tauri.app/concept/inter-process-communication/)
- [Tauri 2 Vite Frontend Setup](https://v2.tauri.app/start/frontend/vite/)
- [Tauri 2 JS API Reference](https://v2.tauri.app/reference/javascript/api/)
- [Tauri Window Vibrancy](https://github.com/tauri-apps/window-vibrancy)
- [tauri-plugin-macos-fps](https://github.com/userFRM/tauri-plugin-macos-fps)
- [GitHub #12437: Inconsistent backdrop-blur on transparent window](https://github.com/tauri-apps/tauri/issues/12437)
- [GitHub #13801: backdrop-blur not matching Safari on macOS](https://github.com/tauri-apps/tauri/issues/13801)
- [GitHub #6577: CSS performance bad on macOS](https://github.com/tauri-apps/tauri/issues/6577)
- [WebKit bug #176830: mix-blend-mode + backdrop-filter](https://bugs.webkit.org/show_bug.cgi?id=176830)
- [DEV.to: Tauri IPC commands vs custom IPC](https://dev.to/hiyoyok/ipc-in-tauri-tauri-commands-vs-custom-ipc-what-to-use-when-2ab4)
- [tauritutorials.com: Error handling in Tauri](https://tauritutorials.com/blog/handling-errors-in-tauri)
- [motion.dev: Web Animation Performance Tier List](https://motion.dev/magazine/web-animation-performance-tier-list)
- [wpewebkit.org: New SVG engine status](https://wpewebkit.org/blog/05-new-svg-engine.html)
- [caniwebview.com: backdrop-filter support](https://caniwebview.com/features/web-feature-backdrop-filter/)
- [atrium.dev: From WKWebView to CEF](https://getatrium.dev/blog/embedding-real-browser-tauri)
