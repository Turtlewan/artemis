# Artemis Integration Constraints: Remote LLM Expansion via Mac Mini Brain

**Date:** 2026-06-13  
**Status:** LOCKED — full integration analysis for the Mac Mini brain → remote inference expansion (future ACI P3 GPU phase).

**Scope:** How models are currently bound in Artemis specs, what seams exist for remote inference, security/architectural constraints that apply to a networked box on the Tailscale-connected homelab, and what assumptions would break.

---

## 1. Current Model Binding Architecture

### 1.1 Model Endpoint Configuration Seam (M0-c + M1-b)

**Binding location:** `config/roles.toml` (per-slot) → resolved at runtime via `ModelRole` + `Settings`  
**Source specs:**
- **M0-c (mlx-openai-server install + config)**, lines 10, 33: "wires one config entry per logical model role into M0-a's roles.toml so the brain reaches models by role, not by physical endpoint"
- **M0-c Task 3**, lines 33, 43: `config/roles.toml` modified to set every `adapter = "openai"` role's `endpoint` to `http://127.0.0.1:{MLX_PORT}/v1` (render placeholder per slot)
- **M0-c Task 6**, lines 35–36: `model_client.py` exports `base_url_for_role(role: str, s: Settings) -> str` returning `s.roles[role].endpoint` for OpenAI-compatible adapters
- **M1-b Assumptions**, line 19: "The `OpenAIModelPort` resolves ANY openai-adapter role generically via the M0-c base-URL seam (`base_url_for_role`/`model_id_for_role`) — NOT hardcoded to responder/embedder"

**Seam detail:**
```toml
# config/roles.toml (M0-a structure; M0-c Task 3 modifies)
[roles.responder]
adapter = "openai"
endpoint = "http://127.0.0.1:{MLX_PORT}/v1"  # render placeholder
model_id = "Qwen3-4B-Instruct-2507"

[roles.sensitive_reasoner]
adapter = "openai"
endpoint = "http://127.0.0.1:{MLX_PORT}/v1"  # same mlx server
model_id = "Qwen3.6-27B"

[roles.embedder]
adapter = "openai"
endpoint = "http://127.0.0.1:{MLX_PORT}/v1"
model_id = "Qwen3-Embedding-0.6B"

[roles.teacher]
adapter = "claude-cli"  # NOT openai; runs via Claude subscription
```

**How models are called:**
- **M0-d (Seam 1: ModelPort contract)**, lines 34, 71–80: `async def complete(self, *, role: str, messages: [...], response_schema: dict | None = None, temperature: float = 0.7, max_tokens: int | None = None) -> ModelResponse`
- **M1-b Task 3**, lines 57–58: `OpenAIModelPort` constructed from `Settings`; resolves per-role base URL via `base_url_for_role(role, settings)` and model id via `model_id_for_role(role, settings)`
- **M1-b Task 3**, line 58: calls the OpenAI-compatible `/v1/chat/completions` with resolved base URL

**OpenAI-compatible interface (mlx-openai-server 1.8.1):**
- **M0-c Assumptions**, lines 16–18: `mlx-openai-server 1.8.1` uses multi-model YAML config, `tool-call-parser: qwen3`, OpenAI `response_format` JSON-schema + Outlines for structured output
- **M0-c Task 2**, lines 33–34: `config/mlx-models.yaml` defines model list with per-model `on_demand` + `on_demand_idle_timeout` for lazy/idle-unload

### 1.2 Model Roles Defined (Current Setup)

**From contracts.md (Seam 1) and M0-c/M1-b tasks:**

