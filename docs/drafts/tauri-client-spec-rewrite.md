# Tauri client spec-rewrite — planning capture

_Tracking doc for the ADR-028 CLIENT spec-rewrite pass (7 new Tauri specs + 2 Python amendments).
Created 2026-06-24 (planning). Source of truth for the carve + the cross-cutting decisions settled
in the decisions pass. Delete once all 7 specs reach `docs/changes/` (status: ready)._

## Sources (locked design)
- **ADR-028** §Refinement — the 7-spec carve + functional-cluster default + user-arrange/persist + WebKit-safe.
- **ADR-025** — client↔brain auth (custom P-256 challenge-response; native FFI: Win CNG/TPM, mac SE; recovery passphrase). Brain-side verifier + session model + host DEK-wrap **survive**.
- **ADR-023** — Tauri platform (React/Tailwind/Vite + Rust; `.exe` now → `.app` later).
- **app-flow.md** — connection/lock state machine + map navigation + per-domain lock rules (re-authored for the map).
- **design-brief.md** — Holo Tactical tokens, 16-cell ambient theming, neural-web SVG, forbidden patterns.
- **Mockup (feel = source of truth):** `docs/research/mockups/travel-zoom-workspace.html` (canonical impl of map + neural web; DOM/CSS/SVG, WebKit-safe — NOT WebGL).

## Cross-cutting decisions (settled 2026-06-24, decisions pass)

1. **Client-only carve (resolved by planning — defaults-not-menus).** The 7 new Tauri specs are CLIENT-ONLY (TS/React/Rust). The old `CLIENT-a`/`CLIENT-b` are **brain-side Python** (`app_auth.py`, `api_app.py`) and **survive as their own specs** — the Tauri client is a new consumer of the same `/app/*` surface. The carve's "Replaces c+b / a+broker" column is loose shorthand. Mixing a Python-server build and a Rust/TS-client build in one spec is disallowed (wave-grouping + one-concern-layer).
   - `CLIENT-a` needs a **small ADR-025 amendment**: signature-encoding normalization (client sends raw `r‖s` on Windows / DER on macOS → brain `SignedKeypairVerifier` accepts the pinned form). The `CLIENT-broker` host key-primitive change (SE→TPM) is an M2/host concern, not client.

2. **Layout persistence = brain-synced, end-state now (owner).** User-arranged map layout persists to the brain (every paired device shows the same arrangement). Adds:
   - `/app/layout` GET/PUT + an **owner-private layout store** on the brain → **CLIENT-b amendment** (Python).
   - `LayoutDTO` + layout-sync client → **CLIENT-core**.
   - **Lock-tier = session-gated** (`require_session`, NOT `require_unlocked`) — the map must function in `Connected·Vault-locked`; card positions aren't secret-tier. _(Flag for apex-security spec review: positions-over-session acceptable.)_
   - **Conflict = last-writer-wins**, server-stamped `updated_at`. Single owner, near-zero concurrent-arrange conflict → no merge machinery.

3. **Spec the full end-state; build gates the tails (owner).** CLIENT-card defines a **per-domain content contract for all ~10 domains**; CLIENT-screens specs every detail view against its `/app/<domain>` read contract. Build wires **Review + Status + Calendar + Tasks** now (backends exist); the rest (Gmail, Finance, Health, Travel, Memory, Knowledge, People) are built **against contract + fake, live-gated** (standard Artemis pattern — cf. M8-a Task 7, FakeParser). No backend detour in this milestone.

4. **Stack coverage = author `apex-tauri` skill first (owner).** Before drafting, run apex-skill-author to create a reusable `apex-tauri` SKILL.md + impl.md (incl. Verification Recipe), bind it into `stack_skills` per the ADR-001 coverage gate. Covers: Rust/Tauri shell, WebKit-safe rendering, native crypto FFI (CNG/TPM/SE), React/Vite webview. Then draft the 7 specs against it. (apex-frontend covers the React half; apex-accessibility/ui-ux-design/animation dispatched at review.)

## The carve (post-decisions)

