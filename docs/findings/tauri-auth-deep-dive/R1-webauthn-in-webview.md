# R1 — Does WebAuthn / Passkeys work inside a Tauri 2 webview? (late 2025 / 2026)

Research date: 2026-06-22. Question scope: `navigator.credentials.create()/get()` inside the
embedded webview each Tauri 2 platform ships (Windows = WebView2/Edge Chromium, macOS = WKWebView,
Linux = WebKitGTK); reachability of the platform authenticator (Windows Hello, Touch ID); known
issues + workarounds; maintained native Rust/Tauri plugins.

Confidence tags: [VERIFIED] = stated directly in a primary source; [LIKELY] = strongly implied /
multiple secondary sources agree; [UNCERTAIN] = thin or indirect evidence.

---

## VERDICT

WebAuthn is **not reliably usable through Tauri 2's embedded webview as a cross-platform feature**.
Tauri itself does not own a WebAuthn implementation — it inherits whatever the host OS webview gives
it, and those three engines differ sharply. The webview path is, in the words of the WebAuthn
ecosystem, "in the worst shape" of any client surface. The robust pattern is to **bypass the webview**
and drive the OS WebAuthn API natively (Rust crate over the Win32 / Apple / Linux-portal APIs) or
hand the ceremony to the system browser. [VERIFIED]

---

## 1. Per-platform: does `navigator.credentials.*` work in the webview?

### Windows — WebView2 (Edge Chromium): **WORKS (best case of the three)** [VERIFIED]
- WebView2 is Edge/Chromium and ships Chromium's full WebAuthn stack. Microsoft documents WebView2 as
  "capable of performing Windows Hello authentication, log in with FIDO keys, and more," and markets
  passwordless / passkey sign-in as a WebView2 scenario (Entra ID auth-flows GA, Windows 11).
  [VERIFIED]
- Confirmed live in the field: WebView2Feedback issue #5460 (opened **Dec 10 2025**) is a developer
  asking how to *disable* the Windows passkey-enumeration prompt that WebView2 shows during Google
  OAuth — i.e. WebView2 is actively invoking Windows Hello / the platform authenticator inside the
  webview. So on Windows the webview reaches the platform authenticator. [VERIFIED]
- Caveat: granular control over those prompts is limited, and behaviour can depend on the WebView2
  runtime version + Windows 11 build (24H2 added plugin-passkey-manager support to the underlying
  WebAuthn API). [LIKELY]
- **Tauri-specific caveat:** the open Tauri bug reports (below) are filed generically; the Windows
  path is the least-broken but has not been cleanly verified end-to-end *inside Tauri 2* in a primary
  source — treat "works in WebView2" as VERIFIED and "works in Tauri-on-Windows" as [LIKELY].

### macOS — WKWebView: **BROKEN / heavily restricted** [VERIFIED]
- Open Tauri bug **#6471** "[bug] macos m1, using webauthn through native navigator.credentials.create()
  is not allowed": `create()` fails with `NotAllowedError: Operation failed` inside Tauri on macOS
  while the identical page works in Safari and Chrome. Opened **2023-03-17**, still **open / needs
  triage**, no fix. [VERIFIED]
