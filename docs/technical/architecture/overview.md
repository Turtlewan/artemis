<!-- aligned 2026-06-11 to ADR-012/013 + contracts.md; amended 2026-06-11 per doc cleanup (spec count + spoke wave); status/ADR-index refreshed 2026-06-26 (Windows-build reality; ADR-029…032). Body subsystem sections (agentic/reactions/sensitivity) refresh is carried in status.md Open Questions. -->
# Artemis — System Overview

_Status: **design map current; build status refreshed 2026-06-26.** The architecture below is locked across ADR-001…032.
**Most of the corpus is now BUILT** — the dev-buildable queue (core spine M0–M7 + OBS + DR + the M8 Gmail/Calendar/Productivity
spoke wave + Finance + reactions runtime + sensitivity wall + the agentic executor engine + the Tauri client behind a mocked
invoke + the Windows voice-dev twin) was implemented and host-verified on the **Windows/WSL2 dev box** by **Codex (`gpt-5.5`)**
as coder (ADR-026, supersedes the earlier "DeepSeek-on-the-Mini" handoff plan). Only **Mac- / MSVC- / Tauri-gated tails** remain
unbuilt in `docs/changes/` (see § Build status). This is the platform map — every subsystem, its boundary,
and how they connect — at altitude; depth lives in the linked ADRs, [`brain.md`](./brain.md),
[`data-model.md`](./data-model.md), [`app-flow.md`](./app-flow.md), and the per-module docs under
[`../modules/`](../modules/). Build order is in [`../../../ROADMAP.md`](../../../ROADMAP.md)._

Artemis is a **private personal command center** — a Jarvis-in-spirit assistant for the owner (+ light access
for trusted people in physical vicinity), with a RAG-heavy "second brain" as its knowledge subsystem. Voice +
text co-equal; reacts <1s; **local-first, no owner data in the cloud**; runs on a dedicated Mac Mini appliance
(M4 Pro 48GB, ADR-001; 64GB re-decision WWDC-pending). One owner today; the identity/scope seams are built so a
guest/multi-person wall drops in later without reworking the brain.

---

## Architecture shape — hub-and-spoke behind a security wall

The **brain is the hub** (not a peer module). Everything else is a ring around it: **interaction surfaces** the
owner touches, **domain modules** (the spokes) with their **connector layer**, and **cross-cutting concerns**
baked into every layer. A **cryptographic security wall** (the M2 key broker + per-scope encrypted vault) sits
under the whole core — owner data is unreadable until a phone-attested unlock releases the key.

```
                          ┌───────────────────────────────────────────────┐
   Interaction surfaces   │  voice (M5) · native iPhone/iPad client (CLIENT)│
   (capture + render)     │  · remote access (Tailscale private tunnel)     │
                          └───────────────────┬─────────────────────────────┘
                            authenticated app API  ·  scope resolved from session, never the client (ADR-010)
                          ┌───────────────────▼─────────────────────────────┐
                          │              ◆ CORE — the brain                  │
                          │  Gateway → Brain (router-first) → Tools/Recipes  │
                          │  → Heartbeat.  Knowledge layer (RAG) · bitemporal│
                          │  memory · ingestion · tool/recipe registry ·     │
                          │  identity/scoping · teacher & curiosity loop.    │
                          │                  (see brain.md)                  │
                          └───┬───────────────────────────────────────┬──────┘
            tool calls (live) │                                       │ push (knowledge + facts)
            ─ exact facts ──▶ │                                       │ ◀─ searchable text
                          ┌───▼───────────────┐             ┌─────────▼──────────┐
   Domain modules (spokes)│ Calendar · Tasks · │     …       │ (later spokes:     │
   own / mirror truth     │ Projects · Habits  │             │  Finance · Health…)│
   per-domain (ADR-011)   └───┬────────────────┘             └─────────┬──────────┘
                              │ connectors (translate external → contract; untrusted text quarantined)
                          ┌───▼──────────────────────────────────────────────▼────┐
   Integration layer      │  Google (Calendar/Gmail) · Telegram · Home Assistant · │
   (NOT modules)          │  wearables · Weather   — egress allowlisted (ADR-009)  │
                          └────────────────────────────────────────────────────────┘
  ── Security wall (M2): per-scope SQLCipher + encrypted volume, DEK released only on phone unlock (ADR-005) ──
  Cross-cutting (every layer):  security/key-broker · observability (ADR-008) · backup/durability · token-frugality
```

