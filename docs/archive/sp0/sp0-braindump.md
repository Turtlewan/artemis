# SP0 Braindump — raw, unprocessed

Append-only vision dump for Artemis. No structure, no triage, no commitment. SP0 drains this
into `REQUIREMENTS.md` when the user says so. Capturing ≠ committing.

---

## 2026-06-01

Artemis will be a command center for my life — it will integrate with a lot of things, and
answer me as quick as Jarvis does for Iron Man.

The data it reads should come from all the integrations. **Most of the integrations will be
built by me** — e.g. a task list, calendar, finance, etc. Each of these will be built so it
can integrate into Artemis itself.

Hosting: **Mac Mini first**, then upgrade as needs require.

Other things we might integrate with:
- Telegram bot
- Home Assistant / Google Home (that kind of thing)
- CircuitMess (maybe)
- Garmin and/or Apple Watch (maybe)

UI: built for **iPhone and iPad** first, then other screens.

These are the only *external* modules I can think of — most other modules will be built by me.

---

**Cooking module.** I want a cooking module where I can add links — each link is either a
webpage or a video.

**Knowledge extraction module.** Extract knowledge from links, reels, and videos.

**Calendar module.** Extracts events from different sources and populates the calendar.
(Maybe the *input/extraction* part should be a separate module by itself.) Also works with
the **task module** — it should scan an event and be smart enough to plan tasks for it.

**Finance module.** Tracks spending and income. Still need to work out the sources — maybe
just Gmail emails.

**Q (architecture): centralised brain/data module?** — User asked whether there should be a
centralised brain/data module. _Provisional recommendation (to confirm in SP0 proper):_
hub-and-spoke. Artemis core = (1) brain/orchestrator owning the integration contract +
(2) centralised knowledge/data layer (the RAG second brain). Modules own their own domain
data but **push** it into the central layer for indexing, rather than the core querying each
module live (central index → Jarvis-fast + cross-module reasoning + modules stay decoupled).
Open fork to lock later: central index vs live federation. **→ RESOLVED 2026-06-03 (phase 3): HYBRID** —
modules own their operational store of record + expose typed tools (brain calls live for exact facts) AND
push searchable knowledge into the central index (recall + cross-module reasoning). See overview.md § Data flow.

**Health & fitness module.** Tracks calories and food. Maybe integrates with the cooking
module.

**Brain module = the core.** Treat the brain as *the* core of Artemis. When we get to it, do
**super deep research** (apex-research / deep dive) before deciding anything — not a casual
pass. Flagged for dedicated deep-research treatment.

**Voice interaction.** Voice is in scope — talking to Artemis (Jarvis-style), not just text.
(Details — wake-word vs tap-to-talk, latency target — deferred to SP0 questioning.)
For now: voice in **one room** of the house; possibly **every room** in the future
(multi-room / whole-home voice later).

**Notes / journal module.** Daily logs and thoughts. No idea what to do with this yet —
just capturing that it should exist.

**Dev workstation module (important).** Do development work *from* Artemis. Idea: a program
that can open/run PowerShell scripts, show where code is being edited from, and alert when
different windows/sessions require attention. Essentially Artemis as the control surface for
the user's own coding agents.
_Prior art (exists, verify in deep research):_ Claude Code notification hooks (idle/needs-input
alerts) + the harness's multi-agent monitor ("FleetView"); multi-agent orchestrators like
Conductor / Crystal / Claude Squad / vibe-kanban; terminal multiplexers (tmux) / Warp for
multi-pane + notifications. Primitives exist; the novel part is folding dev-orchestration into
the personal command center as just another module on the hub. Ties to the existing
planning-Claude / building-DeepSeek loop. → dedicated research pass when reached.

**Cyber security module.** Prevent attacks against Artemis.
_Note (to weigh in SP0):_ security for a system holding finance/health/personal data is
likely **cross-cutting** (a concern baked into every module + the core, plus possibly a
dedicated monitoring/defense module) rather than only a single bolt-on module. Capturing as a
module per the dump; flag that it spans the whole platform.

**News module.** (Selected from suggestions.)

**Briefing module.** Proactive morning/evening digest pulling across modules (calendar, tasks,
finance, health, news). _Note:_ briefing may belong in the core (proactive brain on top of all
modules) rather than as a spoke — decide in SP0.

**Comms module.** Email + Telegram in one place: triage, summarize, draft replies. Feeds off
the Telegram bot and the Gmail source.

