# Local-LLM Expansion Plan — Synthesis (2026-06-13)

_Fable synthesis over 5 info-pull agents (4× Sonnet web research + 1× Haiku corpus read).
Source files in this directory: `models-memory.md` · `apple-path.md` · `x86-gpu-path.md` ·
`serving-software.md` · `artemis-integration-constraints.md`. Every number below is cited there._

**Requirement (owner, 2026-06-13):** future-proof Artemis to run local DeepSeek for coding and
Kimi-class big-context locally — slower than cloud is fine, but it must run. Topology: the M5
Mac Mini stays the orchestrator; heavy inference moves to (an)other box(es) on the tailnet.
Plan all three speed tiers; compare Apple and x86 honestly.

---

## 1. The headline finding: DeepSeek V4-Flash reframes the requirement

The stated requirement was "DeepSeek for coding + Kimi for big context" — two models, two roles.
The model research found **one model now spans both roles at a fraction of the hardware**:

| | DeepSeek V4-Flash | Full DeepSeek V3.2 | Kimi K2.6 |
|---|---|---|---|
| Size | 284B MoE (13B active) | 685B MoE (37B active) | 1T MoE (32B active) |
| Context | **1M tokens** (~9.6 GB KV/seq — hybrid CSA+HCA attention, ~8.7× KV reduction) | 128K (MLA, ~8.7 GB at 128K) | 256K (MLA) |
| Coding | 80.6% SWE-bench (V4-Pro-class) | strong | K2.7-Code strong (1 day old, provisional) |
| Q4 memory | **~80 GB → 128 GB tight / 192 GB safe** | ~405 GB → 512 GB | ~585 GB → multi-box (Q2: ~340 GB → 512 GB) |

**Implication:** if V4-Flash quality satisfies both roles, the hardware floor drops from
512 GB+ (Kimi-class) to **128–192 GB** — roughly a $10k+ → ~$2–5k difference. Full Kimi
remains plannable as a higher rung. This is **Decision A** for the owner.

**Owner direction (2026-06-13):** stay **model-flexible** — plan for ways to achieve the two
roles, not for named models. Hardware is sized for a *capability class* (memory tier ×
bandwidth); models bind late via aliases (§7). The menu:

### 1b. Model menu per role — pros / cons

**Coding role:**
| Candidate | Memory | Pros | Cons |
|---|---|---|---|
| **DeepSeek V4-Flash** (284B/13B act) | 128 tight / 192 safe | Best quality-per-GB (80.6% SWE-bench); 1M ctx covers both roles; MIT | Community quant numbers Medium-confidence; 13B active → some long-task drift risk |
| Full DeepSeek V3.2+ (685B/37B) | 512 | Max open coding quality; 37B active = strongest agentic coherence | 512 GB floor; slowest; superseded for value by V4-Flash |
| **DeepSeek R2** (32B dense) | 64 (≈20 GB Q4) | Fits the Mini itself; dense = consistent multi-step loops; MIT; cheapest tier | Not frontier on large refactors; 256K ctx claim unofficial |
| Qwen3-Coder-Next (80B/3.9B act) | 64 (≈46 GB Q4) | 70.6% SWE-bench in 46 GB | 3.9B active → documented coherence drift on extended autonomous tasks |
| Qwen3-Coder-480B | 256 (Q2) / 512 (Q4) | Strong | Worse quality-per-GB than V4-Flash; Q2 quality loss |

**Big-context role:**
| Candidate | Memory | Pros | Cons |
|---|---|---|---|
| **V4-Flash 1M ctx** | 128–192 | Same box as coding; KV near-free at 1M | One model = correlated failure modes across both roles |
| **Kimi K2.6 / K2.7-Code** (1T/32B act) | 512 (Q2 ~340 GB) / multi-box (Q4 ~585 GB) | Distinct model flavour (de-correlated second opinion); strong agentic; 256K ctx | Brutal floor; Q2 = real quality loss; weak prefill on Mac at long ctx; K2.7 specs 1-day-old |
| **Decompose via Artemis's own RAG** (M3 brain + any small model) | 0 extra | Already specced (M3 hybrid retrieval + agentic multi-hop); runs day-1 on the Mini | Not true global attention — cross-document reasoning over the *whole* corpus at once is weaker; it's a workflow, not a model |