| Role | Model | Adapter | Source | Purpose | Stay local or can move? |
|------|-------|---------|--------|---------|------------------------|
| `responder` | Qwen3-4B-Instruct-2507 | `openai` (mlx) | M0-c, M1-b Task 5 | Fast tool-calling, routing, free-form responses | **Can move** — via `base_url` config |
| `sensitive_reasoner` | Qwen3.6-27B | `openai` (mlx) | brain.md §Memory, M0-c | Sensitive data extraction (finance/health/journal), memory A.U.D.N. | **MUST stay local** — security wall (never cloud) |
| `embedder` | Qwen3-Embedding-0.6B | `openai` (mlx) | M0-c Task 2, M1-b | Router + retrieval embeddings | **Can move** — via `base_url` config |
| `reranker` | Qwen3-Reranker-0.6B | (M3-d, not yet specced) | M3-d research | Cross-encoder rerank | **Can move** — via port adapter |
| `teacher` | Claude Opus | `claude-cli` | ADR-001, M0-c | Distillation, deep-research (non-sensitive) | **Stays cloud** — subscription, not local |
| `research_orchestrator_standard` | DeepSeek | `openai` (API) | DR-c | Research queries (non-sensitive) | **Stays cloud** — API |
| `research_orchestrator_deep` | Claude Opus | `claude-cli` | DR-c | Research (non-sensitive) | **Stays cloud** — subscription |

### 1.3 Async Port Surface (ADR-015)

**From contracts.md (Seam 1, amended 2026-06-11):**

Network-I/O model methods are `async`:
- `ModelPort.complete(role, messages, response_schema=None, temperature=0.7, max_tokens=None)` — **ASYNC** (M0-d, M1-b Task 3)
- `ModelPort.complete_stream(role, messages, temperature=0.7) -> AsyncIterator[str]` — **returns async iterator** (M0-d, M1-b Task 2)
- `ModelPort.embed(role, texts) -> list[Vector]` — **ASYNC** (M0-d Task 4, M1-b)
- All callers `await` these; any method calling them becomes `async` (M1-b, M4-b, M3-a, etc.)

**Implication for remote:** async design is already in place; a remote HTTP endpoint via OpenAI-compatible protocol fits cleanly without refactoring caller sites.

---

## 2. What Exactly Needs to Change for Remote Inference

### 2.1 Config-Only Changes

**Files to change (no code rewrites):**

| File | Change Type | Specific Change | Impact |
|------|------------|-----------------|--------|
| `config/roles.toml` | **Config-only** | Change `endpoint` from `http://127.0.0.1:{MLX_PORT}/v1` to `http://{REMOTE_GPU_BOX_IP}:4000/v1` (or via LiteLLM proxy hostname on Mini) | **NO code change** — responder/embedder endpoints resolve dynamically from `Settings`; a second `roles.toml` file per environment (or an env-var override) and `base_url_for_role()` handles it. |
| `config/roles.toml` | **Config-only** | Keep `sensitive_reasoner` pointing to `http://127.0.0.1:{MLX_PORT}/v1` (local only) | **NO code change** — the sensitivity router gates which role can be called; local stays hardcoded to local. |
| `.env` / slot-specific config | **Config-only** | Add `REMOTE_GPU_INFERENCE_HOST` env var; M0-c's `render_plists.py` substitutes into `roles.toml` at deploy time | **NO code change** — same pattern as `{MLX_PORT}` render placeholder. |

### 2.2 Architectural Seams (No Structural Changes Required)

**Why remote works without refactoring:**

1. **ModelPort is a Protocol, not a class** (M0-d, line 11): `class ModelPort(Protocol)` with method bodies `...` only. `OpenAIModelPort` is a thin adapter over the OpenAI-compatible seam.

2. **Adapter is role-agnostic** (M1-b Assumptions, line 19): "resolves ANY openai-adapter role generically via the M0-c base-URL seam; NOT hardcoded to responder/embedder."

3. **No hardcoded localhost references** (M0-c, M1-b): the entire endpoint is pulled from `settings.roles[role].endpoint` at runtime. A grep for `127.0.0.1` or `localhost` in caller code would expose any hardcoding; if found, it's a bug, not a design constraint.

4. **OpenAI-compatible protocol is the swap seam** (M0-c, line 10; brain.md): "The OpenAI-compatible API is the swap seam — swap runtime/relocate a model = change a base URL."

### 2.3 Structural (Code) Changes — Per-Role Constraint Enforcement

**What requires NEW code (not rewrites):**

