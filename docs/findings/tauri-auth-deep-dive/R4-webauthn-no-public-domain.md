# R4 — WebAuthn / passkeys for a self-hosted service over a private network (no public domain)

**Question:** Can WebAuthn / passkeys be used by a self-hosted "brain" reached over a private
network (Tailscale tailnet, LAN, or localhost) that has **no public registrable domain**, as of
late 2025 / 2026? The client is a **Tauri desktop app** talking to an always-on server over a
Tailscale tunnel (MagicDNS `host.tailnetNNNN.ts.net`, raw `100.x.y.z`, or `localhost`).

**Researched:** 2026-06-22. Tags: [VERIFIED] = stated by primary/spec source; [LIKELY] =
strong secondary consensus; [UNCERTAIN] = inferred or thinly sourced.

---

## TL;DR verdict

Real WebAuthn is **theoretically viable** over Tailscale because `*.ts.net` gives you a genuine
registrable domain with valid public TLS — but in **this specific topology (Tauri WebView client)
it is fragile-to-broken in practice**, for two independent reasons:

1. **Tauri's WebView origin is not your server's URL.** The WebView runs at `tauri://localhost`
   (macOS/Linux) or `http://tauri.localhost` (Windows), not `https://host.tailnetNNNN.ts.net`.
   WebAuthn validates the **origin** against the RP ID, and Tauri WebViews have known, unresolved
   problems invoking `navigator.credentials` at all.
2. **RP-ID binding is brittle across the URL changes this project expects** (localhost in dev →
   `ts.net` later → `mac.local`). A passkey registered under one RP ID will not work under another
   unless they're in a subdomain relationship or you run Related Origin Requests (which needs a
   `.well-known/webauthn` served from the RP-ID domain).

For a single-user, Tailscale-reached brain with a desktop client, a **custom challenge-response**
(server holds a public key, client signs a server-issued nonce with a locally-stored private key)
sidesteps every one of these constraints and is the more robust choice. See §6.

---

## 1. RP ID rules

[VERIFIED] **The RP ID must be a domain string. It cannot be an IP address, and it cannot be a
public suffix (eTLD).** It must be the page's effective domain or a *registrable* parent of it
(eTLD+1 or higher). Source: W3C WebAuthn L2/L3 §RP ID; web.dev "RP ID deep dive"; Corbado RP ID
article.
- web.dev RP ID deep dive — https://web.dev/articles/webauthn-rp-id (current as of 2025)
- W3C WebAuthn L3 — https://www.w3.org/TR/webauthn-3/

[VERIFIED] **Raw IP as RP ID → no.** The spec requires a domain; `navigator.credentials.create()`
with an IP-string RP ID fails. This is an open, acknowledged gap for IP-only internal networks.
Source: w3c/webauthn issue #1358 ("Could not use Webauthn PublicKeyCredential.create when the RP ID
is a Host string (ip)") — https://github.com/w3c/webauthn/issues/1358 (2020, still open/unresolved).
**→ A raw `100.x.y.z` Tailscale IP is NOT a usable RP ID.**

[VERIFIED] **`localhost` is a special case via secure-context, not via RP-ID rules.** WebAuthn is
gated on a *secure context*; `http://localhost` is treated as a secure context by browsers, so
local dev works with RP ID = `localhost`. Note the spec-discussion nuance: there's a long-standing
argument that `127.0.0.1` is the more technically-correct secure-context loopback than the
hostname `localhost`. Source: w3c/webauthn issue #1204 — https://github.com/w3c/webauthn/issues/1204;
MDN "secure contexts".