Read on the menu: the three real "ways to achieve it" are **(i)** one V4-Flash-class box at
192–256 GB doing both roles, **(ii)** a 512 GB-class box that also de-correlates with a
Kimi-class second model, **(iii)** lean on the M3 RAG brain for big-context and buy only a
small coding box. They are rungs, not enemies — (iii) is free now, (i) is the value point,
(ii) is the end-state.

Other model facts that matter:
- **KV cache is near-free on all DeepSeek/Kimi-family models (MLA)** — context length is NOT a
  hardware-sizing driver. Avoid dense GQA models for the long-context role.
- **DeepSeek R2 (32B dense, Apr 2026, MIT)** is the "just works" coding model for 64 GB boxes
  (~20 GB Q4); Qwen3-Coder-Next (80B/3.9B-active, 70.6% SWE-bench, ~46 GB Q4) also fits 64 GB.
- Confidence: V4-Flash memory numbers are Medium (3 consistent community sources, no
  authoritative test); Kimi K2.7-Code specs provisional.

## 2. Hardware ladder — three rungs × two platforms

Context that shapes everything: the **DRAM shortage**. Apple quietly discontinued the M3 Ultra
512GB BTO (Mar 2026; used units ~$9.5k); M5 Ultra Studio expected **Oct 2026** (up to 512 GB,
~1,100 GB/s, est. $5.5–6.5k+, availability uncertain). The same shortage is raising prices
generally — buying decisions should not assume today's prices hold.

### Rung 0 — what the M5 Mini (64 GB) alone gives (no new hardware)
- Coding: DeepSeek R2 32B Q4/Q8 or Qwen3-Coder-Next 80B Q4 (tight alongside Artemis's resident
  brain models — R2 is the safe choice). ~25–45 tok/s on small MoE.
- Big context: nothing serious. The Mini is an orchestrator, not an inference node (its memory
  AND its bandwidth make it the bottleneck in any cluster role).
- Verdict: a real fallback coding tier, not the plan.

### Rung 1 — overnight-batch (~$1.5–5k)
| Option | Runs | Speed | Livability |
|---|---|---|---|
| **AMD Strix Halo 128 GB mini-PC** ($1.5–2.1k) | V4-Flash Q4 (tight) | est. ~10–20 tok/s (109B MoE measured at 19.3) | near-silent, <100 W, low admin |
| **Used EPYC 512 GB + RTX 3090** (~$2–2.5k) | Full DeepSeek 671B Q4; Kimi Q2 borderline | 3.5–4.25 tok/s decode, weak prefill | 40–48 dB tower, 260–350 W, medium admin |
| Apple M3 Ultra 96 GB ($3,999) | V4-Flash Q4 does NOT safely fit (80 GB weights + OS + KV in 96 GB) | — | — (poor value at this rung) |

### Rung 2 — working-session (~$6–14k) ← the sweet spot
| Option | Runs | Speed | Livability |
|---|---|---|---|
| **M5 Ultra Studio 256–512 GB** (Oct 2026, ~$5.5–6.5k+, availability risk) | 512 GB: full DeepSeek Q4 **and** Kimi Q2; 256 GB: V4-Flash comfortable + DeepSeek Q2 | est. ~25 tok/s on 671B (M3U measured 20–21 @ 819 GB/s; M5U +34% BW); Kimi Q2 8–15 | 9 W idle / 150–200 W load, silent, macOS, lowest admin |
| **Intel Xeon (AMX) + 1 TB DDR5 + 1 GPU, ktransformers** ($8–14k) | Full DeepSeek Q4 AND Kimi Q4 (1 TB fits 585 GB) | 12–14 tok/s decode, **200–286 tok/s prefill** (best big-context prefill of any option) | tower 40 dB+, ~300–500 W load, highest admin; **must be Intel AMX — AMD EPYC loses the ktransformers speedup (5–8 tok/s)** |
| **Dual DGX Spark** ($9.4k, 256 GB) | V4-Flash only — full DeepSeek/Kimi do NOT fit | bandwidth-poor (273 GB/s) for dense; OK for small-active MoE | near-silent, ~100–170 W, low admin |