| File | Change Type | What's needed | Why | Code or config? |
|------|------------|---------------|-----|-----------------|
| `src/artemis/sensitivity_router.py` (hypothetical, M3+) | **NEW logic** | Enforce `role="sensitive_reasoner"` calls only resolve to local endpoint (not a network call) | **Security hardening:** prevent future code from accidentally routing sensitive roles to a remote box via a typo or config error | **Code** — runtime assertion in the adapter or router that `sensitive_reasoner` endpoint is `127.0.0.1` or raises `SensitiveRoleRemoteProhibited`. |
| `config/roles.toml` + `M0-a Settings` | **Config validation** | Add a validation rule: any role with `is_sensitive=true` tag must have `endpoint == "http://127.0.0.1:*"` or raise at Settings-load | **Security hardening:** catch typos/misconfigs at boot, not at runtime | **Code** — Pydantic validator on `ModelRole`; config schema change is minimal. |

---

## 3. Security & Tier System Constraints

### 3.1 The Crypto Wall (M2 — ADR-005, ADR-007)

**From overview.md § security wall + ADR-005/ADR-007:**

- Per-scope SQLCipher DB + per-scope encrypted APFS volume (LanceDB), each behind a 32-byte DEK
- DEK is ECIES-wrapped to a Secure-Enclave key (non-exportable)
- **LaunchAgent broker** on the Mini is the ONLY process that touches the SE key; exposes tiny local IPC to the brain
- On phone unlock: broker unwraps DEK → hands brain a **transient, mlock'd, session-only** key
- **Rule:** "Neither DEK nor biometric ever crosses the wire" (overview.md)

**Implication for remote inference:**
- **All data-bearing model calls (embeddings, memory extraction) must run on local models ONLY**
- A remote model endpoint cannot receive:
  - Raw embeddings of sensitive docs (would expose knowledge in transit)
  - Raw memory facts or entity names (would expose identity)
  - Finance/health/journal text (hardest rule — overview.md § privacy policy, brain.md § Tier)

### 3.2 Sensitivity Tier System (brain.md § Cloud / privacy policy)

**From brain.md lines 150–167:**

| Tier | Endpoint | May process |
|------|----------|-------------|
| **Local** (MLX on Mini) | `127.0.0.1:{mlx_port}` | Anything, incl. sensitive (finance/health/journal/episodic/PII) |
| **Claude** (subscription) | Claude Code headless | **Non-sensitive only**; heavy reasoning + distillation |
| **DeepSeek** (trains, CN) | API | **Non-sensitive only** — hardest gate |

**Router rules (lines 150–162):**
1. Deterministic **provenance gate** — anything from a sensitive store or carrying PII is hard-blocked from cloud (structural, via the CaMeL data plane)
2. Local zero-shot classifier for free-text
3. **Fail-safe → LOCAL when unsure**

**What must NEVER leave the box:**
- Finance, health, journal, episodic/personal memory, PII, secrets, any RAG chunk from personal stores

### 3.3 Role Mapping to Sensitivity Tiers

**From brain.md and ADR-001:**

- **Qwen3.6-27B (`sensitive_reasoner`):** Local ONLY. Executes skills on real sensitive data; memory extraction on finance/health; never cloud.
- **Qwen3-4B (`responder`):** Can be local OR remote (if call data is non-sensitive). Tool-calling for deterministic/automation tasks that don't touch sensitive stores.
- **Embedding models (`embedder`, `reranker`):** Can be local OR remote, BUT:
  - Embedding sensitive docs → **LOCAL ONLY** (the knowledge index is encrypted at rest; exposing embeddings + doc text to remote breaks the encryption)
  - Embedding non-sensitive queries (general routing) → can be remote

**In practice (today):**
- All local embeddings stay on the Mini (LanceDB inside the encrypted volume)
- A remote embedder would need to be gated to non-sensitive queries only (e.g., routing, not RAG)

### 3.4 Egress Filtering & Allowlist (ADR-009, brain.md)

**From overview.md § Untrusted content:**