[VERIFIED — and the key finding for this project] **`*.ts.net` is on the Public Suffix List.**
`ts.net` itself is a *public suffix* (that's exactly why one tailnet's cookies can't leak into
another tailnet — browsers consult the PSL). Consequences:
- `ts.net` → public suffix → **cannot** be an RP ID (it's an eTLD).
- `tailnetNNNN.ts.net` → eTLD+1 → **this is the registrable domain and CAN be an RP ID.** [VERIFIED that ts.net is PSL-listed; LIKELY that tailnetNNNN.ts.net is therefore a valid eTLD+1 RP ID — follows directly from PSL semantics but not separately doc-tested.]
- `myhost.tailnetNNNN.ts.net` → the page's full domain; valid as RP ID, and may also set
  RP ID = `tailnetNNNN.ts.net` (a registrable parent).
- Source: publicsuffix/list (PSL repo); Tailscale "tailnet name" docs (format `tailnetNNNN.ts.net`);
  multiple PSL explainers confirming Tailscale uses the PSL for per-tailnet cookie isolation.
  - https://github.com/publicsuffix/list/blob/main/public_suffix_list.dat
  - https://tailscale.com/kb/1217/tailnet-name

So **the `ts.net` MagicDNS name does help**: unlike a `.local` mDNS name or a raw IP, it is a real
registrable domain you can use as an RP ID. The catch is the *client origin* (§2, §5).

---

## 2. Secure-context requirement & Tailscale TLS

[VERIFIED] WebAuthn requires a **secure context**: HTTPS, or the loopback exceptions
(`localhost` / `127.0.0.1`). Source: MDN; W3C spec.

[VERIFIED] **Tailscale issues genuine, publicly-trusted TLS certs for `*.ts.net` via Let's Encrypt**
(DNS-01 challenge; Tailscale writes the `_acme-challenge` TXT under your `*.ts.net`). You enable
MagicDNS + HTTPS Certificates, then `tailscale cert` / `tailscale serve`. The cert is a normal
LE cert chaining to a public root — a browser sees it as valid. Private key never leaves your node.
- Source: Tailscale "Enabling HTTPS" — https://tailscale.com/docs/how-to/set-up-https-certificates
- Source: Tailscale "Tailscale Serve" — https://tailscale.com/docs/features/tailscale-serve

[VERIFIED] **So a *browser* visiting `https://myhost.tailnetNNNN.ts.net` gets a real secure context
with a valid origin** → WebAuthn's secure-context + origin checks are satisfied there. This is the
"good news" path and is how the homelab community runs HTTPS without owning a domain
(e.g. XDA "enabled HTTPS without owning a domain with Tailscale", Home Assistant + Tailscale TLS
guides).

[VERIFIED — the catch for a Tauri client] A **Tauri WebView is not a browser at that URL.** Its
`window.location.origin` is `tauri://localhost` (macOS/Linux) or `http://tauri.localhost`
(Windows; `useHttpsScheme` can force `https://tauri.localhost`). WebAuthn's origin check compares
*that* origin to the RP ID — it has no relation to `myhost.tailnetNNNN.ts.net`. Sources:
- Tauri v2 config / "Localhost" plugin docs — https://v2.tauri.app/plugin/localhost/
- Tauri discussion "How to set a custom Origin" #4912 — https://github.com/tauri-apps/tauri/discussions/4912
- Custom-scheme origin-validation failures (`tauri://`) — e.g. openclaw#46520, Appwrite "Invalid Scheme … (tauri://localhost)".

---

## 3. Tauri WebView WebAuthn support (practical blocker)

[VERIFIED] **Browser-style `navigator.credentials.create/get()` inside a Tauri WebView is broken /
inconsistent across platforms today.** The WebView does not reliably expose the platform FIDO2/
passkey APIs, and origin/secure-context handling for the custom scheme compounds it.
- tauri#7926 "[bug] Allow Passkeys auth support in WebView" (open) — https://github.com/tauri-apps/tauri/issues/7926
- tauri#6471 "using webauthn through native navigator.credentials.create() is not allowed" (macOS) — https://github.com/tauri-apps/tauri/issues/6471
- tauri discussion #6601 "FIDO2/U2F/WebAuthn" — https://github.com/tauri-apps/tauri/discussions/6601

[LIKELY] **Workaround = a native plugin, not the WebView.** `tauri-plugin-webauthn` (community)
calls the OS FIDO2/WebAuthn API from Rust and is "a nearly drop-in replacement for
`@simplewebauthn/browser`", with the **extra requirement that you pass the origin URL explicitly**
to register/authenticate. https://github.com/Profiidev/tauri-plugin-webauthn
- This means: to do real WebAuthn in Tauri you bypass the WebView, drive the native API from Rust,
  and *hand it the origin/RP ID yourself* — i.e. you become responsible for the origin string the
  WebView can't supply correctly. Workable, but it's bespoke plumbing, single-platform-tested, and
  community-maintained.

---

## 4. How real self-hosted apps handle passkeys on private deployments

Common pattern across all of them: **one RP ID = your canonical access domain, pinned at setup;
changing the URL breaks every registered passkey.**

- **Vaultwarden** [VERIFIED]: `DOMAIN` env var must exactly match the external HTTPS URL; passkeys
  are scoped to it. Community thread explicitly requests detaching `DOMAIN` from the WebAuthn
  `rp_id` because changing the domain invalidates passkeys — dani-garcia/vaultwarden discussion
  #6567 ("DOMAIN and rp_id should detach in webauthn context"). Requires HTTPS for anything beyond
  localhost. https://github.com/dani-garcia/vaultwarden/discussions/6567
- **Kanidm** [VERIFIED]: the strictest. `origin` must match or be a descendant of the configured
  `domain`, **or the server refuses to start**. Docs: "Changing the domain value WILL break many
  types of registered credentials … WebAuthn and OAuth"; you must run `kanidmd domain rename`.
  GitHub #645 confirms domain rename historically didn't update `rp_id` as users expected.
  https://kanidm.github.io/kanidm/stable/server_configuration.html ;
  https://github.com/kanidm/kanidm/issues/645. (Kanidm authors `webauthn-rs`, the Rust WebAuthn lib
  — https://github.com/kanidm/webauthn-rs — which enforces origin/RP-ID strictly by design.)
- **Home Assistant** [LIKELY]: WebAuthn/passkey support exists; same RP-ID-pinning caveat — moving
  from a `.local` name / IP / Nabu Casa URL to another breaks passkeys unless subdomain or ROR.
  HA discussion #2519 (passkey selector); web.dev ROR article cited as the mitigation.
- **Immich / Nextcloud / Authelia** [UNCERTAIN for passkey specifics]: searches surfaced mostly
  their **OIDC/OAuth** integration rather than first-party passkey RP-ID guidance. Authelia is
  itself an IdP (it would own the RP ID); Immich/Nextcloud more commonly delegate auth to an
  OIDC provider on a stable domain than expose passkeys on a shifting self-hosted URL. Treat
  "they do passkeys directly on a private URL" as unconfirmed.

**Universal pitfalls reported:** (a) RP-ID mismatch → "relying party ID is not a registrable
domain suffix of, nor equal to the current domain" error; (b) reverse proxy not forwarding the
`Host` header → origin/RP-ID mismatch; (c) `localhost` vs `127.0.0.1` vs LAN-IP inconsistency;
(d) changing the access URL silently bricking all enrolled passkeys.

---

## 5. URL-change fragility (the core gotcha for this project)

[VERIFIED] **A passkey is bound to the RP ID at registration.** A credential registered under RP ID
`A` is unusable at RP ID `B`. The only escape hatches:
1. **Subdomain relationship** — a credential with RP ID = `tailnetNNNN.ts.net` keeps working when
   the page moves to any `*.tailnetNNNN.ts.net` host (RP ID may be the page domain *or a
   registrable parent*). So *within one tailnet*, moving between device hostnames is survivable if
   you set RP ID to the tailnet eTLD+1. [VERIFIED rule; LIKELY as applied to ts.net.]
2. **Related Origin Requests (ROR)** — host `https://<rp-id>/.well-known/webauthn` listing the
   allowed origins. Lets one RP ID accept multiple unrelated origins. web.dev ROR —
   https://web.dev/articles/webauthn-related-origin-requests ; passkeys.dev ROR.
   Sources: web.dev RP-ID + ROR; Duende "RP ID & origin" deep dive (2025-10-14).

**This project's planned URL journey is exactly the failure case:**
`localhost` (dev) → `myhost.tailnetNNNN.ts.net` (Tailscale) → `mac.local` (LAN/mDNS) are **three
different registrable domains** (`localhost`, `tailnetNNNN.ts.net`, `local`). None is a subdomain
of another. ROR can't fully rescue it either, because `localhost` and `*.local` aren't HTTPS
public-suffix domains that can host a trusted `.well-known/webauthn` for the `ts.net` RP ID.
**→ Passkeys enrolled in dev or on the LAN name would break when switching to the Tailscale name,
and vice-versa.** Mitigation would be to *standardize on the `ts.net` RP ID everywhere* (always
reach the brain via its MagicDNS name, even on the same LAN) — but that still leaves the Tauri
WebView origin problem from §2/§3 unsolved.

---

## 6. Bottom line / recommendation signal

[Assessment, grounded in the above]

**Real WebAuthn over Tailscale is *possible* but a poor fit for this exact topology**, because:
- The one genuinely-good piece (`*.ts.net` = real registrable domain + valid LE TLS) only helps a
  **real browser**. The **Tauri WebView origin** is `tauri://localhost` / `http://tauri.localhost`,
  which doesn't match the `ts.net` RP ID, and Tauri WebView passkey support is openly broken
  (tauri#7926, #6471). Doing it properly means a **native Rust FIDO2 plugin where you hand-feed the
  origin** — bespoke, single-platform-tested, community-maintained.
- The project's deliberate URL mobility (localhost ↔ ts.net ↔ mac.local) is precisely what
  RP-ID binding punishes; there is no clean subdomain/ROR mitigation spanning all three.
- IP-only access (`100.x.y.z`) is flatly unsupported as an RP ID.

**A custom challenge-response auth scheme avoids all of this:**
- It has **no RP-ID / origin / secure-context dependence** — the transport is already
  Tailscale-encrypted (WireGuard) and the cert is valid, so you're not re-deriving phishing
  resistance from the browser origin model.
- The client (Tauri/Rust) generates a keypair once, registers the public key with the brain, and
  on each login signs a server-issued random nonce (e.g. Ed25519). The brain verifies the
  signature. This is **URL-agnostic**: it works identically on `localhost`, `ts.net`, `mac.local`,
  or a raw IP, and survives every access-URL change.
- You keep most of WebAuthn's security properties that matter *for a single-user private service*
  (possession of a hardware/OS-protected private key, replay-resistant via nonce) without the
  parts that don't fit (RP-ID domain binding designed for the open web's anti-phishing problem,
  which Tailscale's network identity already addresses).
- Caveat: you own the crypto correctness (nonce freshness, signature verification, key storage in
  OS keychain/secure enclave, no nonce reuse). That's real work, but bounded and topology-stable.

**Signal: lean toward a custom challenge-response (or, if hardware-backed phishing-resistance is a
hard requirement, a native FIDO2 plugin pinned to a single `ts.net` RP ID with the brain always
reached by its MagicDNS name) rather than browser-WebAuthn-in-the-WebView.** The latter is the most
fragile option for a Tauri-over-Tailscale brain.

---

## Sources (with dates / staleness)

- W3C WebAuthn L3 — https://www.w3.org/TR/webauthn-3/ (current spec) [VERIFIED]
- web.dev "RP ID deep dive" — https://web.dev/articles/webauthn-rp-id [VERIFIED, ~2024-25]
- web.dev "Related Origin Requests" — https://web.dev/articles/webauthn-related-origin-requests [VERIFIED]
- w3c/webauthn #1358 (IP not allowed as RP ID) — https://github.com/w3c/webauthn/issues/1358 [VERIFIED; open since 2020 — STALE-but-unresolved, still accurate]
- w3c/webauthn #1204 (localhost vs 127.0.0.1) — https://github.com/w3c/webauthn/issues/1204 [VERIFIED]
- Tailscale "Enabling HTTPS" — https://tailscale.com/docs/how-to/set-up-https-certificates [VERIFIED]
- Tailscale "tailnet name" (format tailnetNNNN.ts.net) — https://tailscale.com/kb/1217/tailnet-name [VERIFIED]
- publicsuffix/list (ts.net is a public suffix) — https://github.com/publicsuffix/list [VERIFIED]
- tauri#7926 passkeys in WebView (open) — https://github.com/tauri-apps/tauri/issues/7926 [VERIFIED]
- tauri#6471 navigator.credentials.create not allowed (macOS) — https://github.com/tauri-apps/tauri/issues/6471 [VERIFIED]
- Profiidev/tauri-plugin-webauthn — https://github.com/Profiidev/tauri-plugin-webauthn [LIKELY, community plugin]
- Tauri "Localhost" plugin / origin docs — https://v2.tauri.app/plugin/localhost/ [VERIFIED]
- Kanidm server config (origin must descend from domain; rename breaks creds) — https://kanidm.github.io/kanidm/stable/server_configuration.html [VERIFIED]
- kanidm/kanidm #645 (domain rename ≠ rp_id) — https://github.com/kanidm/kanidm/issues/645 [VERIFIED]
- vaultwarden discussion #6567 (DOMAIN vs rp_id) — https://github.com/dani-garcia/vaultwarden/discussions/6567 [VERIFIED]
- Duende "Deep dive: RP ID & origin with passkeys" — https://duendesoftware.com/blog/20251014-deep-dive-into-relying-party-id-and-origin-with-passkeys (2025-10-14) [LIKELY]
- Corbado "WebAuthn RP ID & Passkeys" + "Origin validation in native apps" — https://www.corbado.com/blog/webauthn-relying-party-id-rpid-passkeys [LIKELY]

### Biggest unknowns
- Whether `tailnetNNNN.ts.net` is accepted as an RP ID in a *real browser* test was not
  empirically run — it follows from PSL semantics ([LIKELY], not [VERIFIED] end-to-end).
- Exact current state of `tauri-plugin-webauthn` across macOS/Windows/Linux (community plugin,
  maturity/maintenance unverified).
- First-party passkey (not OIDC) behaviour of Immich/Nextcloud/Authelia on shifting private URLs
  was not confirmed.