**Shopping module.** Shopping lists / pantry / inventory. Sits between cooking and health &
fitness ("low on X", what's in the pantry).

**Travel module.** Trips, itineraries, commute. Pulls from calendar + finance + documents.

**Habits / goals module.** Track routines and goal progress; reads from tasks + journal +
health.

**Subscription tracker** is NOT its own module — it's a small feature *inside the finance
module*.

---

## 2026-06-02

**Quote of the day module.** I add quotes; Artemis serves/finds them — a daily quote and/or
on-demand retrieval (search the quote collection). Small module; likely reads from / pushes into
the central knowledge layer like the others. (Also logged in `BACKLOG.md`.)

**CircuitMess watch — camera-based pseudo touchscreen.** Might want to use a camera to do a
pseudo touch screen with the CircuitMess watch, if possible. (Hardware interaction idea — feasibility
TBD.)

**Camera vision — describe the desk / surroundings.** Use a camera to see the desk or things on
it and describe what it sees. (Visual perception input — could feed the brain / notes / assistant.)

**Document input — camera or file attachment.** Add documents to the database for reference via
camera capture (scan/photo) or file attachment. Feeds the central knowledge layer / second brain.
(Likely ties to the documents-vault idea + knowledge-extraction module.)

**Projects module.** A separate module to track projects I want to start and their statuses.
(Distinct from the task module — higher-level project tracking; status per project.)

**Doctor module.** Answer health questions quickly — explicitly **not** medical advice, just fast
answers. Goal: find a way to be **better than a normal LLM** at this (e.g. grounded in my own
health data / trusted sources / the second brain, rather than generic model output). How it beats a
plain LLM = open question to work out.

**Vet module.** Same idea as the doctor module but for pets — fast answers, not veterinary advice,
grounded to be better than a plain LLM (pet's own records / trusted sources / second brain).

**Analysis module.** Acts like a proper high-tier consulting analyst — can gain domain knowledge
the way consultants are *actually taught to research* (structured frameworks, expert-interview-style
inquiry, hypothesis-driven, MECE, primary + secondary sources), not just a generic LLM answer.
The "how analysts are trained to research" methodology is the differentiator to capture later.

---

## 2026-06-03

**Token frugality at RUNTIME — cross-cutting feature constraint.** Spending tokens to **build**
Artemis is fine. The constraint is on the **features when they're being used**: at runtime they
should actively try **not** to burn LLM tokens — lean on **RAG / local retrieval** (and similar
cheap/local paths) instead of firing off expensive LLM calls. Treat per-feature runtime token cost
as a first-class design constraint. **And:** when a feature's design would make it token-heavy at
runtime, **flag it and ask me** before committing to that scope — surface the cost/scope tradeoff
rather than silently building something that spends every time it's used. _(Spans every module +
the core/brain; ties to the brain local vs cloud vs hybrid fork — local inference + RAG are the
token-cheap runtime paths.)_

**Teacher-escalation — DECIDED IN (brain capability).** Cheap **local model is the default**;
a stronger "teacher" model is called **only when the local one fails**, and the teacher's solution
is **distilled into a saved skill/recipe** so the same class of task is handled locally (token-free)
next time. This is the mechanism behind "the agent evolves over time" + serves the runtime
token-frugality constraint (cloud spend happens once per novel hard task, then never again).
_(Pattern source: Odysseus `teacher_escalation.py` / `skill_extractor.py` — see
`docs/research/odysseus-cross-reference.md`.)_

**Integration contract — LEAN (not locked): lightweight internal registry, MCP only at the edge.**
Most modules are self-built and run on the **same machine / same stack**, so they don't need MCP
between them — the brain calls them directly or via an internal API loopback (`app_api`-style),
backed by a simple **tool registry** (list of callable tools + arg schemas) so the LLM knows what
exists. **MCP is reserved for the edges only:** third-party tools that already ship as MCP servers,
cross-machine targets (a future GPU box / external service), cross-language modules, or a risky tool
worth hard process-isolation. Rationale: adopting MCP as the internal contract is over-engineering
for a single-user box (cuts against simplicity + token frugality). Refines the open
integration-contract fork → _internal = registry; external = MCP._

**Odysseus reccos — decisions (2026-06-03).** Cross-reference report:
`docs/research/odysseus-cross-reference.md`. Clone kept at `.research/odysseus` **as reference** —
surface relevant patterns when the matching module comes up in discussion (don't delete).
- **Teacher-escalation → IN** (see above) · **Skills library → IN** (implied — it's where escalation writes recipes).
- **MCP → edge-only** (see above): internal registry for own modules, MCP for external/cross-machine.
- **ntfy → IN** as the notification backbone (local, free, no cloud) for reminders/briefings/tasks/alerts.
  Webhooks-on-events → deferred (optional, later).
- **Cookbook → SKIP as a module, SALVAGE the kernel.** No 270-model catalog/recommender UI (over-built
  for a single-user box running one/few local daily-drivers). Borrow only its **Apple-Silicon
  unified-memory sizing logic** as a **one-time setup helper** to pick the right local model for the Mac Mini.
- **Compare (blind model A/B) → SKIP** as a feature; at most a one-off eval when choosing the daily-driver model.
- **Deep Research visual report renderer → folds into the analysis module** (ships with the Deep Research engine).
- **Build-time patterns** (RAG-based tool selection, hybrid retrieval, local→cloud model routing,
  prompt-cache breakpoints, hub-and-spoke, degrade-don't-crash) → auto-adopt when building the brain; no
  decision needed. **Open SP0 fork inside this:** vector store — standalone ChromaDB+fastembed vs
  **sqlite-vec + MLX** (lean: sqlite-vec, one fewer process for a single-user box; decide at stack re-confirm).
- **Don't-take (agreed):** the Odysseus code itself (unaudited/"vibecoded"), multi-user auth / 2FA /
  owner-scoping (Artemis is single-user), image-editor / diffusion extras.

**Web crawler / keyword watcher.** A crawler that monitors the web (news prompted) for certain
**keywords or subjects** I specify, then **pushes me a notification** when something matches.
_Notes (to weigh in SP0):_ likely the *active/push* counterpart to the **news module** (news =
read/digest; this = watch-and-alert on my topics) — decide whether it's part of news or its own
spoke. Notifications ride the **ntfy** backbone (already IN). Runtime token-frugality applies:
matching should lean on cheap keyword/local filtering, escalating to an LLM only to summarise a
genuine hit. Open: source set (RSS / news APIs / general web crawl) + match definition (literal
keywords vs semantic subjects).

---

## SP0 questioning — resolved decisions (2026-06-03)

_Questioning phase started this session (user: "start the questions"). One question at a time
(user preference). Decisions below are LOCKED unless reopened._

- **Scope = the full platform, NOT a cut-down v1.** Design target is the complete Artemis. Build
  *order* (what DeepSeek builds first) is a separate roadmap-phase concern, deferred — aiming big
  does not mean building everything in one shot.
- **Interaction = voice + text, co-equal.** Both first-class surfaces from the start; every capability
  reachable by either.
- **Latency bar = conversational-instant.** Artemis ALWAYS responds within ~1s: quick things → the
  answer outright; heavy things (analysis, deep research, doctor reasoning) → an immediate
  acknowledgement ("give me a sec") then the result **streamed** as it's ready. Never silent waiting.
  Implies: always-on fast local responder + streaming everywhere.
- **Brain = LOCAL-ONLY (working frame).** The sub-1s bar rules out cloud round-trips for the
  interactive path. Per user (2026-06-03): **take cloud off the table entirely for now** — design as
  if there is no cloud at all (revisitable much later, but all current discussion assumes fully
  local). Cascade: the brain local/cloud/hybrid fork (B) is resolved → **local**. Teacher-escalation
  (still IN) now escalates to a **bigger local model** loaded on demand, not cloud.
- **Identity / users = per-person aware (⚠️ REVERSES the single-user decision).** Artemis is private
  (never public — for the user + possibly a small set of trusted people in physical vicinity, e.g. a
  household), but it is **not single-user**: it distinguishes individuals and holds/serves data per
  person. This **overturns** the 2026-06-03 Odysseus decision ("single-user; don't take multi-user
  auth / 2FA / owner-scoping"). Owner-scoping + an identity layer + a permissions/scoping model are
  now **IN scope**. Pulls apex-security and an identity/permissions design into the platform.
- **Voice recognition (speaker ID) = CONFIRMED requirement.** Artemis identifies who is speaking by
  voice, and routes the right person's data/scoping/permissions accordingly. This is the primary
  identity mechanism for the voice surface (app login likely covers the text surface). Ties directly
  to per-person awareness above.
- **Data scoping = owner-centric (refines per-person down from symmetric multi-user).** Resolved:
  - **Owner (you):** full access — every module + all private data (finance, health, journal, …).
  - **Other people (recognised by voice):** light, general capabilities (weather, search, neutral
    Q&A) **+ Artemis remembers their preferences & likes** (a lightweight personalisation profile).
    Walled off from the owner's private modules; no heavy personal data stores for guests.
  - NOT symmetric multi-user; no separate "shared household" data scope adopted. Whether a given
    module lets a guest view/contribute is a **per-module detail** for the capability-map phase.
  - **Data-model implication:** one rich owner-private scope + lightweight per-person guest
    preference profiles + a general/stateless capability layer. apex-security gates the wall between
    owner-private and guest access.
- **Proactivity = proactive (Jarvis-like) engine, owner-tunable.** Artemis actively watches across
  modules and reaches out unprompted (briefings, calendar clashes, spending alerts, keyword/news
  hits). An always-on proactive engine + notification policy (via ntfy) is IN scope. **Owner-tunable:**
  the user tunes how proactive/noisy it is — per-area thresholds, what surfaces, quiet hours — so
  proactivity ships with configurable controls, not a fixed firehose.

### Non-goals / boundaries (locked)
- **Never a public-facing product.** Private to the user + trusted people in vicinity only.
- **No fully-autonomous high-stakes actions.** Artemis may *draft* / *propose* (email, payment,
  calendar change) but must get the owner's confirmation before *executing* anything high-stakes —
  never sends money, sends comms, or takes irreversible action on its own.
- **Local-only** (no cloud — see brain decision). **Doctor/vet = fast answers, NOT** medical/
  veterinary advice.

### Research gap-check (2026-06-03) — foundational gaps surfaced by research
_User asked "are we missing anything?" → web research on local-first personal assistants (HA Assist,
Jarvis-style projects, MLX/RAG on Apple Silicon). Decisions validated; six foundational gaps surfaced.
Working through them one at a time._

- **#1 Backup / disaster recovery — REQUIRED (procurement deferred).** Local-only + single Mac Mini
  holding irreplaceable finance/health/journal data ⇒ backup is non-negotiable. Shape: external SSD
  (cheap start) or LAN NAS (better long-term, versioned) — both local, no cloud; encrypted, automated,
  DB-safe snapshots (SQLite backup API / litestream-style, not a raw copy of a live DB); optional
  cloud-free offsite = rotated encrypted drive. **Buy the device later, but architect the data layer
  backup-ready NOW** (one consolidated encrypted data dir + clean DB dumps).
- **#2 Long-term episodic memory of the owner — IN (core brain tier).** Separate from the document
  RAG and from guest preference profiles: Artemis remembers conversations, learned facts, decisions —
  "knows you" over time. Default = **remember (almost) everything** (full episodic log, searchable),
  owner-controllable (view/edit/delete). Retrieval is **local/RAG** so keep-everything stays
  token-cheap. Likely keep the raw log + build distilled/summary indexes over it for fast recall.
  Raises storage + backup (#1) + security (#5) weight.
- **#3 Module development model — Standard manifest, free inside.** A module is a first-class concept:
  it MUST ship a standard **manifest** (declares its tools, private/shared data scope, owner/guest
  permissions, proactive hooks, UI surface); internals (code layout, storage, libs) are free. The
  manifest is what populates the tool registry (extends the registry + MCP-edge decision). Uniform
  where the hub/brain/scoping/proactive-engine depend on it; flexible everywhere else. (Rejected:
  strict full-template SDK = over-engineered for a solo builder; loose convention = drift + breaks
  uniform brain reasoning.)
- **#4 Multi-device topology — Mini-as-brain + thin clients + reachable anywhere.** Mac Mini = the
  always-on brain/server (all data + models + thinking, one source of truth); iPhone/iPad/voice
  points/(watch) = thin clients (capture + render). **Remote access: reachable anywhere** via a
  private encrypted tunnel (Tailscale/WireGuard) — data never touches the cloud, only an encrypted
  path to the user's own box. Implications: the **conversational-instant bar is a home/LAN target**
  (remote allowed a beat slower); raises security weight (remote surface + tighter remote auth).
- **#5 Security — its own workstream.** Baseline posture (all IN): encryption-at-rest for sensitive
  data (finance/health/journal/episodic memory) · biometric lock (Face/Touch ID) on client apps ·
  private-tunnel auth + app login for remote · mic privacy (wake-word gating, hard mute, listening
  indicator) · owner↔guest wall enforced at the data layer · a dedicated **apex-security threat-model
  pass** before building anything sensitive. **Auth friction = unlock once per session** (biometric
  on open / after idle timeout, then frictionless until it re-locks) — keeps the Jarvis feel with a
  real lock.
- **#6 Mac Mini resource budget — size hardware to the stack.** Stance: target a **higher-RAM Mac
  Mini (≈32GB+)** so the always-on instant stack (fast responder + STT + TTS + embeddings + vector
  store + wake-word; teacher lazy-loaded) stays resident — buy enough RAM rather than constrain the
  stack. Precise RAM + model sizing happens at the **stack re-confirm phase** via the Apple-Silicon
  sizing helper (Cookbook salvage) once local models are chosen. Design principle: small resident
  responder + lazy-load the heaviest models on demand.

---

## SP0 phase 2 — capability map (2026-06-03)

_Validated structure (research-backed where noted). The big move: separate the **core**, **cross-cutting
concerns**, **interaction surfaces**, and **domain modules** — tangled together in the raw dump._

**◆ Core (the brain — the hub, not a spoke):** orchestrator/brain (intent, routing, local fast-responder,
teacher-escalation→local, skills library) · central knowledge layer (RAG second brain) · episodic memory
(memory of the owner) · **shared ingestion/extraction pipeline** (call #1) · tool registry + module contract
(manifests) · identity & scoping (voice ID, owner/guest) · **proactive engine** incl. briefing + attention
routing (call #2) + ntfy notification policy.

**◆ Cross-cutting:** security · backup/durability · observability · runtime token-frugality.

**◆ Interaction surfaces:** voice (wake-word, STT/TTS, one→multi-room) · chat app (iPhone/iPad) · Telegram ·
remote access (private tunnel) · vision input (camera: surroundings, document capture, CircuitMess
pseudo-touchscreen).

**◆ Domain modules (spokes), grouped:**
- Productivity & time: Calendar · Tasks · Projects · Habits/Goals · Travel
- Knowledge & capture: Notes/Journal · Document input · Quote of the day
- Awareness & inbound: News · Web crawler/keyword watcher · Comms (email + Telegram triage; **Contacts/People live inside Comms** — call #5, user's choice)
- Home & living: Cooking · Shopping/Pantry · Smart home (HA/Google Home)
- Health & body: Health & Fitness · Doctor · Vet · Wearables (data source)
- Money: Finance (incl. subscription tracker)
- Dev & meta: Dev workstation

**◆ Intelligence capabilities (core-adjacent, grounded in the brain — call #3):** Analysis (consulting-analyst
methodology) · Deep Research engine (+ visual report renderer).

**◆ Integrations / connector layer (NOT modules — call #4):** Gmail · Telegram · Home Assistant/Google Home ·
wearables (Garmin/Apple Watch) · **Weather** (revived as a data-source feeding briefing + travel — call #5).
Per HA's architecture, connectors translate external services into the standard contract and feed modules +
the knowledge layer; they are not capabilities themselves.

**◆ Still parked / maybe:** Documents vault · Media/Watchlist · Sleep/Recovery · (Attention router → folded
into the proactive engine).

**Structural calls — all resolved:**
- #1 Extraction → core shared ingestion pipeline + thin per-source connectors ✅ (RAG best practice)
- #2 Briefing + attention routing → core proactive engine ("Heartbeat") ✅
- #3 Analysis + Deep Research → intelligence capabilities, core-adjacent ✅ (user)
- #4 Gmail/Telegram/HA/wearables → integration/connector layer, not modules ✅ (HA pattern)
- #5 Revive Weather (as integration/data-source) + Contacts (→ inside Comms, user's call) ✅

### Knowledge-layer direction (2026-06-03, research-backed) — internals deferred to the brain deep-dive
- **RAG is still correct in 2026 for the document/knowledge corpus (#1) — as *modern adaptive* RAG, not naive
  chunk-and-stuff.** Baseline hybrid retrieval (vector + keyword + rerank); adaptive routing (cheap vector for
  simple / agentic for complex / graph for relationship queries). Long-context and fine-tuning rejected for a
  local, growing, private corpus (small context windows, token cost, can't cleanly update/forget).
- **Episodic memory (gap-check #2) = a distinct self-hosted agent-memory system** (Mem0 OSS / Letta / Zep
  class — OSS/local tiers only, never SaaS): extraction→facts + vector + graph tiers. "Agentic memory" is
  rising as its own mechanism, not plain RAG.
- **Cross-module reasoning:** LazyGraphRAG-style local knowledge-graph layer is the candidate.
- Adaptive routing directly serves runtime token-frugality (cheap local path default; escalate only on need).
- ⚠️ **Lock only the direction. The exact internals (retrieval-strategy mix, memory framework, graph layer
  yes/no, local model choice) are the job of the brain SUPER-DEEP-RESEARCH pass** — still flagged, not yet run.
- **Brain design invariant — UPGRADEABILITY (user, 2026-06-03).** Build the best system achievable *today*,
  but every internal choice (retrieval strategy, memory framework, models, runtime, graph layer, orchestration
  framework) MUST sit behind a **swappable interface** so a better approach can be adopted later without a
  rewrite. "Best today, replaceable tomorrow." Hard requirement on the brain deep-dive.

### Brain super-deep-research — COMPLETE (2026-06-03) → see `docs/research/brain-architecture.md`
5 recursive waves, 18 parallel research agents. Full architecture + every source in the research doc.
Headline decisions locked there: thin custom orchestrator (Gateway→Brain→Skills→Heartbeat) · router-first
+ automation-over-AI · Qwen3-4B responder + constrained decoding · hybrid RAG on LanceDB + lazy graph ·
two-store memory (bitemporal episodic + semantic), auto-injected · typed tool dispatch + gated sandboxed
code-exec · local voice (openWakeWord/Parakeet/Kokoro + Apple VPIO AEC) · scheduled Heartbeat
(silent-success) · idle "Curiosity Loop" self-improvement (RAG/skills, owner-gated, no fine-tuning) ·
security = assume-injection + dual-LLM/CaMeL + crypto owner↔guest wall.
**Deployment DECIDED:** start on a **48GB Mac Mini M4 Pro** (dev stays on the PC); **push the teacher tier
to DeepSeek cloud (non-sensitive only)**; lean local core + lazy-loaded **Qwen3-14B for sensitive heavy
reasoning** (DeepSeek never sees sensitive data; Claude optional later for stronger sensitive reasoning);
distillation loop + automation drive cloud cost down; upgrade to a Mac Studio later (config-only swap).

---

## Where I stopped (2026-06-03, session 2 — questioning + brain deep-dive)

**Mode:** SP0 questioning (phase 1) + research gap-check + capability map (phase 2) + brain
super-deep-research. Wrapped here; user decides next direction next session.

**SP0 phase 1 — vision & scope (LOCKED):** full platform (no cut-down v1; build-order = roadmap) ·
voice + text co-equal · always-react-<1s (instant answer, or instant ack + streamed result) · brain
local-first · owner-centric users (voice ID; owner full, guests = light access + preference profile) ·
proactive engine (owner-tunable). **Non-goals:** never public · no autonomous high-stakes actions ·
doctor/vet ≠ medical advice. (Detail in "SP0 questioning — resolved decisions" above.)

**Research gap-check (LOCKED, 6):** backup required (purchase deferred, build backup-ready) · episodic
memory IN (remember-everything, local RAG) · module SDK = standard manifest, free inside · topology =
Mini-brain + thin clients + reachable-anywhere via private tunnel · security = own workstream
(unlock-once-per-session + baseline) · hardware = size to the stack.

**Capability map (phase 2, DONE):** core / cross-cutting / interaction surfaces / domain modules /
intelligence capabilities / integrations — see "SP0 phase 2 — capability map" above. 5 structural calls
resolved (extraction→core · briefing→core · analysis+deep-research = intelligence capabilities ·
integrations≠modules · Weather revived + Contacts→inside Comms).

**Brain super-deep-research (COMPLETE):** 5 waves, 18 agents → `docs/research/brain-architecture.md`.
Deployment **DECIDED**: 48GB Mac Mini M4 Pro (dev stays on PC), DeepSeek cloud teacher (non-sensitive
only), lazy-loaded Qwen3-14B for sensitive heavy reasoning; distillation + automation drive cloud cost
down; Studio upgrade later (config-only swap). New principle: **automation-over-AI for repeatable tasks.**

**Parked (not lost):** sensitive-reasoning Claude option (default = local 14B) · build/stack-phase picks
(Graphiti vs Mem0 · macOS 26 · Swift-vs-Python AEC · mic type · embedding tier · Pipecat vs HA/Wyoming ·
teacher 30B-A3B vs dense 32B).

**Next session — user will choose:** SP0 phase 3 (subsystem decomposition → overview.md) · or phase 4
data model · or phase 5 stack re-confirm (SwiftUI app + Python brain + MLX seed now well-informed, not
formally re-confirmed) · or fold brain decisions into specs.

---

## Where I stopped (2026-06-01)

**Mode:** SP0 braindump capture (pure capture, questioning deferred by user).

**Modules dumped so far:** cooking · knowledge extraction · calendar (+ maybe a separate
extraction/input module) · task · finance (incl. subscription tracker) · health & fitness ·
notes/journal · dev workstation · cybersecurity (cross-cutting) · news · briefing · comms ·
shopping · travel · habits/goals · quote of the day · projects · doctor · vet · analysis
(quote→analysis added 2026-06-02).

**Added 2026-06-02 — input/interaction + new spokes:** camera-based pseudo-touchscreen for the
CircuitMess watch · camera vision (see desk/things & describe) · document input via camera or file
attachment (→ central DB) · projects module (track projects-to-start + status) · doctor module
(fast non-advice health answers, must beat a plain LLM) · vet module (same, for pets) · analysis
module (consulting-analyst research methodology) · quote of the day.

**Cross-cutting / core notes:** voice interaction in scope (one room → whole-home later);
brain = the core, flagged for super-deep research before any decision; centralised brain/data
layer recommended (hub-and-spoke, modules push to central index — open fork: central index vs
live federation); briefing + attention routing may live in the core, not as spokes.

**Suggested-but-not-selected** (can revive): people/contacts · documents vault ·
media/watchlist · weather · sleep/recovery · attention router.

**Next session — pick one:**
1. **Continue braindump** — keep dumping modules/ideas (just talk, I append).
2. **"Start the questioning"** — drain this into `REQUIREMENTS.md`. SP0 phase 1 = vision &
   scope / v1 boundary / non-goals. Start with the 4 load-bearing forks: (A) interaction
   modality + "fast" target, (B) brain local vs cloud vs hybrid, (C) integration-contract
   shape, (D) the v1 boundary + first module.

---

## Where I stopped (2026-06-03, session 3 — deployment method)

**Mode:** SP0 deployment-method discussion (the user-requested step before phase 6). Run in
layman-terms throughout (user preference), research-gated on every fork. **All decisions → `ADR-002`.**

**Deployment method LOCKED (→ docs/technical/adr/ADR-002-deployment-method.md):**
1. **Runtime:** native + `launchd` (no containers for the live system — macOS containers can't reach
   Metal, so MLX/audio are natively bound anyway; nothing else benefits). Brain + mlx-openai-server +
   ntfy = LaunchDaemons; Swift audio sidecar = LaunchAgent.
2. **Build location:** on the Mini, with a **live↔build mode-switch** (pause Artemis during build/test,
   resume after — never both at once; kills RAM/GPU contention). DeepSeek's intelligence is cloud; only
   light "hands" + test runs are local.
3. **Build-agent isolation (Strong):** dedicated macOS user login (can't decrypt owner data) + Claude
   Code OS-sandbox (filesystem + network walls). Tests use sample data, never real owner data.
4. **Remote access:** **Tailscale** (data E2E + direct; metadata-only to Tailscale; home = direct LAN).
   Headscale = future zero-third-party swap. Native-API clients, **no web UI / reverse proxy**.
5. **dev→UAT→PROD:** 3 slots on one box; **lean default + full-UAT-for-risky** (data-migration /
   sensitive module / security-wall). Expand/contract migrations · backup-before-migrate · rollback ·
   local-script pipeline (no CI server).
6. **Backups:** clean snapshots (never raw DB copy) · scheduled + pre-migrate · tested restores ·
   append-only copy · local SSD→NAS later · **offsite deferred (local-only for now)**.

**Client connectivity (researched, in ADR-002):** iPhone/iPad = native SwiftUI tunnel members; Pi
(maybe) = native, runs Tailscale (4G uplink if roaming); **watch = CircuitMess "NASA Artemis Watch 2.0"
(ESP32-S3, 600mAh) → phone-Bluetooth bridge** (Gadgetbridge/Bangle.js cloudless pattern; battery rules
out a watch-hosted tunnel — ~4–8h WiFi vs all-day BLE). WireGuard-on-watch = niche on-charger fallback.

**NEXT SESSION:** SP0 **phase 6 — roadmap → build order → spec queue** (the last SP0 phase). Core/brain
first → spokes behind the manifest contract; security threat-model gate before sensitive. Then post-SP0
`apex-init` drains into REQUIREMENTS.md / ROADMAP.md + SP4 app defaults. (Re)drain `BACKLOG.md` first.

---

## SP0 phase 6 — roadmap → build order (IN PROGRESS, 2026-06-03 session 4)

_The last SP0 phase. BACKLOG.md drained first → only "quote of the day," already in scope (no new items).
Decisions below LOCKED this session unless reopened._

**Build philosophy = CORE-COMPLETE → THEN SPOKES (LOCKED).** Build the full brain core before any spoke;
the manifest contract is validated against a finished core. (Rejected: thin-slice-dogfood-early ·
value-vertical-per-spoke. User accepts a longer runway before first daily-driver use for architectural soundness.)

**Security wall MOVED UP (LOCKED).** Identity/scoping + the crypto wall (SQLCipher-per-scope + Secure-Enclave
key) is built BEFORE knowledge & memory, so those sensitive stores are born encrypted/partitioned — no
retrofit, no unprotected window. The apex-security **threat-model gate fires here**, early.

**Voice stays IN-CORE (resolved from prior lock).** SP0 phase 1 locked voice+text co-equal/first-class; the
brain research treats local voice as a core subsystem → voice (M5) is inside the core-complete bar, not deferred.

**Client timing = core→spoke boundary (planning default, vetoable).** M1–M7 built/tested headlessly via a dev
CLI + loopback API + automated tests on the Mini. The SwiftUI iPhone/iPad app is built ONCE after the core
surfaces (text+voice) stop moving, at the core→spoke boundary, against stable core APIs — so spokes are
dogfooded through a real app. Telegram + Tailscale remote ride alongside the app.

**Core spine (LOCKED order):**
```
M0  Appliance foundation        (Mac Mini provisioning, launchd services, dev→UAT→PROD slots,
                                 build-agent isolation, backup-ready encrypted data dir, mlx-openai-server,
                                 ports/interfaces scaffolding)                              — depends: ADR-002
M1  Walking-skeleton brain       (Gateway→Brain→Skills→Heartbeat skeleton, Qwen3-4B responder, semantic
                                 router, tool registry + manifest contract, ONE trivial tool, TEXT surface
                                 via dev CLI/loopback, end-to-end ask→answer)               — depends: M0
M2  Security wall + identity/scope (owner/guest, SQLCipher-per-scope, Secure-Enclave key)   — depends: M1
                                 ← apex-security THREAT-MODEL GATE fires here, before any sensitive store
M3  Knowledge layer              (ingestion pipeline + adaptive RAG on LanceDB hybrid+rerank; born encrypted) — M2
M4  Memory                       (two-store episodic+semantic, auto-inject; born encrypted)  — depends: M1,M2
M5  Voice + speaker-ID           (wake/STT/TTS/VAD/AEC + ECAPA speaker-ID → scope)           — depends: M1,M2
M6  Proactive engine             (Heartbeat hooks + ntfy)                                    — depends: M1
M7  Teacher escalation + skills library + Curiosity loop                                     — depends: M1,M3
[core→spoke boundary] → SwiftUI iPhone/iPad client + Telegram + Tailscale remote
M8+ Spokes, incrementally behind the manifest contract                                       — depends: M1(+M2 for sensitive)
```

**STOPPED HERE — next question (unanswered):** which value clusters form the FIRST WAVE of spokes (M8+).
Guidance set for next session: the very FIRST spoke should be non-sensitive (validates the manifest contract
before sensitive modules go behind the security gate). Clusters on the table (from the phase-2 capability map):
- Productivity & time (Calendar·Tasks·Projects·Habits/Goals·Travel — mostly non-sensitive, classic backbone)
- Knowledge & capture (Notes/Journal·Document input·Quote — Quote/Notes = lowest-risk first spoke; Journal sensitive)
- Awareness & inbound (News·Web crawler·Comms — Comms needs Gmail/Telegram connectors + is sensitive)
- Money/Health/Home (Finance·Health·Doctor/Vet sensitive=post-gate; Cooking·Shopping·Smart-home non-sensitive)

**Still to do in phase 6 after spokes are prioritised:** (1) connector build-timing (default: just-in-time with
first dependent module; connector *framework* is part of core ingestion/integration layer) · (2) slice each
milestone into DeepSeek specs applying the ≤3-files / ≤2-phases split rule → the spec queue · (3) then post-SP0
`apex-init` drains into REQUIREMENTS.md / ROADMAP.md + SP4 app defaults (autonomy L3 + lean profile +
security/AI specialists).

## Where I stopped (2026-06-03, session 4 — phase 6 roadmap)
**Mode:** SP0 phase 6 (roadmap → build order). Resolved: core-complete philosophy · security wall moved up ·
voice in-core · client at core→spoke boundary · the M0–M7 core spine order (all LOCKED, above).
**Next question to resolve:** first-wave spoke selection (interrupted). **Then:** connector timing → spec
queue slicing → post-SP0 apex-init.

---

## SP0 phase 6 — first-wave spokes + build strategy (2026-06-04 session 5, LOCKED)

**First wave = Productivity & time (non-sensitive backbone + Gmail connector).** Build order inside the wave:
```
1. Tasks            — pure module, no connector → VALIDATES the manifest contract end-to-end (first spoke)
2. Calendar         — pure module, manual events first
3. Gmail connector  — just-in-time (first dependents = Calendar + Tasks)
4. Calendar/Tasks email-extraction (Gmail-fed)
5. Projects
6. Habits/Goals
```
**Travel = PARKED** ("maybe — revisit after the productivity backbone is in daily use"). Reasoning recorded:
only the *auto spend-from-transactions* pull is blocked (needs Finance, a later sensitive wave); a *manual*
trip budget would be Travel's own field, not Finance. User chose to drop it for now rather than ship a
two-pass module. (Finance sensitivity note: **all finance numbers** — amounts, balances, income, sub-tracker
amounts — are sensitive; only the module scaffolding/category-names are not.)

**Waves 2+ = SOFT roadmap (non-binding, revisit after wave 1 in daily use):** 2 Knowledge & capture (Notes·
Document input·Quote; Journal gated) → 3 Awareness & inbound (News·Web crawler·Comms; Comms reuses the
wave-1 Gmail connector + adds Telegram) → 4 Home & living (Cooking·Shopping·Smart-home; needs HA connector) →
5 Money (Finance) → 6 Health & body (Health·Doctor·Vet·Wearables). Intelligence (Analysis·Deep Research) +
Dev workstation = core-adjacent/meta, sequence whenever wanted.

**Connector build-timing (LOCKED, default):** the connector *framework* (integration/ingestion layer) is
**core** (scaffolded M0–M1). *Individual* connectors are built **just-in-time with their first dependent
module** → Gmail = wave 1, Telegram = wave 3 (Comms), Home Assistant = wave 4, Weather = when briefing/travel
needs it, Wearables = wave 6. No connector built before something consumes it.

**⚠️ BUILD STRATEGY CHANGED (user, 2026-06-04): front-load ALL specs → batch handoff.** User does not have the
Mac Mini yet. Plan = **spec as many milestones as possible NOW** (planning mode runs on the PC), accumulate
them in `docs/changes/`, then **hand the whole queue to DeepSeek at once when the Mini arrives** and build
everything. Reverses the prior "slice M0, interleave just-in-time" default. Staleness risk is LOW (nothing
builds in between; every spec written against the same locked architecture). **Mitigation: spec in strict
dependency order (M0→M1→…→spokes), each spec written against the LOCKED contracts/interfaces of the ones
before it, never against unwritten implementation detail.** apex-init still runs first to formalize
REQUIREMENTS/ROADMAP as the spine.

**Spec queue (ordered units to write):** `M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7 → [client] → wave-1 spokes
(Tasks → Calendar → Gmail connector → email-extraction → Projects → Habits/Goals) → waves 2+ (soft)`.

---

## Gmail ingestion design (2026-06-04 session 5 — wave-1 connector; → see ADR-003)

_Designed ahead of build because it stress-tests the core ingestion-pipeline contract (M3) and forced an
ADR. The Gmail connector spec lands at wave 1; this is its design basis._

**Pipeline shape (per structural call #1 — thin connectors, smart core):**
```
Gmail connector (thin)                Core ingestion pipeline (M3, smart)              Targets
auth + fetch + normalize ──emit──►    classify → embed → extract → route          ──► • Knowledge index (LanceDB)
to a standard "ingestable             dedup (by Gmail msg id), store                   • Calendar (event extraction)
 document" shape                      all owner-private, behind M2 wall                • Tasks (action-item extraction)
   └── also exposes LIVE tools (search_email, get_thread) per the hybrid live+push model
```

**Decisions forced by locked architecture (not open):**
- **Pull, not push.** Gmail `users.watch` push needs a public Pub/Sub webhook → violates the locked
  no-public-surface/local-only posture. Artemis **polls** the History API on a **Heartbeat (M6) schedule**.
  ⚠️ Implication: "new email" reactions are poll-interval-bounded (~1–5 min), **not instant** (accepted).
- **Sync:** initial **full backfill** (`messages.list`→fetch) once, then **incremental** via `historyId`
  (`history.list`); if `historyId` expired (~days retention) → full resync. Dedup key = immutable Gmail
  **message id** (store-before-record).
- **Auth:** OAuth2 **installed-app loopback** (`127.0.0.1` redirect), `access_type=offline`; refresh token
  stored **encrypted owner-private** (SQLCipher / Secure-Enclave-wrapped). Single account = owner's.
- **Scope:** start **`gmail.readonly`**; `gmail.modify` (label "processed") deferred unless wanted.

**Ingestion depth (user choice — between selective & hybrid):** **scan ALL, persist only what qualifies.**
Every email is examined; only matching emails are stored+embedded+extracted; non-matching are examined and
dropped. A lightweight **"seen" ledger** records every scanned message's **id + verdict** (even discards) so
incremental sync never re-judges the same email. → *content selective, seen-record complete.* "Scan all" =
full inbox once (backfill), then every new email thereafter (not a re-scan each poll).
```
fetch (all backfill / new on poll) → cheap triage per email → IN? ─yes─► store raw(enc) + embed + extract → Calendar/Tasks/knowledge
                                                            └─no──► record id+verdict in seen-ledger, drop content
```

**Triage = teacher-creates-rules → applied as AUTOMATION (the key pattern; → ADR-003).** Distilled rules run
the triage; the teacher authors them. **Method/data split (forced by local-only invariant):**
- **Claude (cloud teacher)** = the **method** only (framework, categories, edge-case logic) from
  synthetic/cleared examples. **Never sees real email at runtime.**
- **Local teacher (Qwen3-14B)** = all content-touching work — induces concrete rules from the real inbox +
  judges ambiguous emails.
- **Bounded bootstrapping exception (owner-gated):** owner **hand-selects** specific emails and **pair-authors
  rules with Claude interactively** ("what to look out for" → consensus on a rule). **Claude may *request* more
  samples** to firm up a rule, but **asking ≠ accessing** — owner remains the egress gate. Full audit log;
  finance/health/journal hard-excluded. After the window, Claude reverts to method-only.
- **Applying a finalized rule = automation** (deterministic, token-free, instant) — locked
  "automation-over-AI." AI only runs to *author/refine* rules + judge *novel* ambiguous emails (which then
  become new rules → AI-need shrinks). **Triage** matures to near-pure automation; **extraction** is mixed
  (parsers for structured/templated senders; local-AI for freeform, also distillable). AI spend decays to the
  novel edges.
- **Rule-growth lifecycle:** bootstrap induction → Curiosity Loop (M7, local, ongoing) → owner feedback
  ("should've captured" / "stop capturing") → re-bootstrap (new account/patterns, fresh cleared sample).
- **Dependencies:** rides **M2** (wall/audit) + **M7** (teacher/skills/curiosity) — both core, before wave-1
  Gmail. No ordering conflict.

**Captured to:** `docs/technical/adr/ADR-003-teacher-email-bootstrapping.md`.

---

## Where I stopped (2026-06-04, session 5 — first-wave spokes + Gmail design)
**Mode:** SP0 phase 6 continued. **Resolved this session:** first wave = Productivity & time + Gmail (order
above) · Travel parked · waves 2+ soft roadmap · connector timing (just-in-time) · **build strategy flipped to
front-load-all-specs → batch handoff when Mini arrives** · full Gmail ingestion design (→ ADR-003 written).
**Phase 6 remaining:** (1) slice milestones into DeepSeek specs in dependency order (M0 first) applying the
≤3-files/≤2-phases split rule · (2) post-SP0 `apex-init` to formalize REQUIREMENTS.md / ROADMAP.md + SP4 app
defaults (autonomy L3 + lean profile + security/AI specialists). **Next step (planning default):** run
`apex-init` to lay the REQUIREMENTS/ROADMAP spine, THEN begin speccing M0 (appliance foundation).

---

## SP0 phase 6 — core-design preference forks LOCKED (2026-06-04 session 6)

_User strategy: front-load ALL specs → batch handoff when Mini arrives. Decided to "design the entire core"
first; resolved the brain.md owner-judgment forks before speccing. Specs written against ports (stable);
build-time empirical spikes become gated first-tasks inside the owning milestone's spec._

**The 8 preference forks (all LOCKED):**
1. **macOS target = require macOS 26** — Apple's built-in VM sandbox (strongest code-exec isolation); 2026 Mini ships with it. (M0/M2)
2. **Sensitive reasoning = fake stand-ins by default + owner-gated per-case raw-to-Claude override.** Claude designs the method on synthetic data; local model runs on real data; owner may per-case show Claude real data. Redaction rejected (leaky); override kept (not fully-local). Extends ADR-003's owner-gated pattern to reasoning. (M2 sensitivity router — ADR at apex-init)
3. **Embedding = start 0.6B, upgrade to 4B only if eval proves it.** (M3)
4. **Visual-document understanding = IN from day one** (charts/layouts; overrides brain.md "later"). Vision model + resident-vs-lazy = M3 sizing spike. (M3)
5. **Memory = custom bitemporal store on SQLCipher + sqlite-vec → ADR-004.** LanceDB can't encrypt at rest → memory vectors in sqlite-vec inside the encrypted file; LanceDB = docs only. Mem0 algorithm + 4-timestamp bitemporal + decay; Graphiti = upgrade. Research: `docs/research/memory-engine-research.md`. (M4/M3/M2)
6. **Voice plumbing = custom thin wiring (+ Wyoming plug for multi-room later).** Forced by the Swift VoiceProcessingIO AEC sidecar owning audio I/O. Apple ChipChat (arXiv 2509.00078) = validated blueprint. Pipecat = fallback if AEC sidecar dropped. (M5)
7. **Voice (TTS) = Kokoro-82M.** Benchmark Kyutai Pocket TTS in build; Chatterbox-Turbo = premium upgrade. All behind TTS port. (M5)
8. **Recipes (RENAMED from "skills") = auto-enable clearly-safe; gate data/action-touching for owner approval; + review surface (owner sees auto-enabled recipes, each plain-language explained).** Use "recipe" not "skill" — memory `recipe-not-skill-terminology`; brain.md/overview.md still say "skill" → fix on next revision. (M7)

**New ADR:** ADR-004 (memory engine). **To ADR at apex-init:** #2 (into sensitivity-router ADR); #1/#3/#4/#6/#7/#8 fold into the brain.md→ADR set.

## Where I stopped (2026-06-04, session 6 — preference forks + memory/voice research)
**Mode:** SP0 phase 6, "design the entire core." All 8 preference forks LOCKED (table above), memory + voice
researched via 4 parallel agents (ADR-004 + memory-engine-research.md written). **In progress:** M0 spec
sheets being drafted in the background (docs/drafts/m0/). **Next:** review M0 drafts → then design M1
(walking-skeleton brain) → M2 … down the core spine; each milestone → Deep Details spec(s), ports stable,
spikes as gated first-tasks. apex-init (REQUIREMENTS/ROADMAP + SP4 defaults) still pending — run around the
core spec batch.

---

## 2026-06-04 — IDEA: presence-aware unlock ("coming home = unlock the system")

_Captured to braindump (raw idea, NOT locked). Surfaced during the M5 voice review. This is an
enhancement layered on the locked M2 unlock model — for a dedicated **unlock-UX design pass later**
(post-core), not a core-build blocker._

**The want (Jarvis feel):** when I come home / am physically present, Artemis is just ready — I don't
want to fish out my phone and do a full unlock every time. "Coming home = unlock."

**The honest security boundary (from the discussion):** *presence ≠ proof it's me.* My phone being home
doesn't prove I'm holding it (left on the counter; a housemate has it; I'm home but so is a guest). So
**presence must NOT be the sole key to Tier-1 sensitive data** (finance/health/journal) — that would
re-open the in-home blast radius the owner↔guest wall + phone-attest unlock (ADR-005) exist to close.
Presence is a great *convenience* signal, not an authentication factor (it's ambient + spoofable + not
possession-bound).

**Recommended direction = presence as a CONVENIENCE MODIFIER, not the key:**
- **Home → frictionless, not automatic:** when home (phone on LAN / Watch present), offer a **one-tap /
  Watch-tap** unlock instead of the full phone flow — almost automatic, but one deliberate "yes it's me"
  still happens.
- **Home EXTENDS the session:** after that one unlock, being home keeps the session unlocked **longer**
  (longer idle timeout). Unlock once on arrival, stays open while I'm around. ("Home extends," not
  "home unlocks.")
- **Optional "home comfort tier":** presence alone could open slightly-more *convenience* features
  (NOT finance/health/journal) — a middle tier between Tier-0 and Tier-1. (Adds complexity; optional.)
- **Most-sensitive actions** (send money, irreversible) can still want a fresh tap regardless.
- **Dial = household-trust call:** fully-trusted solo household → can relax further; guests/housemates
  around → keep the biometric gate. Keep *first* Tier-1 access per session behind one explicit biometric;
  presence removes the *friction*, not the *factor*.

**Detection mechanisms already in the vision:** phone on home LAN / geofence · BLE proximity to the Mini ·
Watch present · homelab / Home-Assistant presence (mmWave/occupancy). Ties to the watch (CircuitMess +
phone-BLE bridge) + the homelab presence work + multi-device topology.

**Relates to:** ADR-005 (phone-attest unlock) · ADR-006 (Tier-0/Tier-1) · M5-c (voice-ID≠key) · the
deferred "further unlocks" list (re-assert-for-risky · per-task unlock windows · Watch/hardware-key
unlock · step-up tiers). → revisit in the unlock-UX design pass.
