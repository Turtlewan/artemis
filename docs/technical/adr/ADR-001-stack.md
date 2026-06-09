# ADR-001 — Technology Stack

**Status:** Accepted (SP0 phase-5 stack re-confirm, 2026-06-03)
**Supersedes:** the provisional "SwiftUI + Python" seed (now formally confirmed against the full SP0 decomposition)

## Context
Artemis is a private, local-first personal-assistant platform (see `docs/technical/architecture/overview.md`):
native iPhone/iPad clients + an always-on local-server "brain", voice + text co-equal, <1s react, data-heavy
(a growing RAG "second brain"), single household. **AI writes most of the code** (DeepSeek builds on the Mac
Mini; the owner does not hand-code on the box) → per APEX selection criteria, **AI-buildability and
verifiability outweigh team familiarity.** Hard constraints gate the choice: local-only for sensitive data,
Apple Silicon + MLX for local inference, OSS AI stack, must run on a 48GB Mac Mini, native Apple security/voice
APIs. Stores chosen behind ports (`brain.md` upgradeability) so individual swaps don't cascade.

## Decision
A **native polyglot stack** — Python brain + Swift app/sidecar — on a dedicated Mac Mini appliance.

| Component | Choice |
|-----------|--------|
| Client app | **SwiftUI** (iPhone/iPad, native) |
| Brain / services | **Python** (typed, async, FastAPI-style; `uv`/`ruff`/`mypy`/`pytest`) |
| Inference runtime | **MLX** via `mlx-openai-server` (OpenAI-compatible seam) |
| Knowledge / vector store | **LanceDB** (embedded) |
| Relational + crypto wall | **SQLite + SQLCipher** (per-scope encrypted DBs; key in Secure Enclave) |
| Graph / memory | **Kuzu (via Graphiti)** or **Mem0 OSS** — parked spike, behind `MemoryStore` port |
| Audio sidecar | small **Swift** component (Apple VoiceProcessingIO AEC) |
| Cloud teacher | **Claude Opus via the owner's subscription** (Claude Code headless), bootstrapping only — see ADR note |
| Notifications | **ntfy** |
| Integration contract | internal **tool registry**; **MCP at the edges** only |
| Deployment | bare-metal **Mac Mini M4 Pro (48GB)** appliance + cloud teacher (non-sensitive) |

**Teacher (refines `brain.md`):** Claude Opus is **the single teacher across all domains**, driven through the
owner's **Claude subscription (Claude Code headless), NOT the Anthropic API** — flat-rate quota, not per-token
billing. Boundary: **Claude teaches the *method* (skills), never sees sensitive *data*.** The local model
(**Qwen3.6-27B** → larger on a future Studio; see 2026-06-08 refinement) executes those skills on real
sensitive data and is the sensitive reasoner. DeepSeek demoted to an optional cheap non-sensitive fallback. Cloud tiers are **non-sensitive only**
(consumer-subscription data handling ≠ the API no-train default — set training opt-out). Wind-down trigger
deferred to build.

## Runner-ups ruled out
- **Client — Expo/React Native:** abstracts away the native Apple APIs the security + voice design depends on
  (Secure Enclave/Keychain for the crypto wall, VoiceProcessingIO AEC, CoreML/ANE STT, Face/Touch ID). No
  Android requirement. → SwiftUI wins decisively.
- **Brain — TypeScript/Node:** the entire local AI/RAG/voice ecosystem is Python-first (MLX, LanceDB, Docling,
  rerankers, SpeechBrain, fast-graphrag, Graphiti/Mem0, RAGAS). AI-buildability + requirements-fit → Python;
  verifiability bought back with `mypy --strict` + `ruff` + tests.
- **Relational — PostgreSQL (the usual default):** deliberate deviation. Single-box appliance needs no DB
  server; SQLCipher's per-file encryption *is* the owner↔guest privacy wall (structural, not a `WHERE` clause).
- **Vector — sqlite-vec / pgvector:** sqlite-vec is brute-force (fails <1s past ~1M vectors); pgvector needs a
  Postgres server. LanceDB is embedded + ANN + built-in hybrid/RRF.
- **Inference — llama.cpp/Ollama:** slower on Apple Silicon than MLX; less clean swap seam.

## Consequences
- **Polyglot** (Python + Swift) — two toolchains, but each is the right tool (Python = AI ecosystem; Swift =
  native Apple security/voice). The Swift audio sidecar is an unavoidable native bridge.
