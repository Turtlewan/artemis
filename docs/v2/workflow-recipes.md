# Design note: per-workflow recipes — orchestrate-vs-delegate (WIP discussion)

_Status: OPEN design discussion (started 2026-07-01, during R2 build). Not yet decided. This note
captures the framing; it will evolve as the discussion does. No spec until decided._

## Review synthesis + corrections (4-agent review, 2026-07-01) — READ FIRST
Verdict: **core sound, no hard BLOCK, no unacknowledged security hole.** The encapsulated-caged-recipe +
deterministic-composition + taint→gate(Biba) spine is internally consistent. But the note **over-hardened**
during the discussion — treat the inline "RESOLVED" stamps below as **PROPOSED (pending spike/ADR)**, not
settled. Corrections that supersede the body:

- **Naming (fix the collision):** execution modes are **`deterministic`** (host-orchestrated code — R2),
  **`hybrid`** (recipe steers, guarded engine executes), **`caged-agent`** (autonomous claude-code in the
  cage). ⚠️ These are NOT ADR-035's "Pattern A/B" — *both* of those are `deterministic`; the caged-agent is a
  **third** pattern. Drop the "A/②/③" and "A/B" labels (② was never defined; "B" collides with ADR-035).
- **"Preserves Option B" is only half true:** the broker preserves the *credential* half (no token in cage),
  but ADR-035 Option B also requires *reasoning/orchestration host-side* — caged-agent **reverses that half**
  consciously. Needs the extending ADR to ratify (with ADR-009's no-tools-on-poison-reader reversal).
- **Broker back-ending the *subscription* OAuth is UNPROVEN** — the load-bearing spike; caged-agent is not
  buildable until it passes (mirrors the [[codex-openai-proxy-pattern]]).

### Hard requirements the caged-agent spec MUST carry (from review)
1. **Cage-local / host-brokered fetch ONLY — native `WebFetch`/`WebSearch` FORBIDDEN.** claude-code's native
   web tools run **server-side on Anthropic infra, not in the cage**, so the egress allowlist can't constrain
   them AND a search-provider key would sit in the cage (breaks "zero secrets"). All web I/O must go through
   R2's host-side egress pipe. `--allowedTools` must not be able to re-expose native web tools.
2. **Allowlisted tools must be strictly side-effect-free** (read-only web + scratch). The ADR-009 reversal is
   only safe because no granted tool can act; a state-changing GET/webhook would reopen the hole.
3. **Host-side citation check post-run:** `sources = agent-cited ∩ actually-fetched` (outside the agent) —
   ③ self-cites, so grounding must be validated by the host (R2 had this structurally).
4. **Taint→trusted-write refused structurally at RUNTIME,** not only by promote-time pipeline approval; the
   host forces staging for *derived* tainted output too, and honours at-rest trust labels in the composition
   runtime (label-propagation must be enforced, not assumed).
5. **Two spend channels, two caps:** model tokens capped by the **broker** (per-run id; + subprocess-kill &
   wall-clock belt-and-suspenders); search-provider calls capped by `--max-turns`/wall-clock (NOT the broker).
6. **Egress note:** "search-vouched" allowlist is injection-widenable within a run (a poisoned page steers the
   next search) — bounded (443, read-only, no secrets to exfil) but prefer a static per-recipe allowlist where
   the domain set is known.

### ▶ OWNER DECISION (open, gates the caged-agent spec — not R2)
**③/caged-agent trades R2's *structural* quarantine for *containment + a human gate*.** The cage stops
exfiltration and side-effects, but does NOT stop an injection from **steering the report's content** — a
poisoned-but-plausible result can pass human review. Is that acceptable? Leaning: **yes for review-gated /
display-only outputs** (you read them), **no for anything that feeds trusted state or acts without you
reading it line-by-line** (those stay `deterministic`/`hybrid`, which keep the structural quarantine).

### Scope: near-term buildable core vs deferred
- **Core (buildable after the spike + ADR):** caged-agent runtime + broker + budget-kill + **one** research recipe.
- **Deferred until a *second* recipe justifies it:** the recipe **registry**, **composition/pipelines**, and
  **at-rest taint labels in Cognee memory** (cross-slice — don't build ahead of need).

### Spikes before any spec
1. **Broker ↔ subscription OAuth** (load-bearing): a local reverse-proxy injects the OAuth bearer + Claude-Code
   identity headers; a `--bare` `claude -p` via `ANTHROPIC_BASE_URL` completes AND is billed to the
   subscription (not API credits).
2. **Native web tools forbiddable** + cage-local fetch tool works under `--allowedTools`.

_(The sections below are the raw discussion capture; where they say "RESOLVED", read "proposed" per the above.)_

## The seed

The clean-context provider (R2a, ADR-037) gives every Claude-subscription call a **private sanitized
`CLAUDE_CONFIG_DIR`** — currently holding only the login token, so reads arrive free of the global
`~/.claude/CLAUDE.md` + APEX hooks. Owner's insight: that same per-call dir is the natural place to drop
a **task/workflow-specific `CLAUDE.md` (a "recipe")** — clean context **+** tailored instructions, without
the global rulebook. And those recipes can be *derived from the matching APEX skill* (e.g. a research
recipe ≈ what `apex-research` encodes).

## REFRAME (owner, 2026-07-01): a recipe IS how a capability executes

Recipes are **not a new kind of capability** — a recipe is **the way a capability executes its task**
(the *how*; the capability is the *what*). So the A/②/③ spectrum below is not three competing global
architectures — each is an **execution mode a recipe declares.** A capability's recipe picks its mode:
safety-critical → A (deterministic code); open-ended → ③ (caged agent + broker). R2's web tool = a
capability whose recipe is *code-baked* (A-mode). The capability library already IS where recipes live
(no separate library). Incremental build = stand up the **③-mode execution runtime** (caged claude-code +
credential broker + budget-kill + incident log) as a reusable execution method; **research** is the first
capability whose recipe runs on it.

DECIDED (owner, 2026-07-01): **reusable/shared** — recipes are a **composable cookbook**. A recipe is
defined once, grant-approved once (tools/egress/budget), and any capability can invoke/compose it (e.g. a
"market report" capability = research recipe → summarize recipe → store). Implies: a **recipe registry**
(named, versioned, independently-approved units), a **composition layer** (capabilities invoke + chain
recipes), and two hard OPENs below.

### Grant model / least-privilege — RESOLVED (encapsulation, no inheritance)
A caller **never inherits** a recipe's grants. A recipe executes in **its own grant-scoped cage** with its
own tools/egress/budget; composition passes only the recipe's **output** to the next step. So invoking
`research` does NOT give the caller web egress — `research` does the web work in its cage and hands back a
result. Powers stay encapsulated; only data crosses (same principle as the credential broker + quarantine).
Two-part model:
- **Execution grants** (tools/egress/budget) belong to the recipe, run in its cage, never propagate.
- **Invocation rights** (which recipes a capability may call) are declared + **approved at the capability's
  promote-time** — composition is explicit and gated, not open. ("market-report may invoke {research, summarize}".)

### Cross-recipe quarantine — RESOLVED (taint propagation)
Any recipe that reads untrusted external content (③-mode / web-reading) produces **tainted** output.
- A downstream recipe consuming tainted input applies the **same dual-LLM discipline** (spotlight, no-tools,
  treat-as-data) — summarize spotlights research's output exactly as R2's synth spotlights extracts.
- **Taint propagates**: output derived from tainted input is itself tainted; it clears only at a **trusted
  gate** (human review / structural validation).
- **Hard rule:** a tainted result must NEVER reach a tool / side-effect without a trusted gate — so
  research→summarize→*show the owner* is fine; research→summarize→*auto-send/auto-execute* is not
  (reinforces [[agency-proactivity-scope-locked]]: untrusted-derived results suggest, never auto-act).

### Registry + composition + intent-router (wiring)
- **Recipe registry:** named, versioned recipes in the capability library. Each = {methodology (from APEX
  skill), execution-mode (A/②/③), tool/egress/budget grants, output contract, taint-class, metadata/trigger}.
  Grants approved at promote-time (plangate-egress-style).
- **Composition layer = A-mode (deterministic, controlled).** A capability declares an **ordered recipe
  pipeline** (approved at promote-time); the host runs it, passing tainted outputs forward, each recipe in
  its own cage. An LLM does NOT freely choose which privileged recipes to fire (that would be another
  escalation/injection surface) — *within* a ③-recipe the agent is autonomous in its cage, but the
  *orchestration between* recipes is declarative. Recursive consistency: controlled composition of
  (possibly-agentic) caged recipes.
- **Intent router (R3):** classifies request → selects capability → runs its declared recipe pipeline.

## Recipe trust classification — internal vs external/poisoning (discussion 2026-07-01)

The master classification. **Two orthogonal axes:**
- **Source trust:** does the recipe ingest untrusted EXTERNAL content?
  - `internal` — operates only on trusted internal data (owner's data, memory, files, computation). Output **trusted (untainted)**. Taint is never born here.
  - `external` / reach-out — pulls web/external content. Output **tainted**. This is where poison enters.
- **Sink sensitivity:** does it WRITE to trusted state / take a side-effect?
  - `read-only` — returns data, no durable write, no external action.
  - `trusted-write / side-effecting` — writes memory/files/DB, sends messages, triggers actions.

**The model = Biba integrity (dual of confidentiality):** low-integrity (tainted, external-sourced) data
must NOT flow into a high-integrity (trusted-write/side-effecting) sink without a **trusted upgrade** (human
review / structural validation). Layman: dirty water can't flow into the clean tank without going through a
filter you approve.

**The one danger crossing = `external-source` → `trusted-write/action` sink.** e.g. "research competitor X →
write findings into my projects DB" or "→ send a summary email." A poisoned page could inject bad data into
trusted state or trigger an action. **This crossing MUST be gated** (research yields a *tainted draft*; a
trusted gate clears it before any write/action).

**Two consequences:**
- **Taint labels persist at rest.** External-derived data stays tainted in storage (memory entries carry a
  trust label) until a gate clears it — so a later `internal` recipe reading that memory still sees it as
  tainted. Closes the "launder poison through storage" path (the memory-poisoning defense, generalized).
- **Cage cost is paid only where taint exists.** `internal`-only recipes need no egress cage (no external
  network) and can run lighter / more trusted; `external` recipes always get the full cage + broker +
  quarantine. Pay for containment only at the boundary that has poison.

### The crossing mechanism — RESOLVED: stage → gate → promote
It's not *file-vs-DB* that matters — it's **staging area (tainted, for-review) vs trusted store (read back
as authoritative).** One pattern handles both "save for later review" and "research into a project":
- Tainted external output **always lands first in a tainted staging area** (a review file / "pending" tray
  on a project) — tagged tainted, read by no recipe as trusted. This is SAFE (parked dirty water, labeled).
- It enters trusted state (project DB, memory) **only via a gate**: for a loose review-file the gate is the
  owner reading + deciding; for a project the same staged draft is cleared before the trusted write.
- **A "save it to a file to review later" IS the gate pattern** — staging, not the destination. So it's not
  a dangerous DB-write; the dangerous write is the *promotion* out of staging.
- **Gate policy (default):** human review at `external → trusted-write/action`. OPTIONAL fast-path: auto-
  clear a specific case via structural validation (strict schema + allowlisted provider + provenance) —
  owner opts a provider/shape into the fast-path; default stays human.

### Model-switching (the research agent's model is swappable)
The caged agent doesn't hold the model choice — the **broker** does — so *which* model backs a run is
**layered: recipe default (+ fallback chain) → per-task owner override at invocation** ("research this with
GPT-5.5, that with Sonnet 5"). Consistent with the existing `QuotaAwareRouter`.
- **Claude tiers** (Opus/Sonnet/Haiku) swap by `--model` flag (same claude-code runtime).
- **Cross-provider** (Claude ↔ GPT-5.5/Codex ↔ local) = swap the **agent runtime** (claude-code vs codex in
  the cage), each with its own broker/auth/pool — bigger but doable; **bonus: per-task provider choice
  balances load across the two subscription pools** (ChatGPT vs Claude weekly caps).
- **Granularity:** in ③ the per-task model is the ONE agent running the whole loop (incl. reading poison —
  fine, it's caged); the "cheap reads / strong synthesizes" per-STEP split is a deterministic-mode (A/②)
  property (the R2 split), not available inside a single caged agent.
- **Model choice is a cost AND safety lever:** cheap/local for the poison-reading tier; strong for
  trusted synthesis that never sees raw web.
- **Deferred here (owner, 2026-07-01):** per-task model selection for the R2 web tool's reader/synth is
  NOT built as a one-off on `build_web_tool` — it's delivered properly by this recipe model-switching
  feature. Today the web tool runs fixed defaults (reader haiku→sonnet, synth codex→sonnet failover).
- **Model-fit calibration phase (owner idea, 2026-07-01):** at first real use, run a shakedown — empirically
  try model combos for each role (reader, synth, and later orchestrate/pull/build) and lock the best default
  per recipe, rather than guessing. Rides on `reachout-webtool-eval` (the comparison/eval harness, already
  queued) + recipe model-swappability; cheap to run once both exist.
- **Coding roles (reaffirmed, owner 2026-07-01): Claude orchestrates, GPT (Codex) builds** — this is already
  the ADR-027 dogfood setup in use today (Opus host plans/dispatches/verifies/reviews; Codex builds each
  task). Opus-builds is only the quota-out fallback; drop it only if a Codex outage blocking builds is
  acceptable (a `coder_models` config choice, not new work).

## Architecture SCOPED (2026-07-01) — earns its own ADR when built (post-R2/R3, w/ Pattern-B + capability system)
Not needed for R2 (A-mode). Reverses ADR-035's "no tool-holding web reader" + adds the broker + the
recipe/execution-mode model → a new ADR extending ADR-035 when implementation starts.

## The core distinction (the A/②/③ execution modes)

A `CLAUDE.md`/recipe is the **briefing for an agent**, not the workflow itself. Two architectures:

- **A) Artemis orchestrates (deterministic code).** Artemis's own code owns the steps; each model call is
  a focused "just answer this" system-message completion. **R2's web tool is this** (search→fetch→read→
  synthesize in Python; the reader/synth get `_READER_SYSTEM`/`_SYNTH_SYSTEM`, no CLAUDE.md). High control,
  testable, structural quarantine. Reuses an APEX skill as *code + step-prompts embodying the methodology*.
- **B) Delegate to an agentic claude-code run (recipe-driven).** Artemis hands a whole workflow to a
  claude-code agent whose behaviour is governed by a workflow recipe (CLAUDE.md-style) dropped into the
  sanitized dir; the agent runs its own tool-loop. High autonomy, open-ended. Reuses an APEX skill as the
  *recipe fed to the agent, near-verbatim*. Fits Artemis's harness thesis ("agents do the work").

The mechanism we built (sanitized config dir) serves **both**: dir + system-message = A; dir + workflow
recipe = B.

## The fork, per capability

| | A) Orchestrate (code) | B) Delegate (recipe → agent) |
|---|---|---|
| Control / testability | High | Lower (agent picks its own steps) |
| Autonomy | We write each step | Hand it the recipe, it figures out the rest |
| Safety w/ hostile input | Structural (quarantine enforced in code) | Must be designed carefully (agent + tools + web) |
| Best for | Bounded, safety-critical (untrusted web read) | Open-ended, multi-step (deep research, repo tasks) |
| APEX-skill reuse | methodology → code + prompts | skill → recipe, near-verbatim |