## Data flow — hybrid (LOCKED 2026-06-03)
Each module **owns or mirrors its operational data** (per-domain, ADR-011) and exposes it via **typed tools**
(the brain calls them live for exact/current facts), AND **pushes searchable knowledge** (summaries, extracted
text, events) into the **central knowledge layer** + **facts into memory** for recall + cross-module reasoning.
- **Exact/live question** ("how much did I spend on groceries this month?") → brain calls the module tool live.
- **Reasoning/recall question** ("patterns across spending, calendar, health?") → brain searches the central index + memory.
- Exact facts stay correct + un-duplicated (module = system of record); fuzzy connect-the-dots stays fast (one
  place to search). Ownership governs only where the record lives + who may write it — **awareness is identical
  whether a domain is owned or mirrored** (ADR-011).

---

## ◆ The security wall & key model (M2 — the spine's gate)
The load-bearing security architecture. Specified across **ADR-005** (key broker), **ADR-006** (two-tier
proactivity), **ADR-007** (encrypted vault), **ADR-010** (client auth). The M2-d apex-security gate is a hard
BLOCK on M3/M4 — no sensitive store is built until the wall passes.

- **Per-scope encryption.** Each person's data lives in a **per-scope SQLCipher DB + a per-scope encrypted
  volume** (the LanceDB doc index + memory DB), each behind a 32-byte DEK. Cryptographic isolation — a guest
  physically lacks the owner's key. Strictly stronger than FileVault (which unlocks once at boot, zero owner↔guest separation).
- **Remote-attested key broker.** A minimal, hardened **LaunchAgent** is the only process that touches the
  Secure-Enclave key; it exposes a tiny local IPC to the brain. DEKs are **ECIES-wrapped to an SE key**;
  ciphertext on disk, SE private key non-exportable. The Mini has **no Touch ID** → biometric originates on the
  **owner's iPhone**: Face ID → a **fresh-nonce + monotonic-counter signed assertion** over the Tailscale tunnel
  → broker verifies (counter strictly increasing = replay-blocked) → unwraps the DEK → hands the brain a
  **transient, mlock'd, session-only** key. Neither DEK nor biometric ever crosses the wire.
- **One unlock opens the whole per-scope vault** — broker mounts the encrypted volume (docs + memory) and
  releases the SQLCipher DEK together (ADR-007 refines ADR-005). **Unlock-once-per-session**, idle re-lock.
- **Two-tier proactivity (ADR-006).** **Tier-0** (always-on, even while locked) touches only a deliberately
  minimised, mostly-derived, read-mostly corpus (calendar/weather/derived flags) under a separate small
  **proactive key**. **Tier-1** (real owner data) runs only in an unlocked session — otherwise it **queues for
  the next session**. Resolves always-on proactivity vs "key only when unlocked."
- **⭐ Irreducible core risk:** a prompt-injected tool exfiltrating the live DEK from the brain during a session.
  Mitigated by keeping the DEK in a native crypto boundary the model/tool layer can't address, scoped tool I/O,
  and egress filtering — the deepest apex-security focus.
- **Brain = LaunchDaemon** (per ADR-002), holds only a transient session DEK; **broker = LaunchAgent** under
  owner **auto-login** (so it reloads after a power cut — auto-login does *not* unlock data).