- "Controlled-egress allowlist (default-deny), logged via OBS"
- Remote inference → all outbound calls to GPU box must be allowlisted
- **On Tailscale:** ACL rules already enforce device/network boundaries

**New rule for remote inference:**
- Add GPU box to Tailscale as a tagged device (e.g., `tag:gpu-inference`)
- Add ACL rule: `accept: {src: ["tag:artemis-mini"], dst: ["tag:gpu-inference"]}`
- Log all calls via OBS (already scoped to network ports)

---

## 4. Existing Assumptions That Would Break

### 4.1 Single-Machine Assumptions

**Search results for hardcoded local-only refs:**

From BRING-UP-RUNBOOK.md (Step 2e):
- `bash scripts/install_mlx.sh` — installs mlx-openai-server into project venv, creates model dir at `${ARTEMIS_MODEL_DIR:-/opt/artemis/models}` (Step 2e, line 91)
- **ASSUMPTION:** All models are on the Mini's local filesystem

**Impact:** If a remote GPU box serves models, the Mini needs NO local model weights for the responder (Qwen3-4B) — only for `sensitive_reasoner` (Qwen3.6-27B) stays local. **Change:** Make M0-c Task 4 conditional: pull only local-tier models; responder/embedder can skip if remote endpoints are configured.

From ADR-001 § Deployment (lines 209–223):
```
Local, always-resident (~15GB incl. macOS): responder Qwen3-4B · voice · embeddings + reranker · LanceDB + SQLite · orchestrator / sensitivity router / security.
Local, lazy-loaded (~33GB free): mid model (Qwen3-14B) for sensitive heavy reasoning.
Cloud (DeepSeek, NON-sensitive only): the whole teacher tier.
```

**ASSUMPTION:** Qwen3-4B responder is local; Qwen3.6-27B is local. **Impact:** If responder moves to GPU box, the "~15GB resident" estimate drops significantly. The "64GB tier unlocks GraphRAG" logic stays intact (27B still resident for sensitive).

### 4.2 Network Latency Assumptions

**From brain.md § latency budget (line 107):**
```
Latency budget: end-of-speech → first audio ~750–800ms (LLM TTFT dominates; mask with an instant ack).
```

**ASSUMPTION:** LLM latency is dominated by TTFT (time-to-first-token), masked by instant ack. **Impact:** Remote inference adds network RTT (~1–5ms on LAN, negligible) but may increase first-token latency if the GPU box is slow to load a model. **Mitigation:** GPU box should keep inference models resident (vLLM + model preload) to avoid cold-start penalty.

### 4.3 Local Model Directory Assumption

**From BRING-UP-RUNBOOK.md, Step 8b (parked P5):**
```
**PARK:** exact MLX model pull command — M0-c Task 4 GATED on-hardware; mlx-openai-server 1.8.1 weight-loading mechanism.
If pre-staged on SSD: copy into `/opt/artemis/models/`.
```

**ASSUMPTION:** Model weights live in `/opt/artemis/models/`. **Impact:** Remote inference → responder/embedder weights can skip the Mini. **Change:** M0-c should check `roles.toml` to see which models are local vs. remote, and only pull local ones.

---

## 5. How ACI (Artemis Cognitive Infrastructure) Already Frames Multi-Box Expansion

**From homelab-control-plane.md (lines 1–74):**

### 5.1 Phased Plan (P1–P4)

| Phase | Add | Artemis impact | Trigger |
|-------|-----|----------------|---------|
| **P1** | Mini runs MLX, LanceDB, SQLCipher, voice | New milestone: launchd plist authoring | Hardware in hand |
| **P2** | TrueNAS SCALE, NFS + MinIO | New spoke `aci-storage` | Corpus >50GB |
| **P3** | NVIDIA GPU box (RTX 3090/4090), vLLM, **LiteLLM proxy** | New spoke `aci-inference-router` | 70B latency locally unacceptable |
| **P4** | ESPHome, Jetson vision, IoT, HA MCP | New spoke `aci-home` | P3 stable |