**Already settled by R2:** the quarantined web read/synthesize stays **A** (tight control over hostile
input). Research is the leading candidate for **B**.

## If ③ (agentic delegation): safety envelope (discussion 2026-07-01)

③ = a **caged claude-code agent** (owner chose "its own tools"). It reverses ADR-035's rejected
alternative ("tool-holding reader over raw web") + ADR-009's no-tools-on-poison-reader rule — done
*knowingly*, made defensible by running the agent **inside the WSL2 sandbox** (enablers #1–#2, ADR-036):
- **Tool allowlist** — web-read + scratch workspace only (no host FS, no exec, no shell).
- **Egress allowlist** — its web tools go through the cage's SSRF/allowlist; can't exfiltrate.
- **No host access** — separate FS, host secrets unreachable.

### Quota containment (poisoned page can't drain the pool)
Principle: **the spend limit is enforced by the cage, not the agent** — an injection can't raise it.
- **Per-run hard ceiling:** `--max-turns` (bounds the tool loop) + **host kills the subprocess when the
  `--json` usage stream crosses a token budget** (the load-bearing knob — `--max-turns` alone doesn't stop
  one giant turn) + wall-clock timeout (sandbox runner already enforces).
- **Per-window budget:** N runs/hour·day so repeated injections can't drain the weekly pool.
- **Up-front gate (ADR-012):** expensive intents confirm before running.
- **Fallback:** low pool → Ollama-local (free).
- Residual: a poisoned run can waste *up to one capped run* on junk output; bounded, never unbounded.

### Learning from incidents — YES, but the lesson-write must be gated (memory-poisoning trap)
- **Log every incident** (structured, host-side): domain, trigger (egress-denied / token-budget-kill /
  turn-cap / detected injection), recipe, caps hit. Good observability (folds into the R2 tracing FLAG).
- **THE TRAP:** never let the *exposed/poisoned agent write its own durable lessons.* If an injected run
  can write to a memory future runs read, injection becomes **persistent** — inject once → the payload is
  stored as a "lesson" → every future run is compromised. Classic memory-poisoning.
- **Safe loop:** incident logged as UNTRUSTED data → quarantined lesson-extraction (structured, no tools) →
  **trusted/human-gated promotion** into {domain reputation / egress blocklist, recipe guardrail updates,
  detection heuristics}. Mirrors APEX's Iron Law (skills change only with human approval) + ADR-035's
  parked "egress-allowlist governance at promote-time." Uses Artemis's Cognee memory (Slice 2) — but the
  security-incident store must be **write-gated**, not agent-writable from an exposed context.
- **In-run vs cross-run:** in-run adaptation ("got egress-denied, try another source") within the turn
  budget is fine; *cross-run persistent* learning from untrusted incidents is what must be gated.

### Credential scoping — PROPOSED (broker pattern, 2026-07-01; pending the OAuth spike)
Problem: a caged claude-code agent needs the model credential where it runs, but the Claude **subscription
OAuth token is all-or-nothing** (not scopeable/mintable like an API key), and ADR-035 Option B forbids creds
in untrusted context.
Resolution: **the cage holds NO credential.** The agent points `ANTHROPIC_BASE_URL` at a **host-side model
broker** (outside the cage) that holds the real OAuth, injects auth, and forwards to Claude — the agent gets
outputs, never the token. Symmetry: the broker is the **model-call egress pipe**, mirroring R2's fetch egress
pipe; the cage ends up holding zero secrets (web I/O + model I/O both brokered — requires hard-req #1: web I/O
host-brokered, NOT native claude-code web tools, else the search key sits in the cage). Preserves the
**credential half** of Option B; the "reasoning host-side" half is consciously reversed (see synthesis).
- The broker is the natural home for the **token-budget-kill** (counts tokens as it forwards; the agent
  can't spend what the broker won't forward — stronger than watching `--json`), **incident logging**, and
  **Ollama down-routing**.
- `--bare` (wrong for the host clean-reader — breaks OAuth) is **right for the caged agent** (minimal, no
  keychain, API-key-style to the local broker).
- Residuals: (1) **needs a spike** to confirm claude-code can be pointed at a broker back-ending the
  *subscription* OAuth; (2) the **broker is trust-critical** (holds token + enforces budget) — hardened,
  host-side, never caged.

### What a recipe is (structure)
A recipe = the APEX-skill methodology + Artemis-runtime grants + an output contract. Concretely:
1. **Methodology** — the "how" prose (derived near-verbatim from the matching APEX skill, e.g. apex-research).
2. **Tool allowlist** — the caged agent's hands (e.g. `web_search`, `web_fetch`, `scratch`); NEVER shell/exec/host-fs.
3. **Egress policy** — which domains reachable (research = search-vouched, 443-only, via the cage guard).
4. **Budget/caps** — max-turns, token budget, timeout (heavy recipe = bigger budget).
5. **Output contract** — what it returns (e.g. a cited report), so the host can consume it.
6. **Metadata** — name, description, trigger (how the intent router selects it), version.

**A recipe is a privilege grant** (tools + egress + budget), so its grants are **human-approved at
promote-time** — same gate as capabilities (ADR-035 egress governance / the `plangate-egress` fast-follow),
same Iron-Law spirit (recipes change only with approval). **Two enforcement layers:** claude-code
`--allowedTools` (advertised toolset) + the WSL2 cage (the actual FS/egress boundary — holds even if the
tool layer is bypassed).

## Open questions (to resolve in the discussion)
1. **Default posture + decision rule:** which capabilities are A vs B? Is there a clean test?
2. **What is a "recipe" concretely?** Structure, storage (capability library alongside SKILL.md-authored
   capabilities? — note Artemis term is "recipe" not "skill"), and how it's selected per task.
3. **Relation to build-mode + the capability library** (CB slice): is a recipe a new *kind* of capability?
4. **Executor for B:** claude-code (subscription) vs Codex; the tool surface it's granted.
5. **Safety model for B:** an agentic run with web tools re-opens the injection/egress surface R2 closed
   structurally — how is B sandboxed (WSL2 FetchSandbox? egress allowlist? quarantine)?
6. **Terminology:** these are Artemis **recipes** (self-taught workflows), per house convention.