### Rung 3 — near-interactive on the biggest models ($20k+)
- **2–4× Mac Studio exo cluster** (TB5 RDMA, macOS 26.2+): measured DeepSeek 671B ~25 tok/s,
  Kimi 1T ~34 tok/s on 4 nodes. Works but **explicitly early-stage/fragile** (RDMA via recovery
  mode, M3+ only, 4-node max tested). Not a foundation to depend on yet — re-evaluate in 2027.
- Multi-GPU consumer rigs: **dead end** for these model sizes (no NVLink pooling; 671B Q4 needs
  ~376 GB VRAM). The first native-VRAM fit is 8× RTX PRO 6000 (~$75k+, 4.8 kW, 70 dB) — no.

### Recommendation (synthesis) — owner direction 2026-06-13: keep ALL paths open

The only certainty is **the M5 Mac Mini (orchestrator + Rung-0 fallback coding)**. The inference
box is future hardware; rather than commit to one box now, the plan keeps the ladder open and
**trigger-gates** the choice. All three Rung-1/2 options remain live; pick when a trigger fires.

| Path | Box | Unlocks | Home-livability | When it wins |
|---|---|---|---|---|
| **P-Apple** | M5 Ultra Studio, max memory (~Oct 2026, ~$5.5–6.5k+) | 512 GB → full DeepSeek Q4 **+** Kimi Q2 (path ii); 256 GB → V4-Flash-class (path i) | ★★★ silent, 9 W idle, macOS, lowest admin, MLX-native with the Mini | You want one quiet appliance, all-Apple, and can wait for Oct 2026 + accept availability/price risk |
| **P-Xeon** | Xeon-AMX + 1 TB DDR5 + 1 GPU, ktransformers (~$8–14k) | Full DeepSeek Q4 **and** Kimi Q4 (1 TB fits ~585 GB); best big-ctx prefill (200–286 tok/s); also the training/distill box | ★ tower 40 dB+, 300–500 W, Linux admin | Kimi-at-quality and fast huge-document prefill matter most; you'll run a server |
| **P-Strix** | Strix Halo 128 GB mini-PC (~$1.5–2.1k, available now) | V4-Flash Q4 (tight); overnight coding now | ★★★ near-silent, <100 W, low admin | Cheap bridge: start local coding immediately, demote to ACI edge node later |
| **P-RAG** | none (Mini only) | Big-context via M3 RAG brain + small model (already specced) | ★★★ free | Day-1 baseline for big-context until any box lands |

**Default narrative if forced to one:** start at **P-RAG** (free, day-1) → add **P-Apple** at the
largest memory tier when M5 Ultra ships and pricing is sane → fall back to **P-Xeon** if the
512 GB tier never materializes or you need Kimi-Q4/training. **P-Strix** is an optional cheap
bridge that never becomes waste (demotes to edge). These are not exclusive — see triggers in §5.

## 3. Software plan (invariant across hardware choices)

The corpus read confirmed: **Artemis's architecture already supports this expansion with
config-only changes at the model seam.** `ModelPort` is a Protocol over an OpenAI-compatible
HTTP client; every endpoint resolves from `roles.toml` via `base_url_for_role()`; ADR-015
already made the port surface async (network-ready). The ACI homelab doc (P3) already frames a
LiteLLM proxy on the Mini routing by model id.

Layers (bottom → top):
1. **Inference box serving:** Linux → **SGLang** (official DeepSeek-V4 support, RadixAttention,
   ktransformers integration; add systemd `Restart=always` — crash-hardening still maturing) or
   **vLLM** (best batch/queue story). Mac → **vllm-mlx** (native Anthropic `/v1/messages` API,
   continuous batching; community-maintained — pin versions) or plain `mlx_lm.server`.
2. **Gateway on the Mini:** **LiteLLM proxy** (the 2026 standard, no serious competitor) —
   model-alias routing to Tailscale MagicDNS addresses, retry/fallback chains (remote box →
   Mini-local small model → cloud). Tailscale ACLs + per-caller API keys at the LiteLLM layer;
   WireGuard overhead negligible on LAN.