### 5.2 GPU-Offload Integration Pattern (P3)

**From homelab-control-plane.md lines 26–31:**

```
Clean integration: a **LiteLLM proxy on the Mini** presents one `localhost:4000/v1` 
OpenAI-compatible URL; routing rules live in LiteLLM config — **zero Artemis code changes**.
Fast/voice → MLX; heavy inference + fine-tune → GPU box.
```

**How LiteLLM fits into Artemis today:**
1. LiteLLM proxy runs on the Mini as a sidecar daemon (launchd plist)
2. Proxy listens on `localhost:4000/v1` (or exposed to local network)
3. Proxy routes calls based on model id:
   - `Qwen3-4B-Instruct-2507` → local mlx-openai-server (fast)
   - `Qwen3-70B` or other → remote GPU box vLLM
4. Artemis code sees **zero change** — M0-c's `config/roles.toml` just points `endpoint = "http://127.0.0.1:4000/v1"` to the LiteLLM proxy instead of mlx-openai-server

**Implication:** No new Artemis seam. The OpenAI-compatible protocol + LiteLLM routing handles the dispatch.

### 5.3 Self-Training / Distillation Intersection (Ongoing Lane)

**From self-training-local-model.md (lines 34–47 "NOW vs LATER" + table):**

| Phase | Self-training role | Output |
|-------|-------------------|--------|
| **P0** | Define task categories; generate reasoning traces (Claude); judge-filter (DeepSeek) | versioned `datasets/distill/*.jsonl` + eval set |
| **P1** | 14B QLoRA LoRA runs on Mini (mlx-lm) | trained LoRA adapters |
| **P2** | Corpus + adapters migrate to NAS | NAS-backed training corpus |
| **P3** | Serious distillation (bigger student) + **DPO/RLAIF** using DeepSeek-judged preference pairs (RLHF stack is CUDA-only) | higher-capability student + preference-tuned adapters |
| **Ongoing** | Active-learning loop: capture local-model misses → Claude solves → append → periodic retrain | self-improving corpus |

**Relevance to remote inference:** The GPU box (P3) is the **home for DPO/RLHF training** (lines 46, "RLHF stack is CUDA-only"). A remote NVIDIA GPU box is not just a performance multiplier; it **enables the full self-training pipeline** that the Mini (MLX-only) cannot run. This aligns dual drivers for GPU box timing (performance + training capability).

---

## 6. What the Distillation/Self-Training Lane Requires from Inference

**From brain.md § teacher model (lines 169–206) + self-training-local-model.md:**

### 6.1 Teacher Call Path (M7-a, specced)

- **Claude Opus via subscription** (non-sensitive, heavy reasoning + distillation)
- **DeepSeek for non-sensitive analysis + as judge** (preference-pair generation)
- Both are cloud, not local inference

### 6.2 Distillation Output

- Trained LoRA adapters (P1–P3)
- Preference-pair dataset (P3, judged by DeepSeek)
- Deployed as hot-swap into the responder or lazy model

### 6.3 Training Workload

**From self-training-local-model.md line 56:**
- `mlx_lm.lora` QLoRA on Qwen3-14B — 2–4h on the Mini (P1)
- DPO/RLAIF — **CUDA-only** (Unsloth stack) — needs GPU box (P3)

**Inference role in training:**
- The responder (inference role) stays available during LoRA training (adapters are separate, LoRA is low-rank)
- After training, adapters can be hot-swapped into responder or the lazy reasoner
- A remote inference box **doesn't conflict** with local training; the two can coexist

---

## 7. Summary of Integration Seams & Change Scope

### 7.1 Seams That Support Remote Expansion