## ◆ Core — the brain (the hub)
Specified in [`brain.md`](./brain.md). Router-first reactive loop; deterministic/automation path → local
responder → escalate to a heavier/cloud model only on need. One-line responsibilities:
- **Gateway** — voice/text/app ingress; resolves person + scope **from the authenticated session, never from a
  request parameter** (ADR-010); attaches owner/guest scope before routing.
- **Brain** — router-first; `respond_stream` (sentence streaming) + `pre_route` (Tier-pre-serve gate) back-fills
  feed voice (M5) + the Tier gate.
- **Tool + recipe registry** — module **manifests** indexed for RAG-for-tools; internal = local typed calls,
  MCP at edges; self-taught **recipes** (M7) live alongside tools.
- **Identity & scoping** — owner full / guests light; voice-ID = identity *not* auth; the crypto wall is the
  real boundary. `data_scope` on a module (`owner-private | guest-visible | shared`) is the **sensitivity Tier
  source of truth** — M5's voice Tier gate reads it; there is no separate `sensitive` flag.

## ◆ Memory engine — the owner-memory store + cross-module entity backbone (M4, ADR-004 · ADR-013)
A **custom bitemporal `MemoryStore`** on a **per-person SQLCipher file + sqlite-vec** (chosen over Mem0/Graphiti:
only a custom store satisfies SQLCipher-at-rest + bitemporal + small-model robustness + per-person partition
together; both runner-ups are documented upgrades). Distinct from the document RAG corpus.
- **Two stores** — episodic (TTL noise-control) + semantic facts (decay re-rank, never hard-delete).
- **Bitemporal** four-timestamp pattern (`valid_from/to`, `tx_from/to`); `as_of` recall; non-destructive UPDATE
  = close interval + insert.
- **A.U.D.N. write path** — extract atomic facts → semantic search existing → local reasoner emits
  **ADD / UPDATE / DELETE / NOOP** under **constrained decoding**, **cardinality-aware** (SINGLE relations
  key on `(subject, relation)`; MULTI on `(subject, relation, object)` so values coexist; registry defaults
  MULTI = never-overwrite fail-safe).
- **Decay, not deletion** — composite `recency × access × salience` score as a surface-time re-rank multiplier;
  owner-driven purge is the only hard delete. **Auto-inject** ranked current facts into each turn's prompt.
- **A-MEM** note metadata (`keywords`, `contextual_description`, `linked_ids`) for multi-hop recall; full
  provenance + owner view/edit (a normal bitemporal UPDATE) / purge.
- **Cross-module entity backbone (ADR-013).** M4 is also the canonical entity registry — not a separate
  Contacts module (privacy: it already lives owner-private behind the M2 wall). Homes three entity types:
  **Person · Place · Goal**. Other spokes reference a person by the stable **`person_fact_key`** (no ad-hoc
  strings) and resolve cross-module refs via a **`memory.resolve_entity`** tool through the ToolRegistry —
  never cross-store joins. (Build: a deferred **M4-c amendment** spec adds the tool + key + Place/Goal schema.)