- Root cause is structural, not a Tauri bug per se: WKWebView is an *embedded* webview (EWV). Apple
  restricts WebAuthn in EWV so that **only passkeys for the linked RP-ID domain** (via Associated
  Domains / the app's own service) can be created or used — federated/3rd-party IdP passkeys are
  blocked, and the app needs the entitlement/association set up. Tauri apps generally serve from a
  custom `tauri://`/`asset` origin, not an HTTPS RP-ID with an associated-domains file, so the
  ceremony is disallowed. [VERIFIED for the EWV restriction; LIKELY for the Tauri-origin mismatch
  being the proximate cause]
- Apple's own guidance: for anything beyond your own first-party domain, use **`ASWebAuthenticationSession`**
  (the *system* webview / real browser), not WKWebView. [VERIFIED]

### Linux — WebKitGTK: **NO SUPPORT / effectively broken** [LIKELY]
- WebKitGTK exposes `WebKitAuthenticationRequest`, but that is **HTTP auth challenge** handling, not
  the `navigator.credentials` WebAuthn API. No primary source documents working
  `navigator.credentials.create()/get()` in WebKitGTK. [VERIFIED that the API surfaced in docs is HTTP
  auth, not WebAuthn]
- The Tauri WebAuthn discussion (#6601) explicitly shrugs at Linux ("🤷 😅") — there is no standard
  platform authenticator story; the nearest effort is the vendor-neutral `xdg-credentials-portal`
  (D-Bus portal) project, which is experimental. [VERIFIED — maintainer statement in #6601]
- Net: assume WebAuthn does not work in Tauri's Linux webview today. [LIKELY]

---

## 2. Can the embedded webview reach the platform authenticator (Windows Hello / Touch ID)?

- **Windows / WebView2: yes.** Documented + confirmed by the live #5460 enumeration-prompt behaviour —
  the webview talks to Windows Hello and FIDO2 keys. [VERIFIED]
- **macOS / WKWebView: only narrowly.** Touch ID *can* satisfy the user-verification step, but **only**
  when the passkey belongs to the app's own linked RP-ID domain (non-federated, associated-domains
  configured). For the general Tauri custom-origin case it is effectively unreachable, hence #6471's
  `NotAllowedError`. [VERIFIED for the restriction; LIKELY for "unreachable in practice for Tauri"]
- **Linux: no platform authenticator path** through WebKitGTK. [LIKELY]
- General industry framing (Corbado / passkeys.dev): WebViews run in the *calling app's* context, so
  the platform limits web-platform features and access to the local authenticator (Touch/Face ID,
  Windows Hello, Android biometrics) — native components are recommended over WebViews for passkeys.
  [VERIFIED — secondary, consistent across multiple sources]

---

## 3. Known issues, GitHub issues, workarounds

Open Tauri issues / discussions (all primary):
- **tauri-apps/tauri#6471** — macOS `navigator.credentials.create()` `NotAllowedError`. Open since
  2023-03-17, untriaged. [VERIFIED]
- **tauri-apps/tauri#7926** — "[bug] Allow Passkeys auth support in WebView" (reporter hit errors using
  Hanko passkeys in Tauri). Open since 2023-09-30, `needs triage`, no maintainer fix. [VERIFIED]
- **tauri-apps/tauri discussion#6601** — "FIDO2/U2F/WebAuthn". Maintainer (FabianLars, Jul 2024) on the
  Tauri authenticator plugin: *"we currently consider this plugin basically broken. It can serve as
  inspiration, but probably shouldn't be used as-is."* Lays out the per-platform native API map
  (Android Fido2ApiClient, Windows FIDO2 Win32 APIs, Apple ASWebAuthenticationSession) and the Linux
  gap. [VERIFIED]

Workarounds (ordered most→least robust):
1. **Drive the OS WebAuthn API natively from Rust, bypassing the webview** — a Tauri command (IPC) that
   calls the platform authenticator directly and returns the assertion to JS. Best cross-platform-ish
   path on Windows (Win32 WebAuthn API has clean Rust bindings — see §4). [LIKELY — recommended pattern,
   not a turnkey plugin]
2. **Hand the ceremony to the system browser** — open the RP's login URL in the real default browser
   (on macOS via `ASWebAuthenticationSession`; elsewhere via `open`/`xdg-open` or a loopback redirect),
   complete WebAuthn there, then deep-link / loopback back into the Tauri app with the result. This is
   the standard "auth in system browser, not webview" pattern and side-steps every webview limitation.
   [VERIFIED as the recommended approach by Apple + general guidance]
3. **macOS only:** configure Associated Domains + serve your own HTTPS RP-ID so WKWebView's
   first-party-only WebAuthn is permitted — narrow, brittle, federated IdPs still blocked. [LIKELY]

---

## 4. Maintained Tauri plugin / Rust crate exposing platform WebAuthn natively?

- **No maintained, turnkey `tauri-plugin-*` for passkeys/WebAuthn.** The official Tauri authenticator
  plugin (v1 + v2) is declared "basically broken" by a maintainer and should not be used as-is.
  [VERIFIED — discussion #6601]
- **Rust crate that *does* exist and is maintained: `webauthn-authenticator-rs`** (kanidm project,
  the same group behind the widely-used server-side `webauthn-rs`). It is the *client/authenticator*
  half and **includes bindings for the Windows 10+ WebAuthn (Win32) API**, plus CTAP2 transports for
  roaming keys. This is the building block for the §3-option-1 native bypass on Windows. [VERIFIED —
  crates.io / docs.rs]
  - Limitation: its native *platform-authenticator* binding is strongest on **Windows**; macOS/Linux
    platform-authenticator coverage via this crate is weaker (CTAP/roaming-key focus, plus the OS APIs
    differ). [LIKELY]
- `webauthn-rs` (kanidm) is **server-side only** (relying-party verification) — relevant if Artemis is
  also the RP, but it does not help the *client* webview ceremony. [VERIFIED]
- Linux: `xdg-credentials-portal` is the nearest native effort; experimental, not production-ready.
  [VERIFIED as existing; UNCERTAIN on maturity]

---

## CONFIDENCE — overall & biggest unknown

Overall **HIGH** that the webview path is unreliable cross-platform and that the native-bypass /
system-browser pattern is the right answer. The structural reasons (EWV RP-ID restriction on Apple,
no WebAuthn in WebKitGTK, Chromium-complete on WebView2) are well-attested.

Biggest unknown: **the exact, current end-to-end behaviour of WebAuthn *inside Tauri 2 specifically*
on Windows 11 24H2 with a recent WebView2 runtime** — WebView2-the-engine clearly supports it, but I
found no primary source that cleanly verifies a Tauri 2 app completing a Windows Hello passkey
ceremony in-webview (the Tauri bugs are generic/untriaged). Worth a 30-min spike before committing to
an in-webview Windows path. Secondary unknown: maturity of `webauthn-authenticator-rs`'s
platform-authenticator support on macOS.

---

## KEY SOURCES (with dates)

1. tauri-apps/tauri **discussion #6601** — FIDO2/U2F/WebAuthn; maintainer "plugin basically broken"
   (Jul 2024), per-platform native API map, Linux gap. https://github.com/tauri-apps/tauri/discussions/6601 — 2024–2025 [VERIFIED, current]
2. tauri-apps/tauri **issue #6471** — macOS `navigator.credentials.create()` NotAllowedError, open/untriaged.
   https://github.com/tauri-apps/tauri/issues/6471 — opened 2023-03-17, still open (stale but unresolved)
3. tauri-apps/tauri **issue #7926** — Allow Passkeys auth in WebView, open/needs-triage.
   https://github.com/tauri-apps/tauri/issues/7926 — opened 2023-09-30 (stale but unresolved)
4. MicrosoftEdge/WebView2Feedback **issue #5460** — disabling passkey enumeration in WebView2 (proves
   WebView2 invokes Windows Hello in-webview). https://github.com/MicrosoftEdge/WebView2Feedback/issues/5460 — 2025-12-10 [VERIFIED, fresh]
5. Microsoft Learn — WebAuthn APIs for passwordless on Windows (Win32 WebAuthn API; 22H2 ECC, 24H2
   plugin passkeys). https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/webauthn-apis — current
6. crates.io — **webauthn-authenticator-rs** (Windows 10 WebAuthn API bindings, CTAP2).
   https://crates.io/crates/webauthn-authenticator-rs — current
7. Corbado — "Why are WebViews a challenge for passkeys" / passkeys.dev macOS reference (EWV RP-ID-only
   restriction; ASWebAuthenticationSession = system webview).
   https://www.corbado.com/blog/native-app-passkeys ; https://passkeys.dev/docs/reference/macos/ — 2024–2025 [VERIFIED, secondary]