| Seam | Spec | Line | Current state | Remote-ready? |
|------|------|------|---------------|---------------|
| **ModelPort.complete(role, ...)** | M0-d | 34–40 | `async` protocol; role-parameterized | ✅ YES — role → endpoint lookup is dynamic |
| **base_url_for_role(role, settings)** | M0-c | 35–36 | Config-driven lookup; no hardcoding | ✅ YES — endpoint can be local or remote |
| **OpenAIModelPort adapter** | M1-b | 57–58 | Thin OpenAI-compatible HTTP client | ✅ YES — works with any base URL |
| **roles.toml endpoint field** | M0-c | 33 | Role → endpoint mapping | ✅ YES — render placeholder per slot |
| **Sensitivity router** (hypothetical M3+) | brain.md | 150–162 | Rules: local-only for sensitive | ⚠️ NEEDS CODE — enforcer for `sensitive_reasoner` |
| **LiteLLM proxy** (ACI P3 pattern) | homelab-control-plane.md | 26–31 | Proxy on Mini, routes by model id | ✅ YES — zero Artemis code change needed |

### 7.2 Breaking Changes (Would Not Work Without Refactor)

**None identified** in the current locked specs. The architecture is designed to support swappable endpoints via ports + config.

### 7.3 Risk Areas (Needs Validation or Hardening)

| Risk | Mitigation | Code or config |
|------|-----------|-----------------|
| **Sensitive data leakage via remote embeddings** | Only embed non-sensitive queries locally; enforce in sensitivity router | Code — add validation rule that RAG embedding calls resolve to local only |
| **Config typo routes sensitive role to remote** | Validation at Settings-load time | Code — Pydantic validator: `sensitive_reasoner` endpoint must be `127.0.0.1:*` |
| **GPU box model not resident, cold-start latency** | LiteLLM proxy + vLLM model preload + monitoring | Config (vLLM) + infra, no Artemis code |
| **Tailscale ACL misconfiguration** | ACL rules in homelab infrastructure; not Artemis code | Config — Tailscale ACL policy |

---

## 8. Files & Specs to Watch for Remote Expansion

### 8.1 Specs That Define Remote-Relevant Behavior

| Spec | Aspect | Notes |
|------|--------|-------|
| **M0-c (mlx-openai-server)** | Model binding seam | Lines 33–43 define `roles.toml` endpoint + render logic |
| **M0-d (ports)** | ModelPort protocol | Lines 34–40 define the async seam contract |
| **M1-b (router-brain)** | ModelPort adapter | Lines 57–58 implement `OpenAIModelPort` over base-URL seam |
| **M3-d (visual retrieval)** | Embedder routing | Will define Qwen3-Reranker callsite; ensure it uses role-based dispatch |
| **M4-b (memory write path)** | Sensitive reasoning | Calls `model.complete(role="sensitive_reasoner", ...)` — verify always resolves local |
| **M7-a2 (escalate/distill)** | Teacher role dispatch | Resolves `role="teacher"` → Claude CLI; teacher stays cloud (no change) |
| **DR-c (deep research)** | Research role dispatch | Uses `research_orchestrator_standard` (DeepSeek) + `research_orchestrator_deep` (Claude); both stay cloud |
| **OBS-b (observability)** | Call tracking | May log remote calls; ensure egress is logged and allowlisted |

### 8.2 Specs That Define Deployment/Config

| Spec | Aspect | Notes |
|------|--------|-------|
| **M0-a (package setup)** | Settings schema | Defines `roles: dict[str, ModelRole]`; ensure `ModelRole` includes `endpoint` field |
| **M0-b (launchd plists)** | Daemon orchestration | M0-c Task 3 fills `{MLX_LAUNCH_CMD}`; future P3 would add LiteLLM proxy plist |
| **BRING-UP-RUNBOOK** | Mini setup sequence | Step 2e (mlx install); P3 expansion adds GPU box setup + LiteLLM plist |
| **M0-e (build user isolation)** | Security boundaries | Sandbox ACLs on `/opt/artemis`; remote inference doesn't change this |

---

## 9. Concrete Next Steps for P3 GPU Expansion Spec (Future)

### 9.1 Pre-Spec Validation (Before ADR/Planning)

1. **Confirm LiteLLM proxy is the integration pattern.**
   - Write a minimal proof-of-concept: LiteLLM on Mini + vLLM on GPU box, route Qwen3-4B responder calls
   - Measure TTFT latency vs. local MLX (should be <50ms penalty on LAN)
   - Confirm `/v1/chat/completions` / `/v1/embeddings` work through proxy

