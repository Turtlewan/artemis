# M0–M5 readiness-gate application manifests

_Produced 2026-06-08 by 5 parallel READ-ONLY analyst agents (one per milestone) + planning-authored M0.
These capture the exact edits to apply to the `docs/drafts/m{0..5}/` specs before the batch-move to
`docs/changes/`. The analysis (read every spec + cross-check research/ADRs) was parallelised; the
**application is single-writer (planning)** so cross-cutting conventions stay identical and no spec
diverges. If a session ends mid-application, resume from these files — do NOT re-run the analysts._

## Fork resolutions (both ADR-grounded — NOT owner questions)
1. **Volume-mount placement → fold into M2-a** (path contracted in M2-c; NOT a new M2-e). Source: ADR-005
   line 36 ("the broker also mounts a per-scope encrypted volume on unlock… The M2 broker specs gain this
   volume-mount step at finalization"). Mount point `/opt/artemis/<slot>/<scope>/vault/`.
2. **Tier-0 boot-unwrappable proactive key → implement in M2-a** as an explicit `proof_required=false`
   key policy, scoped ONLY to the `proactive` corpus. Source: ADR-006 line 14 (the "proactive key …
   unwrapped at boot — protects only the minimised corpus") + line 24 (provisioned at M2). Owner already
   ratified the posture in ADR-006. M2-d's gate must audit proactive-key scope creep (ADR-006 line 25).

## Cross-milestone dependencies (reconcile when applying M1)
- **`Brain.respond_stream(text, scope) -> AsyncIterator[str]`** — text-segment stream; lives in M1-b
  (responder ModelPort already supports `stream=True`; tool path yields its rendered answer as one
  segment). Consumed by M5-d. brain.md "stream every stage" / FINALIZATION-NOTES M5 line 39. **ADD to M1-b.**
- **`Brain.pre_route(text, scope) -> str | None`** — returns the top candidate module BEFORE serving so
  the Gateway can classify the Tier and withhold sensitive data pre-serve. Lives in M1 Brain/Gateway.
  Consumed by M5-c (+ M5-d's stream path). FINALIZATION-NOTES M5 line 40. **ADD to M1-b/M1-c.**
- **M1-a manifest sensitivity flag** — M5-c reads a per-module `sensitive: bool`/`data_scope` from the
  M1-a `ModuleManifest` as the Tier source of truth. If M1-a lacks it, add a `sensitive: bool` to the
  manifest model (M5-c carries an interim name-keyed stopgap otherwise). **Check M1-a when applying.**
  → RESOLVED 2026-06-08 (M1 applied): M1-a's `ModuleManifest` already carries `data_scope: DataScope`
  (`owner-private | guest-visible | shared`) — a strict superset of a boolean. NO new `sensitive: bool`
  field added (avoids a 2nd source of truth). **M5-c MUST read `data_scope` as the Tier source of truth**
  (`sensitive ≡ data_scope == OWNER_PRIVATE`), NOT the name-keyed stopgap. Apply this when editing M5-c.
- **M4 internal:** M4-a `add`/`update` gain `keywords`/`contextual_description`/`linked_ids` kwargs
  (A-MEM metadata, written by M4-b); `AudnDecider.__init__` gains `repo` (cardinality lookup) and
  `build_write_path` passes it. `compute_fact_key` gains `object_` param (cardinality-aware keying).

## Shared conventions brief (the decided cross-cutting facts — applied identically everywhere)
1. Data root = `/opt/artemis` (runtime data); code/repo = `/Users/artemis-build/artemis`; model cache
   `/opt/artemis/models`. Resolve any data-root NEEDS-CLARIFICATION to `/opt/artemis`.
2. ONE local-heavy role `sensitive_reasoner` (model_id `Qwen3.6-27B`, openai adapter, mlx lazy/on-demand)
   = sensitive reasoning + sensitive memory extraction. NO `extractor` role.
3. Responder `Qwen3-4B-Instruct-2507` (resident); embedder `Qwen3-Embedding-0.6B`; reranker
   `Qwen3-Reranker-0.6B`; teacher = `claude-cli` adapter (cloud; NotImplemented until M3+).
4. Runtime pins: mlx-openai-server **1.8.1** (PyPI `mlx-openai-server`), multi-model **YAML** config
   (`on_demand: true` + `on_demand_idle_timeout`), `--tool-call-parser qwen3`, structured output via
   OpenAI `response_format` + Outlines (outlines-core). NO mlx-lm spec-decode on Qwen3 (#846) → native
   MTP (on-hardware). Pin sqlite-vec.
5. Visual-doc retriever LOCKED = ColQwen2.5 Light, PyTorch MPS 2.5.1 (NOT 2.6.0).
6. GraphRAG = gated build-time spike (LightRAG vs agentic on a gold-set behind `retrieve(query,mode)`);
   agentic multi-hop stays the DEFAULT.
7. Memory absorptions: composite forgetting score as a retrieval-time re-rank multiplier (semantic only,
   NOT deletion); A-MEM note metadata columns; Graphiti 4-timestamp ref; fact-keying Option 2
   relation-cardinality registry; fold `bump_access`+`purge` into M4-a's repository.
8. Readiness gate BLOCKS on any `[NEEDS CLARIFICATION]` marker → resolve each to a decision OR a drafted
   default + a GATED on-hardware task, and REMOVE the marker text. True owner-judgment items only → flag.
9. Strip stray EOF/drafting artifacts (`</content>`, `</invoke>`).
10. Accepted split-rule exceptions (keep flag comments): M0-a, M0-d, M1-a, M4-a.

## Application status
| Milestone | Manifest | Applied? |
|-----------|----------|----------|
| M0 | below (planning-authored) | ✅ applied 2026-06-08 |
| M1 | M1.md | ✅ applied 2026-06-08 |
| M2 | M2.md | ✅ applied 2026-06-08 (volume-mount task placed as M2-a Task 10, gated SE task kept as Task 9 to preserve all cross-refs) |
| M3 | M3.md | ✅ applied 2026-06-08 |
| M4 | M4.md | ✅ applied 2026-06-08 (cross-milestone: M4-a add/update gained A-MEM kwargs + bump_access/purge; M4-b cardinality+sensitive_reasoner; M4-c calls M4-a primitives, no repository.py touch) |
| M5 | M5.md | ✅ applied 2026-06-08 (M5-c Tier signal = M1-a `data_scope` source of truth, NOT name-keyed stopgap; M5-c/M5-d consume the M1 respond_stream + pre_route back-fills already added to M1-b/M1-c) |

After all applied → batch-move `docs/drafts/m{0..5}/` + `docs/drafts/m{6,7}/` → `docs/changes/`, then `apex-init`.

---

## M0 manifest (planning-authored)

### M0-a-foundation-layout.md
- **Marker (line 17):** resolve the `[NEEDS CLARIFICATION: confirm /opt/artemis … vs a runtime-user home …]`
  → DECISION: data root = `/opt/artemis` (all five M0 specs inherit it). Replace the bracketed marker with
  marker-free prose: "Runtime data root = `/opt/artemis` (writable by the runtime service user, outside any
  user home so the build agent cannot read it — see M0-e isolation). The build-agent repo/home stays
  `/Users/artemis-build`." Remove the marker.
- **Task 2 (line 48):** `sensitive_reasoner` (local mlx base URL, model `Qwen3-14B`, adapter `openai`) →
  model `Qwen3.6-27B`. Add comment `# local heavy: sensitive reasoning + sensitive memory extraction (lazy)`.
- No EOF artifact. Keep the split-rule flag comment (line 13).

### M0-b-launchd-services.md
- **Marker (line 18):** resolve `[NEEDS CLARIFICATION: is the ntfy binary install part of M0 …]`
  → DECISION (FINALIZATION-NOTES "ntfy install in M0"): ntfy IS installed in M0. Replace marker with:
  "ntfy is installed in M0 via Homebrew (`brew install ntfy`) as part of the deploy bootstrap; binary path
  `/opt/homebrew/bin/ntfy` (exact path confirmed on-hardware — GATED). M0-b writes its plist against that
  path." Remove the marker. (The actual `brew install ntfy` runs in M0-c's install script alongside mlx, or
  the deploy bootstrap — add a one-line note to M0-c Task 1; see M0-c below.)
- {LOGS_DIR}/{REPO_DIR} derive from M0-a (data_root=/opt/artemis) — no direct edit.

### M0-c-mlx-server.md
- **Marker (line 18):** resolve `[NEEDS CLARIFICATION: confirm the exact PyPI package name and CLI …]`
  → DECISION: mlx-openai-server **1.8.1**, PyPI name `mlx-openai-server`, multi-model **YAML** config,
  `--tool-call-parser qwen3`, OpenAI `response_format` + Outlines. Replace the marker with these as stated
  facts + "live serve/throughput confirmed on-hardware (GATED Tasks 4–5)." Remove the marker.
- **Files table (line 32) + Task 2 (line 41):** change `config/mlx.toml` → `config/mlx-models.yaml`
  (1.8.1 uses YAML multi-model config). Rewrite Task 2 to a YAML config: top-level model list, each entry
  `{model_id, model_path, on_demand: <bool>, on_demand_idle_timeout: <s>}`, plus `--tool-call-parser qwen3`.
  Served models = `Qwen3-4B-Instruct-2507` (on_demand:false, resident), `Qwen3-Embedding-0.6B`,
  `Qwen3-Reranker-0.6B`, `Qwen3.6-27B` (the sensitive_reasoner; on_demand:true + idle timeout). NOT teacher
  (claude-cli). Acceptance line 109 (`tomllib.load mlx.toml`) → load the YAML (`yaml.safe_load`) and assert
  exactly one resident (on_demand:false) model.
- **Task 1 (line 39):** `uv add mlx-openai-server` → `uv add "mlx-openai-server==1.8.1"`. Add: "also
  `brew install ntfy` here (M0-b plist consumer); confirm path on-hardware."
- Replace remaining `Qwen3-14B` / `Qwen3-Reranker` strings with `Qwen3.6-27B` / `Qwen3-Reranker-0.6B`.

### M0-d-ports-scaffolding.md
- **Marker (line 20):** resolve `[NEEDS CLARIFICATION: expose as_of as a single datetime … or AsOf(...)]`
  → DECISION (FINALIZATION-NOTES + ADR-004): `AsOf` frozen dataclass `{valid_at: datetime, tx_at: datetime
  | None = None}` (tx defaults to now). The draft already drafts this — restate as decided, remove the marker.
- Keep the split-rule flag comment (line 13).

### M0-e-isolation-backup.md
- **Marker (line 19):** resolve `[NEEDS CLARIFICATION: … backup script as a runnable skeleton over
  sample/empty DBs …]` → DECISION (FINALIZATION-NOTES "backup skeleton runs over sample/empty DBs"): yes —
  M0-e ships the backup script as a runnable skeleton over sample/empty DBs proving the VACUUM-INTO-not-raw
  mechanic; the real keyed dump (Keychain scope key) lands at M4. Remove the marker.
- **Marker (line 42):** resolve `[NEEDS CLARIFICATION: the exact Claude Code OS-sandbox config schema/
  filename …]` → DECISION (FINALIZATION-NOTES "sandbox config schema = on-hardware confirm"): ship the
  drafted JSON profile; the exact schema/filename is confirmed against the installed Claude Code on the Mini
  (GATED Task 7). Remove the marker (downgrade to gated on-hardware confirm).
- Data root: setup_build_user.sh ACL denies reference `/opt/artemis/<slot>/owner-private` explicitly.