3. **Claude Code coding backend:** `claude-code-router` (34.9k stars; task-type routing,
   tool-use error-tolerance transformers) or LiteLLM's Anthropic passthrough in front of the
   local DeepSeek endpoint. NB: APEX detects coding mode by "deepseek" appearing in
   `ANTHROPIC_BASE_URL` — keep the local route's URL/alias containing "deepseek" (or amend the
   detection rule) so the planning/coding split keeps working when coding goes local.
4. **Background/batch jobs:** vLLM offline `LLMEngine` mode (checkpointing, priority preemption)
   for overnight builds/reads; a ~50-line asyncio queue suffices in front of llama.cpp-class
   servers. Wake-on-LAN for on-demand power (Ethernet required; cold start ≈ 2–3 min incl.
   model load — fine for batch, use keep-alive windows for interactive).
5. **Artemis corpus changes (POST-handoff, additive — do NOT touch the frozen ~61-spec corpus):**
   - `roles.toml`: remote endpoints per role (config-only).
   - Settings validator: pin `sensitive_reasoner` (and sensitive-embedding roles) to
     `127.0.0.1` unless Decision C extends the trust boundary.
   - M0-c model-pull task becomes conditional on role locality.
   - Tailscale ACLs (ops, no code).
   - Future small specs: "EXP-a remote-inference routing" + "EXP-b inference-box bring-up
     runbook" — draft when hardware is chosen.

**Quality caveat (honest):** community verdict on local models inside Claude Code-style agentic
loops is "workable, not optimal" below the V4-Flash class; small MoE models drift on long
autonomous tasks. The local coding tier should be treated as *capacity*, with cloud DeepSeek as
the quality fallback until V4-Flash-class local proves itself on your specs.

## 4. Security / trust boundary (Decision C input)

The M2 wall currently requires `sensitive_reasoner` and sensitive embeddings to stay Mini-local.
A remote inference box is owner-controlled hardware on the tailnet — but it is a NEW trust
surface (disk, swap, logs). Options:
- **C-1 Keep the wall as-is:** remote box gets only non-sensitive work (coding on specs, public
  docs). Big-context jobs over PERSONAL documents stay Mini-sized. Zero new risk; limits the
  Kimi use case materially.
- **C-2 Extend Tier boundary to the box:** FileVault/LUKS, no-persistence serving config (no
  prompt logging, no disk KV offload), Tailscale-only ingress, documented in an ADR + the
  bring-up runbook. Unlocks big-context over personal data; adds an auditable surface.

**✅ RESOLVED 2026-06-13 — owner chose C-2 (extend boundary to the box).** The remote inference
box MAY process sensitive data, so big-context jobs run over the owner's own documents. Binding
requirements to spec when a box is chosen (EXP-b + a mini security review):
1. **Full-disk encryption** on the box (FileVault on macOS / LUKS on Linux).
2. **No-persistence serving config** — disable prompt/response logging; no disk KV-cache offload;
   ephemeral scratch only. The model server must not write request content to disk.
3. **Tailscale-only ingress** — no LAN/public listener; ACL restricts to the Mini's tailnet
   identity; per-caller API key at the LiteLLM layer.
4. **ADR** capturing the Tier-boundary extension (amends/extends the M2 wall rationale) +
   **bring-up runbook** section + **its own mini security review** before first sensitive job.
5. The Settings validator that pins `sensitive_reasoner`/sensitive-embeddings to `127.0.0.1`
   (§3.5) is **relaxed to allow the box's tailnet address** ONLY once C-2's controls are verified —
   until then it stays Mini-local (fail-safe default).

## 5. Decision queue
- **A. ✅ RESOLVED 2026-06-13 — model-flexible.** Owner: don't lock to named models; plan the
  ways-to-achieve menu (§1b) + a standing model-update process (§7). Hardware sizes for a
  capability class; the 192-vs-512 GB floor question folds into Decision B (each buy option
  states which model classes it unlocks).