2. **Test sensitivity router enforcement.**
   - Attempt to route `role="sensitive_reasoner"` through LiteLLM proxy to GPU box
   - Confirm the new validation rule (Config + Code) blocks it with a clear error

3. **Verify zero Artemis code changes for responder/embedder routing.**
   - Change `roles.toml` to point responder to GPU box via proxy
   - Run existing tests (M1-b, router + brain); confirm pass without code edits

### 9.2 Spec Structure (Rough Outline for P3 ACI-Inference-Router)

**File:** `docs/changes/aci-inference-router.md` (or split into `aci-inference-router-a` [config] + `aci-inference-router-b` [runtime])

**Identity:** Wire GPU box (vLLM) into Artemis via LiteLLM proxy on Mini; add enforcement for sensitive roles staying local.

**Tasks:**
1. Write LiteLLM proxy config (`config/litellm-models.yaml`)
2. Create LiteLLM launchd plist
3. Add `sensitive_reasoner` validation rule to `Settings` (Pydantic)
4. Update `BRING-UP-RUNBOOK.md` with GPU box setup + proxy startup
5. Update `homelab-control-plane.md` ACI section with tested numbers
6. Add tests: remote responder call passes; remote sensitive_reasoner call raises

**Permissions:** File creates (litellm config, plist), config edits (roles.toml), code edits (Settings validation).

**Commands:** LiteLLM config validation, pydantic validator test, integration test on Mini + GPU box.

### 9.3 Risk Gate (M2 Equivalent for Remote)

**Before P3 spec moves to `docs/changes/ready/`, a security gate must clear:**
- [ ] Confirm sensitivity router enforces `sensitive_reasoner` → local-only
- [ ] Confirm no data flows from encrypted stores (memory/knowledge) to remote embedder
- [ ] Confirm Tailscale ACL rules are written and tested
- [ ] Confirm egress is logged (OBS integration)

---

## 10. Alignment with Existing Docs

### From homelab-control-plane.md (ACI Framing)

- **P1 (now):** Mini + voice; launchd plist milestone
- **P3 (GPU):** LiteLLM proxy on Mini; new `aci-inference-router` spoke
- **Self-training:** GPU box is the home for DPO/RLAIF (P3); local LoRA training (P1) prepares dataset

**Alignment:** This analysis confirms P3 pattern is architecturally sound. No seam rewrites needed; config + LiteLLM routing + validation code.

### From brain.md § upgradeability (lines 225–231)

> Ports-and-adapters everywhere; the Brain depends only on ports: `Retriever` · `MemoryStore` (with `person_id` + `as_of` in signatures) · `EmbeddingModel` · `VectorStore` · `Reranker` · `Router` · `ModelPort` (OpenAI-compatible; **models referenced by logical role** "responder"/"teacher", **mapped in config**)

**Alignment:** This analysis is a direct consequence of the design lock. Role-based config mapping is the intended seam for future remote expansion.

---

## 11. Citation Index

### Specs & Documents Referenced