| # | Spec | Wave | Scope |
|---|------|------|-------|
| 1 | **CLIENT-core** | W1 | Tauri scaffold (React/Tailwind/Vite + Rust) · gateway HTTP/SSE client · connection/lock state machine · DTOs **+ LayoutDTO + layout-sync client** |
| 2 | **CLIENT-theme** | W1 | Holo Tactical tokens · WebKit-safe liquid-glass · 16-cell ambient (season×time) resolver · bundled-photo loader (gradient fallback) |
| 3 | **CLIENT-auth** | W2 | Device P-256 keypair · native FFI (Win CNG/TPM Platform Crypto Provider · mac SE) · pairing · connect/unlock · recovery passphrase (ADR-025; build-time spikes gated) |
| 4 | **CLIENT-world** | W2 | World plane · camera (pan/zoom/travel + rubber-band) · functional-cluster default layout **· user-arrange + brain-synced persist** · Home/Esc recenter · dock · minimap · neural-web SVG |
| 5 | **CLIENT-card** | W3 | Glance→detail expand-morph (top-most over dimmed map) + collapse-back **· per-domain content contract (all ~10 domains)** · no internal scroll |
| 6 | **CLIENT-screens** | W4 | Concrete detail content: Review (recipes + GATE pending) · Status **· all ~10 domain views vs per-domain `/app` contracts** (build wires Calendar/Tasks; rest fake+gated) |
| 7 | **CLIENT-ask** | W4 | Floating Ask-Artemis pop-up (⌥Space) · chat/SSE streaming |
| + | **CLIENT-a amend** | Py | ADR-025 signature-encoding normalization |
| + | **CLIENT-b amend** | Py | `+ /app/layout` GET/PUT + owner-private layout store (session-gated) · `+ /app/calendar` `/app/tasks` read endpoints · document per-domain read contract for the rest |