- **B. ✅ RESOLVED 2026-06-13 — keep all paths open, trigger-gated.** Only certainty: buy the
  M5 Mac Mini (orchestrator). The inference box stays a live menu (P-Apple / P-Xeon / P-Strix /
  P-RAG, §2). Pick when a trigger fires — do NOT pre-commit now. Triggers:
  - **T1 — M5 Ultra ships (≈Oct 2026):** check 512 GB BTO real price/availability. Buyable at
    sane price → P-Apple 512 (end-state, both roles). Only 256 GB → P-Apple 256 (V4-Flash class).
  - **T2 — Kimi-Q4 / fast huge-doc prefill / a local training box becomes a felt need** before
    or instead of T1 → P-Xeon.
  - **T3 — you want local coding running before any big box** → P-Strix bridge now (cheap, demotes
    to edge later); revisit T1/T2 afterward.
  - **T0 — until any trigger fires:** P-RAG (Mini-only big-context) + Rung-0 Mini coding. Zero spend.
  Interacts with the open "buy M4 Pro Mini now vs wait M5" question — same DRAM-shortage clock.
- **C. ✅ RESOLVED 2026-06-13 — C-2 (extend boundary to the box).** Box may process sensitive
  data under the 5 binding controls in §4 (FDE · no-persistence serving · Tailscale-only ingress ·
  ADR + runbook + mini security review · fail-safe validator stays Mini-local until controls
  verified). To be specced in EXP-b when a hardware trigger fires.

**All three decisions (A/B/C) resolved 2026-06-13 — the plan is complete. No remaining open
gates; next action is owner-triggered (T1/T2/T3) hardware purchase, then draft EXP-a/EXP-b.**

## 8. APEX coding-system fit (added 2026-06-13)

The plan relocates the **coding backend** from DeepSeek-cloud to a local box. APEX is the system
that *consumes* that backend, so it must be checked. Verdict: **fits well — the dual-backend
design anticipated exactly this — but four real adjustments + one hard requirement.**

### Two distinct model paths through the box (do not conflate)
- **Dev-time (APEX):** Claude Code → **Anthropic Messages protocol** (`ANTHROPIC_BASE_URL`) →
  box serves DeepSeek as the *coding agent*. This is how APEX builds Artemis.
- **Run-time (Artemis):** the built app → **OpenAI protocol** (`ModelPort`/`roles.toml`) → box
  serves DeepSeek/Kimi as the app's *reasoner / big-context*. This is §3's original path.
Same box, possibly same weights — **two protocols, two consumers.** LiteLLM fronts both.

### Hard requirement (R)
- **R — Anthropic-protocol serving for the coding endpoint.** Claude Code speaks only the
  Anthropic Messages API. The box must expose `/v1/messages` for the coding role — via
  `claude-code-router`, LiteLLM's Anthropic passthrough, or (Mac) vllm-mlx's native Anthropic
  endpoint. The OpenAI-only serving in §3 is **insufficient for APEX**; this endpoint is
  mandatory, and its route URL/alias **must contain "deepseek"** so the detection hook
  (`backend-session-start.ps1`) and the planning-mode write-gate (`backend-pretool-write.ps1`)
  keep firing correctly.

### Adjustments
1. **A1 — Claude Code runs on the Mini, not the box.** The Mini (orchestrator) runs Claude Code +
   the repo + `~/.claude` skills + git + context7 (needs internet); it dispatches *inference* to
   the box over Tailscale. The box stays pure inference — no repo, no secrets, no filesystem
   access to source. This makes the "Mini = orchestrator" framing exact AND reinforces C-2: the
   box sees prompts/code over the API, never the disk.
2. **A2 — Wave-parallel fan-out vs single-box throughput (the main mismatch).** apex-code spawns
   N parallel `code-worker` agents per wave + up to 2× `apex-wave-reviewer` per high-risk domain +
   post-build `apex-reviewer`/docs agents — *all on the coding backend*. Cloud absorbs this for
   free; a single local box does not. Resolution: **serve coding on vLLM/SGLang (continuous
   batching)** so concurrent agents batch (throughput holds; per-request latency drops) — NOT
   mlx_lm.server/llama.cpp (weak batching → agents serialize + contend for KV cache). Add a
   **max-concurrent-workers cap** matched to the box's batch+VRAM budget; on weak-batching servers,
   AFK/overnight mode absorbs the serialization. (Candidate new field: a per-backend worker-cap
   read at wave dispatch.)