| Document | Relevant sections | Key lines |
|-----------|-------------------|-----------|
| **docs/technical/contracts.md** | Seam 1 (ModelPort), lines 16–50 | ModelPort async interface, ModelResponse with `origin`/`model_id` |
| **docs/technical/architecture/overview.md** | Security wall, Core brain, integration layer, lines 67–237 | Crypto wall, key broker, tier system, deployment |
| **docs/technical/architecture/brain.md** | Inference + models (lines 90–206), Upgradeability (lines 225–231) | mlx-openai-server, role-based config, ModelPort ports |
| **docs/technical/adr/ADR-001-stack.md** | Stack, Teacher refinement, Hardware, lines 1–90 | mlx-openai-server 1.8.1, Qwen3.6-27B, M4 Pro 48GB → M5 Pro 64GB target, Claude subscription |
| **docs/technical/adr/ADR-005-owner-key-broker.md** | (not fully read; referenced via overview.md § security wall) | Key broker, DEK handling, phone-attested unlock |
| **docs/technical/adr/ADR-007-knowledge-layer.md** | (referenced via overview.md § knowledge layer) | LanceDB in encrypted volume, per-scope key |
| **docs/changes/M0-c-mlx-server.md** | Config seam, endpoints, roles.toml, lines 10–113 | mlx-openai-server config, `base_url_for_role`, endpoint render placeholders |
| **docs/changes/M0-d-ports-scaffolding.md** | ModelPort definition, async port rules, lines 1–160 | ModelPort protocol, Usage, ModelResponse, async rules, embed/complete seams |
| **docs/changes/M1-b-router-brain.md** | Router + Brain, OpenAIModelPort adapter, lines 1–130 | OpenAIModelPort implementation, role resolution via base-URL seam, sensitive_reasoner routing |
| **docs/bring-up/BRING-UP-RUNBOOK.md** | Step 2e (mlx install), Step 3–8, lines 1–100+ | Model directory setup, mlx daemon startup, on-hardware gating |
| **docs/bring-up/SECRETS-INVENTORY.md** | S7, S10, model roles, lines varies | DeepSeek + Claude subscription role mapping, Keychain storage |
| **docs/research/homelab-control-plane.md** | P1–P4 phases, GPU deep-dive, ACI naming, lines 1–74 | LiteLLM proxy pattern, P3 GPU box, self-training lane integration |
| **docs/research/self-training-local-model.md** | NOW vs LATER, distillation + training, lines 1–68 | LoRA on Mini (P1), DPO/RLAIF on GPU (P3), dataset generation |

---

## Appendix A: Hardcoding Search Results

**Grep for hardcoded local-only refs (all hits found; no architectural blockers):**

```bash
grep -r "127.0.0.1\|localhost\|mlx_port" docs/changes/ docs/technical/ --include="*.md"
```

**Results:**
- M0-c Task 3 line 33: `endpoint = "http://127.0.0.1:{MLX_PORT}/v1"` — **intentional render placeholder**
- M0-c Task 3 line 43: mlx plist template — **intentional, per-slot**
- M0-c Specialist Context line 93: `mlx server binds 127.0.0.1 only` — **intentional security boundary (loopback only)**
- No hardcoding in caller code (M1-b, M3, M4, etc.); all use `base_url_for_role(role, settings)`

**Conclusion:** No architectural hardcoding. The loopback binding is a security feature, not a blocker (LiteLLM proxy binds to local network or Tailscale).

---

## Appendix B: Sensitivity Router Enforcement Sketch

**Pseudocode for the validation rule to add to M0-a `Settings`:**

```python
# In src/artemis/config.py (M0-a, post-update)

from pydantic import field_validator, ValidationInfo

class ModelRole(BaseModel):
    adapter: str  # "openai", "claude-cli"
    endpoint: str
    model_id: str
    is_sensitive: bool = False  # NEW FIELD

class Settings(BaseModel):
    roles: dict[str, ModelRole]
    
    @field_validator("roles")
    def validate_sensitive_roles_local(cls, roles: dict[str, ModelRole]) -> dict[str, ModelRole]:
        """Ensure sensitive roles (e.g., sensitive_reasoner) only resolve to local endpoints."""
        for role_name, role in roles.items():
            if role.is_sensitive or role_name == "sensitive_reasoner":
                if not role.endpoint.startswith("http://127.0.0.1:"):
                    raise ValueError(
                        f"Role {role_name!r} is marked sensitive but endpoint {role.endpoint!r} "
                        f"is not local (127.0.0.1). Sensitive roles must stay on-box."
                    )
        return roles

# In config/roles.toml:

[roles.sensitive_reasoner]
adapter = "openai"
endpoint = "http://127.0.0.1:8040/v1"
model_id = "Qwen3.6-27B"
is_sensitive = true  # NEW FLAG
```

**When a config tries to point `sensitive_reasoner` to a remote GPU box, Settings-load will raise** and prevent startup.

---

**End of constraints analysis.**