## Brain-side `/app/*` base — prerequisite track (added 2026-06-24)
**Non-obvious gap surfaced 2026-06-24:** the brain-side HTTP surface the Tauri client codes against is **entirely unbuilt** — no `src/artemis/api_app.py`, no `identity/app_auth.py`, no broker. The old `CLIENT-a`/`CLIENT-b`/`CLIENT-broker` are *ready specs that were never built* (the cluster build never reached them; "CLIENT awaits the rewrite"). They survive the Tauri rewrite (decision 1 — they're platform-agnostic Python/Swift), but they must be **built** for any end-to-end test. This is a **separate track from the 7-spec client carve** (different file trees: `src/artemis/` Python vs `client/` Tauri → parallel-safe), and it is the gate for **Milestone B (end-to-end)**, not Milestone A (client shell vs a mocked brain).

| Track item | Stack | Build status | Action |
|---|---|---|---|
| **CLIENT-a** (`app_auth.py`: device registry · challenge-response sessions · `require_session` · scope-from-session) | Python | ready, **unbuilt** | Build + apply the **ADR-025 signature-encoding** amendment (accept raw `r‖s` / DER → pinned form). Dev-buildable (FastAPI + fakes). |
| **CLIENT-b** (`api_app.py`: pairing/session/unlock-relay/review/status routes · `main.py` wiring · `tailscale serve`) | Python | ready, **unbuilt** | Build + apply the amendments: `+ /app/layout` GET/PUT (session-gated, owner-private store, LWW) · `+ /app/calendar` `/app/tasks` read endpoints · document the per-domain read contract for the rest. Dev-buildable with fakes; the live broker pairing relay + `tailscale serve` are Mac-gated. |
| **CLIENT-broker** (broker `pair` IPC verb) | Swift | **Mac-gated** | Real pairing relay needs the Mini; **dev uses a fake broker** (the established off-hardware pattern; M2-c sqlcipher shim covers the DEK side). |

The two **"+ amend"** rows in the carve table above are these specs' amendments — they fold into building the unbuilt base (amend-then-build), not standalone edits.

## Path to first testing (two milestones)
- **Milestone A — client shell vs a mocked brain:** MSVC toolchain + build **CLIENT-core + CLIENT-theme + CLIENT-world + CLIENT-auth** (auth real co-located Hello, or stubbed). First "see the map move" moment; no brain-side build needed (fake `invoke` responses).
- **Milestone B — end-to-end (pair → unlock → ask → real Review/Status/domain data):** Milestone A **+** the brain-side base track above **+** a running brain with a responder model (`dev-model-stack-ollama` [ready, unbuilt] or cloud-Codex) **+** the ADR-025 Windows-Hello/TPM signer spikes (real-hardware).
- **Recommended first-testing vertical slice (minimum for a real loop on the Windows box):** `CLIENT-core` + `CLIENT-theme` + `CLIENT-world` + `CLIENT-auth` (client) **+** `CLIENT-a` + `CLIENT-b` (brain, with amendments) **+** a dev model. Domain screens, the Mac/SE path, and gated spokes come after.

## Drafting plan (AFK, dependency-ordered waves)
- **Pre-req:** author `apex-tauri` skill (decision 4) → bind into `stack_skills`. ✅ DONE 2026-06-24 (v1.0.0; Rust recipe tick pending MSVC).
- **W1:** CLIENT-core · CLIENT-theme. ✅ DONE — `status: ready` (reviewed + gate-passed; ADR-030 written).
- **W2:** CLIENT-auth · CLIENT-world. ✅ DONE — `status: ready` (security/tauri/a11y reviewed + gate-passed).
- **W3:** CLIENT-card. ✅ DONE — `status: ready`.
- **W4:** CLIENT-screens · CLIENT-ask. ✅ DONE — `status: ready` (CLIENT-screens folds the locked Calendar/Tasks/Projects/Gmail/**Finance** detail designs). **All 7 client specs ready.**
- **Brain-side base track (parallel, Python — see § above):** build CLIENT-a (+ sig-encoding amendment) · build CLIENT-b (+ layout + per-domain read endpoints amendment). Independent file tree (`src/artemis/`) → can build alongside the client-spec drafting; the gate for Milestone B end-to-end testing. Sequence CLIENT-b's DTO/route shapes with CLIENT-core's DTOs (same wire contract).
- Each spec: Deep Details template → dispatched domain review (apex-tauri + apex-frontend + apex-accessibility + apex-ui-ux-design/animation as relevant; apex-security/auth for CLIENT-auth + the CLIENT-b layout endpoint) → readiness gate → `docs/changes/`.

## Parked / build-phase (not blocking the spec rewrite)
- 7 draft palette cells hand-tune (design-brief matrix) · exact world-plane sizing / responsive bounds · fonts pass · 16 bundled photo-background assets sourcing (theme spec codes the loader + gradient fallback; assets land later).

## Micro-decisions deferred to draft-time (defaults-not-menus)
- Client state-management lib (lean default at CLIENT-core draft) · exact render approach = **locked by the mockup** (DOM transforms + SVG + backdrop-filter, WebKit-safe) · ADR-025 signature-encoding pin (a build-time spike already in ADR-025).

## ▶ BUILD ORDER — for the coding session (added 2026-06-24)
**What's MSVC-gated vs not** — the key sequencing lever:
- **Buildable WITHOUT MSVC (do these first):** the entire **brain-side** (`CLIENT-a`/`CLIENT-b`, Python) + the entire **client FRONTEND** (TS/React — `CLIENT-core`'s TS DTO/facade/state layer + `theme`/`world`/`card`/`screens`/`ask`). The frontend runs in a browser via `npm run dev` with the Tauri `invoke` layer **mocked**, and `tsc`/`vite build`/`vitest` all pass without the Rust toolchain.
- **Needs MSVC (gated tail):** `CLIENT-core`'s **Rust gateway** (`cargo check`), `CLIENT-auth`'s **native FFI keystore plugin** (cargo + CNG/TPM/SE), and the full `tauri build` / integration. Install `winget … VCTools` + `rustup default stable-msvc` to unblock.

**Build waves (dependency + file-overlap order):**
1. **Brain-side (Python, parallel track):** `CLIENT-a` (+ ADR-025 sig-encoding amendment) → `CLIENT-b` (+ `/app/layout` + 5 per-domain read endpoints). Dev-buildable now (fakes for the Mac-gated broker). *Real-wired reads:* calendar/tasks/projects; *fake-gated:* gmail (docling), finance (FIN unbuilt).
2. **`CLIENT-core`** — scaffold + `domains.ts` + DTO/error/gateway + connection/layout state. (Rust gateway compile = MSVC; TS layer = now.)
3. **`CLIENT-theme`** (file-disjoint from core; parallel) — tokens/ambient/photo-bg/neural-web.
4. **`CLIENT-auth`** (MSVC-gated FFI) ∥ **`CLIENT-world`** (frontend) — both after core (auth touches `lib.rs`/`Cargo.toml`/`capabilities`; world touches `App.tsx`). Serialize each after core.
5. **`CLIENT-card`** — after world (touches `App.tsx`/`WorldPlane.tsx`).
6. **`CLIENT-screens`** ∥ **`CLIENT-ask`** — after card/core (screens fills card's registry; ask touches `App.tsx`/`lib.rs`).

**Serialization edges (NOT file-disjoint — build in order, no parallel clobber):** core → {auth, world} → card → {screens, ask}; auth+ask both touch `src-tauri/{lib.rs,Cargo.toml,capabilities}` → serialize.
**cross_model_review:** `CLIENT-core` + `CLIENT-auth` (auth/transport) — second-family review before shipping.
**First runnable target (Milestone A):** core+theme+world+card+screens+ask frontend in a browser (mocked invoke) → the map shell + domain overlays, no MSVC. **Milestone B (end-to-end):** + brain-side built + MSVC + a dev model (`dev-model-stack-ollama`).
