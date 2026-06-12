# Multiplatform Swift Client — Adding a Native macOS Surface (2026)

_Research date: 2026-06-12 · macOS 26 / iOS 26 / Xcode 26 era · Swift 6_
_Context: Artemis thin SwiftUI client (currently universal iOS, XcodeGen, shared SPM package `ArtemisKit` + app target `ArtemisApp`). Goal: end-state native on Mac + iPhone + iPad, one codebase, three surfaces, "Athena-style" desktop assistant._

> Sourcing note: where Apple's own docs/forums are cited they are authoritative. Some specifics (esp. SecAccessControl `.or` fallback behaviour on Touch-ID-less Macs) are not definitively documented by Apple and are flagged as such — these warrant a DTS incident or a quick spike on real hardware before they are locked into a spec.

---

## Q1 — Multiplatform target structure (2026)

### (a) Single multiplatform target with Destinations vs (b) separate macOS target

Since Xcode 14 a single app target can carry multiple **Destinations** (iPhone, iPad, Mac, and also tvOS/watchOS/visionOS), conditionally including code, resources, dependencies and build settings per platform. This is now the default and recommended shape for a new SwiftUI app that ships **one product across iPhone, iPad and Mac from a common codebase**. ([Swift Dev Journal — Xcode Multiplatform App Targets](https://www.swiftdevjournal.com/xcode-multiplatform-app-targets/), [Apple — Configuring a multiplatform app target](https://developer.apple.com/documentation/xcode/configuring-a-multiplatform-app-target))

A **separate macOS target** is the recommended structure when any of these is true:
- You charge per-platform / ship as distinct App Store products.
- You distribute the Mac build **outside the App Store** (our case — see Q4).
- The Mac surface diverges enough (different scenes, lifecycle, large amounts of Mac-only UI) that a shared target's `#if` density would hurt maintainability.

Apple's own guidance: "Use separate targets if you plan to sell a Mac version of your app outside the App Store." ([Swift Dev Journal](https://www.swiftdevjournal.com/xcode-multiplatform-app-targets/))

**For Artemis:** the *logic* is already isolated in the platform-agnostic `ArtemisKit` SPM package, so the target question is purely about the thin app shell. Because the Mac build is Developer-ID / outside-App-Store, and because an "Athena-style" assistant wants a Mac-specific scene graph (menu-bar item + floating panel — Q2) that the phone/tablet build does not, a **separate `ArtemisMac` app target sharing `ArtemisKit`** is the cleaner structure than forcing one target to host two very different `App` scene bodies. Both targets depend on the same SPM package; only the thin SwiftUI shell + scene wiring differs.

> Net: this is a "(b) with a shared package" recommendation, but it is a soft call. If the Mac UI ended up nearly identical to the iPad UI, a single multiplatform target would be equally valid. The deciding factor is the divergent Mac scene graph, not the business logic.

### Native macOS (AppKit-backed SwiftUI) vs Mac Catalyst vs "Designed for iPad on Mac"

| Option | What it is | Native feel | 2026 status |
|---|---|---|---|
| **Native SwiftUI on macOS** | SwiftUI compiled to the AppKit backend; real Mac controls, windows, menus | **Best** native feel for a new app | Apple's recommended path for new multiplatform apps |
| **Mac Catalyst** | UIKit/iPad app brought to Mac via the Catalyst runtime | "iPad-like"; closer-but-not-native; needs extra work to feel Mac-native | **Not deprecated**, but positioned as a *bridge for existing UIKit/iPad apps*, not the path for new SwiftUI apps |
| **"Designed for iPad" on Mac** | Unmodified iPad binary run on Apple Silicon | Lowest effort, least native; an iPad app in a Mac window | Fallback only; not a "real Mac app" |

Apple Developer Forums, "The State of Mac Catalyst in 2026": Catalyst is **not deprecated** but Apple's recommendation is explicit — *"I don't see the advantage of using Mac Catalyst for a new SwiftUI app project. SwiftUI supports both iOS and Mac so you can share a lot of the same code and provide a native Mac experience."* Many Apple apps still ship on Catalyst (Music, Podcasts, Maps, Messages, FaceTime) precisely because they were originally UIKit/iOS apps. ([Apple Forums — State of Mac Catalyst in 2026](https://developer.apple.com/forums/thread/811728), [Pilky.me — Catalyst vs SwiftUI](https://pilky.me/catalyst-vs-swiftui/), [Doran Gao — Native macOS, SwiftUI, and Mac Catalyst](https://medium.com/@dorangao/native-macos-swiftui-and-mac-catalyst-the-3-apple-app-models-every-developer-should-understand-017e1fbff4eb))

The owner wants "a real Mac app, not a website / not an iPad app." Since Artemis has **no UIKit legacy** (it is SwiftUI from day one), there is zero migration pull toward Catalyst. **Native SwiftUI (AppKit-backed) is unambiguously the right choice.** Drop to AppKit (`NSViewRepresentable`, `NSPanel`, `NSStatusItem`) only for the few Mac behaviours SwiftUI doesn't yet express well (Q2's floating panel is the main one).

### XcodeGen expression of a macOS destination / target + platform-conditional settings

XcodeGen supports two shapes, mirroring the target decision above:

- **Multiplatform single target** — use `supportedDestinations` on the target (each entry `auto`-resolves its platform); per-platform deployment targets via `Project.options.deploymentTarget` or `Target.deploymentTarget`. Note community-reported rough edges with `supportedDestinations` + per-destination deployment targets — verify generated settings. ([XcodeGen ProjectSpec.md](https://github.com/yonaskolb/XcodeGen/blob/master/Docs/ProjectSpec.md), [XcodeGen #1577](https://github.com/yonaskolb/XcodeGen/issues/1577), [#1437](https://github.com/yonaskolb/XcodeGen/issues/1437))

- **Separate macOS target (recommended for Artemis)** — a distinct target with `platform: macOS`, its own `deploymentTarget`, and a shared SPM dependency on `ArtemisKit`:

```yaml
# project.yml (illustrative)
options:
  deploymentTarget:
    iOS: "26.0"
    macOS: "26.0"

packages:
  ArtemisKit:
    path: ./ArtemisKit

targets:
  ArtemisApp:            # existing iPhone+iPad
    type: application
    platform: iOS
    sources: [Sources/iOS, Sources/Shared]
    dependencies:
      - package: ArtemisKit

  ArtemisMac:            # new native Mac surface
    type: application
    platform: macOS
    sources: [Sources/macOS, Sources/Shared]
    settings:
      base:
        ENABLE_HARDENED_RUNTIME: YES
        CODE_SIGN_IDENTITY: "Developer ID Application"
        PRODUCT_BUNDLE_IDENTIFIER: com.artemis.mac
    dependencies:
      - package: ArtemisKit
```

Platform-conditional **build settings** in XcodeGen use the `[sdk=...]` settings-condition suffix or are simply scoped to the per-platform target. Per-platform deployment targets live under `options.deploymentTarget`. ([XcodeGen Project Spec](https://yonaskolb.github.io/XcodeGen/Docs/ProjectSpec.html), [Dave DeLong — Conditional Compilation Pt 4](https://davedelong.com/blog/2022/05/15/conditional-compilation-part-4-deployment-targets/))

### `#if os(macOS)` discipline (view layer only)

- **`ArtemisKit` stays platform-agnostic** — networking, auth, DTOs, vault. No `#if os` in the package except where a platform API genuinely differs (and even then prefer protocol abstraction over scattered conditionals). The keychain/SE/LAContext code does need *some* conditional handling (Q3), but keep it behind one well-named type, not sprinkled.
- **`#if os(macOS)` lives in the app/view layer** — scene graph (MenuBarExtra/Window vs WindowGroup), `NSPanel`/`NSStatusItem` bridges, menu commands, window styling. This is exactly the "view-layer only" discipline the owner asked about.
- Prefer **separate Sources/macOS and Sources/iOS folders** for whole divergent views over inline `#if` blocks inside a shared view body; reserve inline `#if` for small leaf differences (a toolbar placement, a control style). This keeps diffs surgical and the shared logic clean.

---

## Q2 — Mac form-factor for an always-available assistant ("Athena-style")

Three SwiftUI scene primitives, and they **coexist**:

- **`MenuBarExtra`** (SwiftUI, macOS 13+) — a menu-bar icon with either a `.menu`-style dropdown or a `.window`-style popover (`MenuBarExtra(...) { ... }.menuBarExtraStyle(.window)`). Ideal for the always-available, low-friction "summon the assistant" entry point. Automatic popover dismissal. Good for a compact chat/ask surface. ([Nil Coalescing — Build a macOS menu bar utility in SwiftUI](https://nilcoalescing.com/blog/BuildAMacOSMenuBarUtilityInSwiftUI/), [Daniel Saidi — Customizing the macOS menu bar in SwiftUI](https://danielsaidi.com/blog/2023/11/22/customizing-the-macos-menu-bar-in-swiftui))

- **`WindowGroup` / `Window`** — `Window` (single, unique window; macOS 13+) is the right primitive for a singleton main assistant window; `WindowGroup` is for user-spawnable multiple windows (less apt for a single-instance assistant). Pair with `.windowStyle(.hiddenTitleBar)` for a clean chrome-light look, and a `Settings { }` scene for preferences (the standard ⌘, panel). ([Nil Coalescing — Scenes types in a SwiftUI Mac app](https://nilcoalescing.com/blog/ScenesTypesInASwiftUIMacApp/), [Create with Swift — Understanding scenes](https://www.createwithswift.com/understanding-scenes-for-your-macos-app/))

- **Global-hotkey floating panel** — the "Spotlight-for-your-assistant" experience (⌥-Space to summon a floating prompt) is **not well served by `WindowGroup`+`openWindow`**: as of recent macOS it misbehaves with Spaces/Mission Control/full-screen and doesn't reliably float on top. The idiomatic approach is **`NSStatusItem` + a custom `NSPanel`** (`.nonactivatingPanel`, `level = .floating`, `collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]`, `hidesOnDeactivate = false`), hosting SwiftUI via `NSHostingView`. Register the global hotkey with **Sindre Sorhus's `KeyboardShortcuts` package** (wraps `RegisterEventHotKey`, ships a SwiftUI recorder), in `applicationDidFinishLaunching`. ([Fazm — SwiftUI menu bar app with floating window: best practices](https://fazm.ai/blog/swiftui-menu-bar-app-floating-window-best-practices), [Ardent Swift — Spotlight-like hotkey window](https://ardentswift.com/posts/hotkey-window/))

**Coexistence & recommendation:** Yes — a single Mac app can present a `MenuBarExtra` **and** a `Window`/`Settings` scene **and** an `NSPanel` simultaneously. The idiomatic 2026 shape for an always-available desktop assistant:
- **`MenuBarExtra(.window)`** as the persistent, always-there home (live status + quick ask).
- A **global-hotkey `NSPanel`** for instant summon-from-anywhere (the "Athena" feel).
- A **`Window`** (`.hiddenTitleBar`) for the full conversation/history surface, plus a **`Settings`** scene.
- Set `LSUIElement = YES` if Artemis should be menu-bar-only with no Dock icon (typical for an ambient assistant); otherwise keep the Dock icon and the main Window.

---

## Q3 — macOS auth portability (paired-device SE + biometric model)

**Short answer: the core model ports cleanly — same `SecKey` / Secure Enclave / `LAContext` APIs on Apple-Silicon Macs (Touch ID) as on iPhone (Face ID) — with three real caveats: (1) the "don't name the wrong modality" UX rule, (2) `kSecAttrAccessGroup` / app-group differences, and (3) the Mac Mini-with-no-Touch-ID case, which needs an explicit fallback.**

### Same on both?

- **Secure Enclave P-256 keypair:** identical. The only user-app data the SE stores is a 256-bit EC private key; it's generated in and never leaves the SE; you hold only the public key + a `SecKey` reference usable after auth. Same on iOS and Apple-Silicon macOS. ([Apple Forums — Secure Enclave and TouchID](https://developer.apple.com/forums/thread/50511), [Alexei Gridnev — Secure Enclave-stored keys](https://medium.com/@alx.gridnev/ios-keychain-using-secure-enclave-stored-keys-8f7c81227f4))
- **Biometric signing via `LAContext` + `SecKey`:** same APIs. `kSecUseAuthenticationContext` lets you pass a pre-authenticated `LAContext` so a single biometric gesture authorizes the key operation without a second prompt — works on both platforms. `LAContext.biometryType` returns `.faceID` / `.touchID` / `.opticID` / `.none`, so the same code adapts at runtime. ([App Security in Swift — Keychain, Biometrics, Secure Enclave](https://medium.com/@gauravharkhani01/app-security-in-swift-keychain-biometrics-secure-enclave-69359b4cffba))

### `SecAccessControl` flags

- Build with `SecAccessControlCreateWithFlags(...)`. For an SE signing key gated by biometrics: `[.privateKeyUsage, .biometryCurrentSet]`, paired with `kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly` (or `...WhenUnlockedThisDeviceOnly`).
- **`.biometryCurrentSet`** binds the key to the *currently enrolled* biometric set — re-enrolling a face/finger invalidates it (good for security; the key effectively self-destructs on tamper). `.biometryAny` survives enrollment changes. ([Apple — biometryCurrentSet](https://developer.apple.com/documentation/security/secaccesscontrolcreateflags/biometrycurrentset), [Apple — privateKeyUsage](https://developer.apple.com/documentation/security/secaccesscontrolcreateflags/privatekeyusage))
- **`.or .devicePasscode` fallback gotcha:** combining `[.biometryCurrentSet, .or, .devicePasscode]` is the documented way to allow passcode/login-password as an alternative to biometrics — **but** an Apple Forums thread (Feb '25) reports the `.or` evaluating as a *sequential* (biometric **then** passcode) prompt in some configurations rather than true alternatives. `[.userPresence, .or, .devicePasscode]` reportedly does **not** work as hoped. This is exactly the path the Mac Mini case depends on, so **verify on real hardware**. ([Apple Forums — SecAccessControlCreateWithFlags `.or` behaviour](https://developer.apple.com/forums/thread/122531))

### Keychain access groups / `kSecAttrAccessible`

- `kSecAttrAccessible*` constants are the same. Use a `...ThisDeviceOnly` variant so the credential never migrates via iCloud Keychain or backup — correct for a per-device paired key.
- **`kSecAttrAccessGroup` differs:** on macOS, keychain access groups depend on the app being **signed with a provisioning profile / keychain-access-groups entitlement**, and the legacy "file-based" macOS keychain vs the **data-protection keychain** behave differently. To get iOS-identical behaviour you must opt the Mac app into the **data-protection keychain** (`kSecUseDataProtectionKeychain = true`) — otherwise SE/biometric items and access-group semantics don't match iOS. This is the single biggest portability footgun. ([Apple — Local Authentication](https://developer.apple.com/documentation/localauthentication), [Apple — Accessing Keychain Items with Face ID or Touch ID](https://developer.apple.com/documentation/LocalAuthentication/accessing-keychain-items-with-face-id-or-touch-id))

### `LAContext` reuse

Same pattern both platforms: create + retain one `LAContext`, optionally `evaluatePolicy` it, then pass it as `kSecUseAuthenticationContext` to `SecItemCopyMatching` / key operations so the user isn't re-prompted. `touchIDAuthenticationAllowableReuseDuration` lets a recent auth satisfy subsequent operations within a window.

### The Mac-Mini-without-Touch-ID case (the real blocker to resolve)

- All Apple-Silicon **laptops** have built-in Touch ID; all Apple-Silicon Macs work with a **Magic Keyboard with Touch ID**. A **Mac Mini with a plain keyboard has no biometric at all.** ([Eclectic Light — Passkeys and biometrics](https://eclecticlight.co/2022/09/18/last-week-on-my-mac-passkeys-and-biometrics/))
- A purely-`.biometryCurrentSet` SE key on such a Mac **cannot be authorized** — there is no biometric to satisfy it. To let the Mini participate you must include a **passcode/login-password fallback** (`.or .devicePasscode`) at key-creation time, accepting the `.or` evaluation quirk above. Apple's `LAPolicy.deviceOwnerAuthentication` (vs `...WithBiometrics`) already falls back to the login password when no biometric exists — use that policy for the `LAContext` evaluation on Mac.
- Apple does **not** publicly document the exact fallback behaviour of an SE key created with biometric-only flags on a biometric-less Mac. **Flag for a DTS incident or a hardware spike** before locking the spec.

**Reuse-the-iOS-code verdict:** the `ArtemisKit` auth layer is ~90% portable. Budget for: (1) opt into the data-protection keychain on macOS; (2) a Mac code path that creates the SE key with a `.devicePasscode` fallback and uses `deviceOwnerAuthentication` policy (so the Touch-ID-less Mini works via login password); (3) modality-aware prompt strings (`biometryType`); (4) verifying the `.or` fallback UX on real hardware. Keep all four behind one `AuthService` abstraction in `ArtemisKit`, not scattered `#if os`.

---

## Q4 — Personal-use Mac distribution

For a self-built app the owner runs on **their own Macs** (not App Store):

- **Sign with a Developer ID Application certificate** ($99/yr Apple Developer Program) and **notarize** (`xcrun notarytool submit` → staple). Since macOS 10.15, non-App-Store apps must be signed **and** notarized to launch without the user manually overriding Gatekeeper. ([Apple — Developer ID](https://developer.apple.com/developer-id/), [Apple — Notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution), [Xojo — Code Signing on macOS Pt 3, 2026](https://blog.xojo.com/2026/03/24/code-signing-on-macos-what-developers-need-to-know-part-3/))
- **Ad-hoc / no Developer ID alternative:** for *truly* personal machines you can run an **ad-hoc signed** (or unsigned) build and clear quarantine manually (`xattr -d com.apple.quarantine`, or right-click → Open). This avoids the $99 program but means every move/update re-triggers Gatekeeper friction and you **cannot reliably use a stable keychain-access-group / provisioning-profile entitlement** — which the SE/biometric keychain item (Q3) benefits from. For an assistant holding a paired SE key + vault, **Developer ID + notarization is the recommended path**; ad-hoc is the fallback if avoiding the program fee.
- **Hardened Runtime:** required for notarization; enable it. Then declare only the entitlements actually needed:
  - **Keychain Sharing** entitlement (`keychain-access-groups`) — for the data-protection keychain group used by `ArtemisKit`.
  - **Secure Enclave / biometrics:** no special entitlement beyond a valid signing identity; SE key creation works under Hardened Runtime once signed.
  - **Network client** (`com.apple.security.network.client`) — for the Tailscale-tunnel HTTP API.
  - If you adopt the **App Sandbox** (optional outside the App Store), you additionally need the network-client sandbox entitlement; sandbox is **not required** for Developer-ID distribution, so for a personal appliance you may skip it to reduce friction. ([Apple — App code signing process](https://support.apple.com/guide/security/app-code-signing-process-sec3ad8e6e53/web), [rsms — macOS distribution gist](https://gist.github.com/rsms/929c9c2fec231f0cf843a1a746a416f5))

---

## Recommendation (for the Artemis CLIENT specs)

1. **Structure:** Keep `ArtemisKit` as the platform-agnostic SPM core. Add a **separate native macOS app target `ArtemisMac`** (not a single multiplatform target), sharing `ArtemisKit`, because (a) the Mac build is Developer-ID/outside-App-Store and (b) the Mac scene graph diverges (menu-bar + floating panel). Use **native SwiftUI (AppKit-backed)** — never Catalyst (no UIKit legacy to migrate) and never "Designed for iPad." Confine all `#if os(macOS)` to the view/scene layer; prefer `Sources/macOS` vs `Sources/iOS` folders over inline conditionals.

2. **Mac form factor:** `MenuBarExtra(.window)` as the always-available home + a global-hotkey **`NSPanel`** (via `NSStatusItem` + `NSHostingView`, hotkey via Sindre Sorhus `KeyboardShortcuts`) for the Athena-style summon-from-anywhere + a singleton `Window` (`.hiddenTitleBar`) for full history + a `Settings` scene. They coexist in one app. Consider `LSUIElement` for a Dock-iconless ambient presence.

3. **Auth:** The SE-P256 + `LAContext` model ports to Apple-Silicon Macs ~as-is, but spec must handle four deltas behind one `AuthService`: opt into the **data-protection keychain** (`kSecUseDataProtectionKeychain`); add a **`.devicePasscode` / login-password fallback** + `deviceOwnerAuthentication` policy so the **Touch-ID-less Mac Mini can authenticate**; **modality-aware** prompt strings via `biometryType`; and **verify the `.or` fallback UX on real hardware** (Apple's `.or` evaluation has a documented quirk).

4. **Distribution:** Personal-use Mac build → **Developer ID + notarization + Hardened Runtime**, entitlements limited to **Keychain Sharing + network-client** (skip App Sandbox for a personal appliance). Ad-hoc/unsigned is a viable but friction-heavy fallback only if avoiding the $99 program.

5. **Open items to resolve before the Mac client spec is "ready":** (i) confirm SE-key fallback behaviour on a Touch-ID-less Mac (DTS incident or hardware spike — the Mini is exactly this case); (ii) confirm `.biometryCurrentSet .or .devicePasscode` prompts as a true alternative, not sequential, under macOS 26; (iii) decide single-target vs separate-target once the Mac UI fidelity to iPad is known (recommendation above assumes meaningful divergence).