## ◆ Knowledge layer — the second brain (M3, ADR-007)
Adaptive RAG over the document/"second-brain" corpus. **Sensitive → LanceDB inside the per-scope encrypted
volume** (LanceDB OSS can't encrypt at rest; the volume is the workaround), mounted by the broker on unlock —
document search is **Tier-1 (unlock-gated)**.
- **Ingestion:** per-source connectors → normalized `Document` → Docling parse → **late chunking** (+ Contextual
  Retrieval for high-value) → embed (**Qwen3-Embedding-0.6B**) → LanceDB (dense + FTS). **Idempotent via
  `content_hash`**; provenance + locator (page/timestamp/bbox) on every chunk.
- **Retrieval (adaptive, behind `retrieve(query, mode)`):** default = hybrid (vector + BM25) + **RRF** +
  **Qwen3-Reranker**; complex/connect-the-dots = **agentic multi-hop** (query-time iterative loop, no upfront
  graph). **Knowledge graph = gated build-time spike** (LightRAG vs agentic on a personal gold-set; agentic
  stays default until a graph earns its extraction cost).
- **Visual-document understanding** (locked): Apple Vision OCR + Qwen3-VL scene description + **ColQwen2.5 Light
  via PyTorch MPS 2.5.1** visual retrieval.

## ◆ Teacher & recipe loop — self-improvement (M7, ADR-003)
How Artemis learns new capabilities without a human writing code. ("Recipe" = a self-taught capability; the
project's term for what other systems call a learned skill.)
- **Escalate → distill → replay.** When the local brain can't handle a request it **escalates to the cloud
  teacher** (Claude Opus via subscription — "teaches the method, never sees sensitive data"; non-sensitive,
  quota-capped); the successful method is **distilled into a signed recipe** stored on the per-scope volume and
  **replayed locally** next time. M7-a1 (format/store/signing) · M7-a2 (escalate/distill/replay + brain seam) ·
  M7-a3 (dedupe/retire).
- **Promotion policy + Review surface (M7-b).** A new recipe's safety class gates how it ships: **auto-safe**
  (private/self-only) enables silently; **gated** (`TAKES_ACTION` — anything leaving the owner's boundary or
  touching other people) **parks PENDING until the owner approves it on the CLIENT Review screen** (IG1=B —
  this is the *only* owner-approval surface; not ntfy actions).
- **Curiosity loop (M7-c).** Idle-time gap-scan over telemetry → a `Researcher` fills the gap from the open web
  (the Deep-Research engine below), behind a **grounding gate** (≥2 independent reachable sources, never
  self-generated) + hard token caps.

## ◆ Untrusted content + Deep Research (DR, ADR-009)
The security envelope for everything the system reads from the outside world, and the engine that reads it.
- **`artemis.untrusted` (DR-a, reusable).** Spotlighting + a **dual-LLM quarantine**: a **Quarantined-LLM**
  reads raw untrusted content with **no tools** and emits only a **schema-validated extract**; a
  **Privileged-LLM** holds the tools and **never sees raw content**. Enforces brain.md's "assume the model WILL
  be injected" in deterministic code outside the model. First consumer = Deep Research; **M3 ingest + every
  connector (esp. Gmail) reuse it** — email is the canonical injection vector.
- **Web access (DR-b).** `SearchProvider` (Brave default, Tavily fallback) + `Fetcher` (local trafilatura
  default) behind ports, all outbound calls through a **controlled-egress allowlist** (default-deny), logged via
  OBS. The code-exec sandbox stays fully egress-blocked.
- **Deep-Research engine (DR-c).** Bounded iterative loop (search → fetch → quarantined-extract → judge → loop
  or synthesise) implementing M7-c's `Researcher`. Two modes: **Standard** (DeepSeek orchestrator, the idle
  loop's default) / **Deep** (Claude teacher, owner-invoked); the **quarantined reader is always a local
  model**. Non-sensitive only; raw pages never persisted.

## ◆ Cross-cutting concerns (in every layer, not a spoke)
- **Security / key model** — see § security wall above. Own workstream; threat-model gate (M2-d) before any
  sensitive store.
- **Observability (ADR-008, OBS-a/b).** Local-first, **no external SaaS, no PII egress, no OTel collector**.
  Capture seam = **"meter the pipe + thin taps"**: a `TracingModelPort` wraps the one model chokepoint for
  token/cost/latency; a thin `ObservabilitySink` taps only the Brain + distill for confidence/escalation/errors.
  Telemetry → a **SQLCipher** store (carries hashed keys + scores + counts, **never message content**);
  **tier-aware cost model** (local = 0, teacher = quota-units, cloud = per-token micros). The Curiosity Loop's
  `TokenLedger` guardrail stays **separate** (hard-stop reliability ≠ observability).
- **Backup / durability** — one consolidated encrypted data dir (`/opt/artemis`) + clean DB dumps; device
  purchase deferred, but the data layer is architected backup-ready now (backup-before-migrate + rollback).
- **Runtime token-frugality** — cheap local/RAG path default; flag-and-ask before shipping a token-heavy feature.

## ◆ Interaction surfaces (capture + render; thin clients)
- **Voice (M5)** — Swift audio sidecar (VoiceProcessingIO AEC, openWakeWord, Silero barge-in) → STT
  (Parakeet + Whisper) → brain → streaming TTS (warm Kokoro-82M); speaker-ID (ECAPA) drives the voice Tier gate
  (**voice-ID = identity, not the key**). Instant-ack + latency budget. One room first → satellites later.
- **Native Mac · iPhone · iPad client (CLIENT)** — universal, equal-polish, XcodeGen. Screens: **Review** (the
  owner-approval surface) · **Chat** · **Status**. Reaches the brain over the **Tailscale tunnel** via an
  **authenticated `/app/*` API** (extends the M1-c FastAPI app; `tailscale serve`).
- **Mac surface (ADR-017, CLIENT-f): native SwiftUI, Athena-style.** A *separate* `ArtemisMac` target sharing the
  `ArtemisKit` core (not Catalyst, not Designed-for-iPad). Scene = **menu-bar popover + global-hotkey floating panel +
  full window + Settings**. The Mac is just another paired device (its own SE key) over Tailscale; the **Mini stays
  headless**. Day-to-day Mac client = a MacBook/other Mac. Built via Developer-ID + notarization (personal use, no App Store).
- **Client ↔ brain auth (ADR-010): paired-device key, one key / two authorities.** The phone holds **one SE
  P-256 keypair** registered with **both** the broker (vault-unlock authority) and the brain's app-auth registry
  (API-session authority). Opening the app = **one Face-ID gesture** driving two domain-separated handshakes:
  an **API-session** challenge-response (opaque short-lived token) **and** the **vault unlock**. **Session ≠ data
  access — the DEK is the data gate**: a real *"Connected but vault-locked"* state exists (Status works on the
  session alone; Chat + Review need the vault open → fail-closed 423 → re-unlock). Scope is resolved from the
  session, never the client.
- **Remote access** — reachable anywhere via the private encrypted tunnel; data never touches cloud, only an
  encrypted path to the owner's box. Conversational-instant bar is a home/LAN target; remote allowed a beat slower.
- **Vision (DESIGNED, deferred — ADR-014)** — a future vision *input* sibling to voice: an overhead desk camera +
  on-screen annotated viewfinder HUD, a **voice-first guided build-assistant** for hands-on projects. A new Swift
  **vision sidecar** (Apple Vision detect/track/OCR + open-vocab detector) feeds object crops on demand to the
  brain's Qwen3-VL (MLX) for ID + M3/M4/web enrich; autonomous watch-and-verify is the north star, reached via a
  capability ladder. Mini-local (no ACI edge box). Deferred behind M3/M4/M5/DR/Projects/CLIENT.

## ◆ Domain modules (the spokes)
Each is a first-class module: ships a **manifest** (tools · `data_scope` · owner/guest permissions ·
proactive_hooks · ui), owns or mirrors its operational data (ADR-011), pushes knowledge + facts to the core.

**Source-of-truth is per-domain, not global (ADR-011) — no bidirectional sync in wave-1:**
- **Mirror** (external = truth, read + write-through): **Calendar**, **Email**. The external system is
  authoritative at every instant → no conflict-resolution subsystem. **Calendar = active manager**: mirror +
  write-through + a thin **native proposal overlay** (Artemis-native proposals/holds that can't conflict,
  promoted to real Google events via the Review screen on approval).
- **Own** (Artemis = truth): **Tasks** (optional one-way export), **Projects**, **Habits/Goals**.
- **All external-effect writes are staged as `PendingAction` instances via `ActionStagingService` (ADR-012), surfaced on the pending-actions tab of the CLIENT Review screen; reads/awareness need no approval.** The CLIENT milestone is the **unlock** for write-enabled spokes.

**Spoke wave (M8, specced):** Google-auth foundation → **Calendar** (full module — source-of-truth doc
[`../modules/calendar.md`](../modules/calendar.md)) → **Gmail** connector (read-only/awareness, every message
through `artemis.untrusted`) → **Productivity** (Tasks/Projects/Habits/Goals).

**Later spokes:** **Finance (+ subscription tracker) — DESIGNED ([`../modules/finance.md`](../modules/finance.md); FIN-* specs pending core)** · Notes/Journal · Document input ·
News / web watcher · Comms · Cooking · Shopping/Pantry · Smart home · Health & Fitness · Doctor/Vet · Travel ·
Dev workstation. Grouped boundaries retained from the phase-3 map; build just-in-time behind the manifest contract.

## ◆ Integration / connector layer (NOT modules)
Connectors translate external services into the standard contract and feed modules + the knowledge layer; they
are not capabilities themselves (HA architecture pattern). **External text passes `artemis.untrusted`**; all
outbound network is egress-allowlisted (ADR-009).
- **Google** (Calendar + Gmail — single-owner OAuth2, published-unverified, refresh token in the owner-private
  encrypted scope) · **Telegram** · **Home Assistant / Google Home** · **wearables** (Garmin/Apple Watch) ·
  **Weather**.

---

## The module contract (how a spoke plugs into the hub)
A module is uniform **only where the hub depends on it**, free everywhere else:
1. **Manifest** (`ModuleManifest`) — declares `tools[]` (`ToolSpec`), `data_scope`, owner/guest `permissions`,
   `proactive_hooks[]` (`HookSpec`), `ui` surface. Populates the tool registry (RAG-for-tools).
2. **Typed tools** — the live/exact interface the brain calls (typed dispatch).
3. **Knowledge + memory push** — searchable text/summaries → knowledge layer (provenance + locator); facts →
   memory write path (`build_write_path`).
4. **Proactive hooks** — deterministic `check` functions the Heartbeat runs on schedule (silent-success;
   escalate only on a hit).
5. **Scope tags** — every datum tagged via `data_scope`; the crypto wall + sensitivity Tier enforce it.

## Build status & spec map
**Built (Windows/WSL2 dev box, Codex coder, ADR-026):** the entire dev-buildable queue — core spine M0–M7 + OBS + DR +
M8 Gmail/Calendar/Productivity + Finance + the cross-module reactions runtime (ADR-021/032, ships DORMANT in `observe`) +
the end-to-end sensitivity ingestion wall (ADR-029) + the headless agentic executor engine (ADR-031, behind the optional
`[agentic]` dep group) + the Tauri client (behind a mocked `invoke`) + the Windows voice-dev twin (ADR-001 wire-compatible) + owner-private SQLite stores encrypted at rest on Windows via real SQLCipher keyed by a DPAPI-sealed per-scope DEK (WindowsKeyProvider; ADR-033 Phase 1 — boundary = offline-disk-theft + cross-user), with the same-user-credential gate now closed by a **Windows Hello unlock** on the win32 brain startup + `artemis-unlock` CLI (ADR-033 Phase 2, m2-win-b; process-level gesture gate, not yet a TPM-attested binding — that lands with the Tauri/Mac path). The Finance store now also **fails closed** when the SQLCipher binding is absent (no plaintext fallback).
Each was host-verified with full `uv run mypy` + `uv run pytest -q` and an independent cross-model review on high-stakes specs.
**Gated / unbuilt (in `docs/changes/`):** Mac-gated (`M0-b/c/e/f`, `M2-a/c/d`, `M3-d`, `M5-a-audio-sidecar`), MSVC-gated
(`CLIENT-auth` + the whole Rust compile) and Tauri-gated (`GATE-b`) tails — they wait on the Mac Mini / MSVC C++ Build Tools.
`docs/changes/BUILD-ORDER.md` is the live queue truth. The core spine builds in dependency order; **M2-d is a hard gate before M3/M4**:

```
M0 foundation → M1 thin brain → M2 security wall → M3 knowledge → M4 memory
  → M5 voice → M6 heartbeat → M7 teacher/recipe → [CLIENT app @ core→spoke boundary] → M8+ spokes
OBS (observability) + DR (deep research) = post-gate, parallel to the late spine.
```

| Group | Specs | What |
|-------|-------|------|
| M0–M7 core spine | 32 | foundation · thin brain · security wall · knowledge · memory · voice · heartbeat · teacher/recipe |
| OBS | 2 | logging + sink + taps (OBS-a) · SQLCipher telemetry + cost model (OBS-b) |
| DR | 3 | `artemis.untrusted` (DR-a) · web access (DR-b) · deep-research engine (DR-c) |
| CLIENT | 6 | app-auth core · `/app/*` endpoints · broker `pair` IPC · ArtemisKit · app shell · screens |

**On-hardware gated** tasks (real Secure-Enclave prover, encrypted-volume mount, `tailscale serve`, on-device
UI) run on the Mini, mirroring the M2 pattern.

## ADR index (shaping decisions)
| ADR | Decision |
|-----|----------|
| [001](../adr/ADR-001-stack.md) | Stack: SwiftUI app + Swift audio sidecar · Python brain · MLX · LanceDB · SQLCipher · Claude-subscription teacher · Mac Mini appliance |
| [002](../adr/ADR-002-deployment-method.md) | Deployment: native + launchd · build-on-Mini · Tailscale tunnel · dev→UAT→PROD slots · expand/contract migrations |
| [003](../adr/ADR-003-teacher-email-bootstrapping.md) | Teacher-on-email bootstrapping (non-sensitive, quota-capped) |
| [004](../adr/ADR-004-memory-engine.md) | Memory engine: custom bitemporal SQLCipher + sqlite-vec |
| [005](../adr/ADR-005-owner-key-broker.md) | Owner key delivery: remote-attested key broker (the M2 wall) |
| [006](../adr/ADR-006-two-tier-proactivity.md) | Two-tier proactivity (Tier-0 always-on / Tier-1 unlocked) |
| [007](../adr/ADR-007-knowledge-layer.md) | Knowledge layer: encrypted-volume LanceDB + adaptive retrieval |
| [008](../adr/ADR-008-observability.md) | Observability: local-first logging + SQLCipher telemetry |
| [009](../adr/ADR-009-untrusted-content-and-deep-research.md) | `artemis.untrusted` dual-LLM layer + Deep-Research engine |
| [010](../adr/ADR-010-client-app-auth.md) | Client ↔ brain auth: paired-device key (one key, two authorities) |
| [011](../adr/ADR-011-spoke-source-of-truth.md) | Spoke source-of-truth: default-mirror, no bidirectional sync |
| [012](../adr/ADR-012-gated-action-staging.md) | Gated-action staging: owner-approval `PendingAction` for one-off external writes |
| [013](../adr/ADR-013-cross-module-links.md) | Cross-module links: M4 entity backbone (Person/Place/Goal) + ToolRegistry-mediated logical refs |
| [014](../adr/ADR-014-vision-build-assistant.md) | Vision build-assistant: overhead desk-vision *input* + guided-build subsystem (DESIGNED, deferred; capability ladder Rung 0→3) |
| [015](../adr/ADR-015-async-port-surface.md) | Async port surface: network-I/O ports (LLM/embed/rerank/retrieve/memory) are `async`; local-disk/cached stay sync |
| [016](../adr/ADR-016-async-tool-dispatch-surface.md) | Uniform async tool-dispatch: `ToolSpec.callable_ref` + GATE `approve` are `async` (every tool callable is `async def`) |
| [017](../adr/ADR-017-macos-client-surface.md) | ~~macOS client surface: native multiplatform `ArtemisMac`~~ — **SUPERSEDED by ADR-023** (Tauri desktop client) |
| [021](../adr/ADR-021-cross-module-reactions.md) | Cross-module reactions: hybrid learned-first "when X→then Y" layer (3 pieces + shared reconciler + link-integrity contract); hub views carved out. (018–020 reserved for APEX-system ADRs.) |
| [022](../adr/ADR-022-model-runtime-relook.md) | **Accepted** — Model/runtime re-architecture: reasoning routed by sensitivity — **non-sensitive → Codex-subscription** (pluggable, local/API fallback), **sensitive → local model**; **hybrid, privacy wall retained**. Local-trigger proactivity + composed harness (own spine + Pydantic AI + MCP + OTel); build-Windows-first |
| [023](../adr/ADR-023-tauri-client-replatform.md) | Client re-platform → **Tauri** cross-platform desktop (`.exe` Windows-now → Mac later); supersedes ADR-017. **(Navigation shell superseded by ADR-028; platform choice stands.)** |
| [024](../adr/ADR-024-task-executor.md) | Task Executor: general multi-step plan→act→verify agent (background-default) + separate durable task-memory; reuses GATE; graduates→recipes (= M9) |
| [025](../adr/ADR-025-tauri-client-auth-wall-reroot.md) | Tauri client auth/wall re-root: unlock = **custom P-256 challenge-response + native hardware sealing** (Windows TPM/Hello · macOS SE/Touch ID), reusing the M2-a verifier; supersedes ADR-023 §4; recovery passphrase unchanged |
| [026](../adr/ADR-026-codex-build-coder.md) | Build coder = **Codex CLI (`gpt-5.5`)** for Artemis core (supersedes DeepSeek); coder-tier policy retired; `cross_model_review` default-satisfied (Claude plans/reviews → Codex builds). (027 = APEX-system ADR.) |
| [028](../adr/ADR-028-client-spatial-navigation.md) | **Client navigation = spatial "travel-zoom" command-map** (pan + scroll-zoom + travel-then-expand; brain core; floating Ask pop-up; photo background) — supersedes the Review/Chat/Status tab-shell. Mockup: `docs/research/mockups/travel-zoom-workspace.html` |
| [029](../adr/ADR-029-sensitivity-ingestion-gate.md) | Sensitivity ingestion gate: cheap local-model classify at the ingest seam (fail-closed), enforced end-to-end (M3a/M4b/M8b1 + RAG-compose `PrivacyWallError`); retires the regex false-negative leak |
| [030](../adr/ADR-030-tauri-client-transport.md) | Tauri client transport: the Rust core owns the session token; it never enters the webview |
| [031](../adr/ADR-031-agentic-runtime-host-computer-use.md) | Agentic runtime: one unified plan→act→verify executor + Rung 0→4 host-computer-use ladder + blast-radius authority; coding subsystem borrows the OpenHands SDK under an Artemis planner/agent-inbox/GATE/router. Dev sandbox = no-network Windows AppContainer |
| [032](../adr/ADR-032-reactions-runtime-composition.md) | Cross-module reactions runtime composition: claim-check event payload · continuous bounded worker · observe-first manual go-live gate · at-least-once idempotent effects · depth-counter cascade guard |
| [033](../adr/ADR-033-windows-host-v1.md) | **Windows-host v1**: run on the dev box now, Mac = later migration (off critical path). Substitutes: Ollama/CUDA · Windows voice twin · TPM/Hello unlock. Security wall = lighter interim (SQLCipher DEK sealed to TPM/DPAPI + Hello; phone-attested SE broker deferred to Mac). 8GB-VRAM model juggling accepted |

## Still parked / maybe
Documents vault · Media/Watchlist · Sleep/Recovery · full CaMeL capability data-plane · knowledge-graph layer ·
non-sensitive always-available knowledge tier · bidirectional sync (per-domain, demand-triggered) · hardware
64GB re-decision (WWDC 2026). (Build-phase parked items live in each ADR's § Parked.)