3. **A3 — AFK vs Edit mode → speed tiers.** apex-code's **AFK Build Mode** (silent, overnight,
   complete) maps perfectly onto a slow local box (12–25 tok/s). **Edit Mode** (interactive small
   fixes) is painful at local speeds → route Edit Mode to the *fastest* local model (DeepSeek R2
   32B dense, or a Mini-local small coder) or keep Edit Mode on cloud; reserve the big local
   DeepSeek for AFK builds.
4. **A4 — Failure-mode + quota semantics.** The pause/checkpoint-on-rate-limit logic is
   backend-agnostic and still works, but local *triggers* differ: OOM (context+KV exceeds loaded
   model), thermal throttle, server crash (SGLang fault-tolerance still maturing). Run the coding
   server under a supervisor (`systemd Restart=always` / launchd KeepAlive); add "local-server
   unavailable / OOM" as a pause trigger alongside rate-limit. A crash mid-build → Claude Code sees
   an API error → pause-checkpoint → resume after auto-restart (the In-Flight row is the checkpoint).

### Fits as-is, no change
- **Cross-model review** (`cross_model_review: true`) already names "the Mac co-locating Claude +
  DeepSeek" and needs Claude reachable *during* a DeepSeek build. In A1's topology the Mini reaches
  Claude (cloud) over internet → DeepSeek-build (local box) + Claude-review (cloud) works. Sending
  Artemis *source code* to Claude is fine — source isn't the C-2-protected personal data.
  **Future option:** a *second local model of a different family* (e.g. Qwen-Coder) on the box could
  satisfy evaluator-independence fully locally, removing the cloud dependence for review.
- **Planning mode** stays Claude-cloud — unchanged. The dual-backend split persists; only the
  coding half relocates.
- **Autonomy levels, hard blocks, governance, the spec corpus** — all backend-agnostic. The frozen
  ~61-spec corpus is unaffected: APEX consumes specs identically regardless of where DeepSeek runs.
- **PreToolUse write-gate** — keyed on "deepseek" in the URL (see R); works unchanged once the
  local route is named correctly.

### Where this lands in the spec work
- **EXP-a (remote-inference routing)** gains the requirement R + adjustments A1/A2 (Anthropic
  endpoint, Mini-runs-Claude-Code, worker-cap).
- A possible tiny **APEX-side change** (separate from the Artemis corpus): a per-backend
  `max_parallel_workers` knob in apex-code's wave-dispatch, and an extra pause-trigger. These touch
  `~/.claude/skills/apex-code/` (APEX is self-hosting) — NOT Artemis. Defer until a box exists.
- The model-update process (§7) gains an **APEX-shaped eval gate** — see §7.3 below.

## 8b. Planning mode + research models (added 2026-06-13)

§8 covered the *coding* half. This covers the *planning* half — the quality-critical side.