- **High-lock-in items confirmed intentionally:** SwiftUI (client framework) and Python (brain language) are
  near-rewrite to change — accepted, justified by hard constraints. Stores are medium-lock behind ports.
- **Deviation from PostgreSQL default** is intentional and documented (local embedded + per-file encryption).
- **Cloud teacher via subscription** carries operational fragility (OAuth login kept alive on the Mini; CLI/SDK
  adapter, not a base-URL swap) and consumer-tier data handling → strictly non-sensitive, bootstrapping-scoped.
- **Coverage gate:** `stack_skills: [apex-python, apex-swift]` (both have Verification Recipes). **Recorded
  gaps** (Artemis-specific, build on base-model + domain skills, do not author yet): MLX/local-inference,
  LanceDB, the voice pipeline (openWakeWord/Parakeet/Kokoro/Silero/SpeechBrain). Domain skills `apex-ai-systems`,
  `apex-search`, `apex-security`, `apex-data`, `apex-realtime`, `apex-homelab` cover the concepts.

## Parked (component spikes, behind ports — decided at build)
Graphiti-vs-Mem0 · embedding tier 0.6B/4B · teacher 30B-A3B/dense-32B (local upgrade path) · macOS 26 target ·
Swift-vs-Python AEC · mic plain/XMOS · Pipecat vs HA/Wyoming · the teacher wind-down trigger.

## Refinement (2026-06-08 — brain/AI research sweep)
Re-validation pass (`docs/research/2026-06-08-brain-ai-improvements-synthesis.md`):
- **Sensitive reasoner = Qwen3.6-27B** (dense, ~18GB 4-bit, fits the 48GB box with ~23GB headroom; GPQA 87.8 / SWE-bench 77.2) — replaces the Qwen3-14B placeholder. Responder unchanged (Qwen3-4B-Instruct-2507); still the best sub-5GB tool-caller on MLX.
- **Runtime:** pin `mlx-openai-server` 1.8.1 (multi-model YAML, idle-unload TTL, qwen3 tool-parser); **do NOT enable mlx-lm speculative decoding on Qwen3** (skipped-token bug #846) — use Qwen3.6 native MTP instead.
- **Hardware lock HELD (M4 Pro 48GB) pending WWDC 2026 (this week).** The decisive lever is the **64GB RAM tier**, not the M5 Pro chip: a Mac Mini caps at 64GB on M4 Pro and M5 Pro alike; the M5 Pro adds GPU speed (3–4× prefill, +20–30% gen), not headroom. 64GB would let Qwen3.6-27B dual-role as a local non-sensitive teacher (~80% of teacher load) and clear the GraphRAG spike's hardware bar (ADR-007). If WWDC announces an M5 Pro Mini with 64GB BTO ≤ ~S$3,600 → buy it; else 64GB-on-M4-Pro is the same headroom, available now. Re-decide §Deployment after WWDC.

## Refinement (2026-06-09 — post-WWDC hardware decision)
WWDC 2026 was **software-only — no M5 Mac Mini announced** (`docs/research/wwdc-2026-stack-implications.md`;
MLX serving path on M4 Pro unchanged). **Owner decision: WAIT for the M5 (Pro) Mac Mini** rather than buy
an M4 Pro now. Rationale: the 64GB ceiling is **identical on M4 Pro and M5 Pro**, so waiting costs **zero
memory headroom** and gains the M5 Pro's GPU speed-up (~3–4× prefill, +20–30% gen); the build is fully
front-loaded (specs accumulate in `docs/changes/`), so the wait has **no idle cost**.
- **Target config when buying = M5 (Pro) Mac Mini, 64GB.** The 64GB tier (not 48GB) is the lock: it lets
  Qwen3.6-27B dual-role as a local non-sensitive teacher, clears the GraphRAG hardware bar (ADR-007), and
  widens the local fine-tune envelope to 32B-dense / safe 30B-A3B MoE
  (`docs/research/self-training-local-model.md`).
- **Re-evaluation trigger:** M5 (Pro) Mac Mini announcement → confirm 64GB BTO at acceptable price, then
  buy. Reopen the 48-vs-64 question **only** if the M5 Mini's RAM ceiling unexpectedly differs from 64GB.
- **§Deployment stays "M4 Pro 48GB" as the *minimum-spec* reference** until the M5 purchase; nothing in the
  spec queue hard-codes a RAM size (specs target the 48GB floor, so a 64GB buy is pure headroom).