### Mechanism finding: APEX mode is set by the backend URL string, not the model
`backend-session-start.ps1`: `$isDeepSeek = $url -like '*deepseek*'` → match = CODING, else =
PLANNING. So:
- A route named "deepseek" can **only** be a coding backend (planning would misroute).
- A local **non-"deepseek"** model is accepted by APEX as a planning backend.
- The **same weights** can serve both modes under two LiteLLM aliases — e.g.
  `artemis-coder-deepseek` (→ coding) and `artemis-planner` (→ planning) — no model swap. (Caveat:
  one loaded model serving two roles still contends for the box's batch/KV budget; see A2.)

### Should planning go local at all? — the case for keeping it cloud-frontier
Planning is **the opposite workload to coding** on every axis that matters here:
| Axis | Coding (local case is strong) | Planning (local case is weak) |
|---|---|---|
| Volume | high (every spec, overnight builds) | low (a handful of specs/decisions per session) |
| Quality sensitivity | medium (spec carries the load) | **highest** — spec quality *is* the failure variable for the whole pipeline (DeepSeek-V4 research) |
| Data sensitivity | source code (not personal) | **design docs / specs / ADRs — also not personal data** |
| Cost shape | per-token cloud → local saves real money | Claude **subscription = flat**; local saves little |
| APEX wiring | wired to "deepseek" | wired to "the strong model" |

**Conclusion:** planning does **not** need to go local for privacy (it never touches the
C-2-protected personal data — that's runtime app data, not development design docs) and gains
little on cost (subscription is flat). It would *lose* the most on quality, which is the one thing
APEX cannot afford to degrade. **Recommendation: planning stays cloud-frontier by default.**

### Local planning as an optional *resilience/independence* tier (not the default)
Reasons you might still want a local planning capability — as a fallback, not a replacement:
- **Offline / internet-down** operation (the appliance keeps planning).
- **Evaluator independence** (governance): the council + cross-model review want *de-correlated
  model families*. A strong local model of a **different family** (Kimi or Qwen alongside cloud
  Claude) is a genuine second opinion, not an echo. This is the same lever as §8's "second local
  family for review."
- **Future capability self-training:** the CAP/M7 lane already aims to distill Claude-grade
  reasoning into a local student. A distilled-from-Claude *planner* is the long-horizon version of
  "local planning" — earned, not bolted on.
Strongest local candidates for planning-grade reasoning (from §1): DeepSeek V3.2/V4 or Kimi K2.x
(both strong reasoners) served under a **non-"deepseek" alias**. Honest gap: frontier Claude still
edges them on subtle multi-step architectural judgment — so local planning is a *resilience* tier,
promoted only if an eval (below) shows parity on real specs.

### Research models (the apex-research / apex-deep-dive fan-out) locally
The research workflow has three role tiers; they localise **differently**:
| Role | What it does | Local fit |
|---|---|---|
| **Planner** (decompose the research) | one call, light reasoning | cloud-frontier or a strong local; cheap either way |
| **Pullers** (web fetch + faithful extract/summarise) | many, parallel, **mechanical** | **best local target** — web access is the *orchestrator's* WebSearch/WebFetch tool, NOT the model; the model only summarises returned text. A small fast local model (even Mini-local) does this fine and **saves the most cloud tokens** (this is the high-volume tier). |
| **Synthesizer** (combine into a decision) | one call, **heavy reasoning**, high-leverage | keep cloud-frontier (or the big local reasoner) — its output feeds decisions; don't cheap out |
**Mapping to hardware:** pullers are many + cheap + parallelisable → small model, possibly even on
the Mini, run concurrently; synthesizer is single + heavy → cloud or the big box. This mirrors the
model the owner already used this session (cheap pull tier + strong synth). Going local on the
**puller tier only** captures most of the token saving at near-zero quality risk; the synth/planner
tiers are where quality lives, so they stay frontier unless evaluated.

### Hardware/topology implication
One box holds one big model at a time (load = minutes, hundreds of GB). If planning(local) and
coding(local) want *different* models → model-swap latency or a second box. Two clean ways out:
(i) **same model both modes** via dual aliases (works if V4-Flash-class is strong enough for both —
plausible); (ii) **planning stays cloud** (recommended) so the box only ever loads the coding model
and the pullers run on a tiny separate/Mini-local model. Option (ii) is simplest and protects
quality; option (i) is the all-local end-state if/when a local reasoner proves out.

### Decisions surfaced
- **D-plan-1 — ✅ RESOLVED 2026-06-13 — "1 then 3": cloud-frontier now → fully-local distilled
  planner as the end-state.** Planning + research-synthesis stay on **cloud Claude** for the
  near/mid term (the committed posture); the **local-fallback middle option (b) is skipped** — no
  stopgap local planner. The **long-horizon goal is a fully-local planner distilled from Claude via
  the CAP/M7 capability lane** (the M7 teacher + `distill-datagen-pipeline` already aim Claude-grade
  reasoning into a local student — this names *planning/spec-authoring* as a distillation target,
  not just coding). Promotion to the local planner only after the §7.3 eval (extended with real
  spec-authoring tasks) shows parity with the frontier baseline. Until then: box loads only the
  coding model; planning is cloud.
- **D-plan-2 — ✅ RESOLVED 2026-06-13 — move pullers local.** The research **puller tier**
  (web-fetch + faithful extract) runs on a cheap fast local model (Mini-resident or the box's small
  model); the **planner + synthesizer tiers stay cloud-frontier**. Web access stays the
  orchestrator's WebSearch/WebFetch tool — only the extract/summarise step is local. Captures most
  of the research-token saving at near-zero quality risk. EXP-a wires a `research-puller` alias to
  the local small model; the synth alias stays cloud.
Both fold into EXP-a when a box exists; neither blocks anything now. The promotion gate for *any*
local planning/synth model = the §7.3 eval, extended with **real spec-authoring tasks** judged
against a frontier baseline (no vibes-promotion of the quality-critical role).

> **Capability-lane note (end-state):** D-plan-1(3) makes spec-authoring a first-class distillation
> target for the CAP lane — the `distill-datagen-pipeline` 6-category generation set should reserve
> a **planning/spec-authoring category** (teacher = Claude producing real Artemis specs/ADRs) so the
> eventual local student can be evaluated as a planner, not only a coder. → also logged to BACKLOG.

## 7. Model-update strategy (standing process — the real future-proofing)

Principle: **hardware is bought for a capability class; models bind late and swap cheap.**
A model swap must never touch Artemis code.

1. **Alias indirection.** LiteLLM defines role aliases (`artemis-coder`, `artemis-bigctx`,
   `artemis-coder-fallback`); `roles.toml` points at aliases, never at model ids. A swap =
   download weights → flip the alias mapping → done. (The alias for the coding backend keeps
   "deepseek" in its route name while APEX's mode detection depends on it.)
2. **Refresh cadence.** Quarterly model-refresh check (the apex-refresh pattern applied to
   model weights; later automatable as an M6 heartbeat + M7 curiosity job): scan major open
   releases (DeepSeek, Qwen, Moonshot/Kimi, Mistral, Meta, new entrants), recompute the §1 fit
   table against the *owned* memory tier, shortlist candidates that fit.
3. **Promotion gate (eval-before-swap).** A candidate must beat the incumbent on a small owned
   eval set before its alias flips: ~10–20 spec-style coding tasks (drawn from real Artemis
   specs) + a handful of long-document QA jobs. Aligns with the existing eval backlog items
   (withpi scorer, RAGAS dimensions). No vibes-promotion. **APEX-shaped gate (for the coding
   role):** the candidate must also pass a real APEX build end-to-end — i.e. honour the
   `code-worker` status contract (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT), route a
   fork correctly, and survive an agentic tool-use loop without coherence drift. A model that
   benchmarks well but breaks the worker contract is not promotable as the coding backend.
4. **Rollback.** Keep the incumbent's weights until the candidate survives ~2 weeks of real
   use; flip the alias back to roll back. (Storage-management backlog item covers eviction.)
5. **Quant-maturity rule.** Community GGUF/MLX quants lag releases by days–weeks and early
   quants are often broken — pin exact quant files/versions; never auto-pull "latest".
6. **Hardware trigger.** If two consecutive refresh cycles surface clearly-better models that
   do NOT fit the owned tier, that — not calendar age — is the signal to revisit hardware.

## 6. Other future-proofing surfaced (→ BACKLOG.md)
- Wired networking headroom: Mini↔box Ethernet (WoL requires it) and TB5 if clustering ever.
- UPS + power monitoring for 24/7 inference box.
- Inference-box bring-up runbook + secrets/disk-encryption posture (pairs with Decision C).
- Capability-lane convergence: an x86/GPU box doubles as the DPO/RLAIF training home
  (homelab-control-plane.md already frames this).
- Model-weight storage management (hundreds of GB per model; versioning + eviction).
- Wake-on-demand power orchestration (Mini wakes the box per queued job).
- Re-check exo/TB5 RDMA clustering maturity in 2027 (would change the Rung-3 calculus).
