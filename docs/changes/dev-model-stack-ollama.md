---
spec: dev-model-stack-ollama
status: ready
token_profile: lean
autonomy_level: L2
---

# Spec: dev-model-stack-ollama — stand up the real local model stack on the Windows dev box (Ollama)

**Identity:** Wires the brain to **real local models via Ollama** on the 8GB Windows dev box — the dev twin of M0-c's mlx-openai-server, both behind `roles.toml`'s OpenAI-compatible seam — so the brain runs + is tested against real embeddings/responder instead of the `FakeEmbedder`/cloud-only path. Dev-first (ADR-022 Windows-first; ADR-026). Captures the runbook's "running it (Ollama local models + config wiring)" Phase-2.

<!-- DEV-FIRST: Windows/CUDA, 8GB VRAM. Prod (Mac/MLX) keeps M0-c's mlx-openai-server config; this does NOT change M0-c. roles.toml on the dev box IS the dev config (dev_chat already treats it as editable); M0-c regenerates the prod roles config at Mini bring-up. -->

## Assumptions
- The validation-slice brain is built + green (M0-a..M1-c, `compose_brain`, `OpenAIModelPort`, `OpenAIEmbeddingModel`, `scripts/dev_chat.py`). → impact: Stop (this spec only re-points config + adds a dev REPL flag; no brain logic changes).
- `compose_brain(settings)` already defaults the embedder to the real `OpenAIEmbeddingModel(settings)` (`gateway.py`); `dev_chat.py` currently *overrides* it with `FakeEmbedder`. So "use real embeddings" = drop the override. → impact: Stop (the `--real` path passes no `embedder=`).
- `OpenAIModelPort` / `OpenAIEmbeddingModel` resolve `(endpoint, model_id)` per role from `roles.toml` and are endpoint-agnostic — pointing a role at Ollama needs **no adapter code change**, only a config edit. → impact: Stop.
- Ollama serves an OpenAI-compatible API at `http://127.0.0.1:11434/v1` (`/chat/completions`, `/embeddings`) and supports tool-calling + `format`/structured-output for Qwen3. → impact: Caution (the two are the acceptance-criteria watch-items below; confirm empirically — this is also the empirical answer to ADR-022 parked (b)).
- The sensitivity classifier **reuses the responder role** (decided 2026-06-23) — no separate model/role. → impact: Low.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `config/roles.toml` | modify | Point `responder` / `embedder` / `reranker` at Ollama (`http://127.0.0.1:11434/v1` + Ollama model ids); keep the mlx (`:8040`) values as comments. `teacher` / `responder_cloud` / `sensitive_reasoner` unchanged. |
| `scripts/dev_chat.py` | modify | Add a `--real` flag: compose with the real embedder (no `FakeEmbedder` override) when set; FakeEmbedder otherwise. |
| `docs/bring-up/DEV-MODEL-STACK.md` | create | Runbook: Ollama install (Windows/CUDA) + the 3 model pulls + keep-alive + the verify checklist (the two watch-items). |

## Exact changes

- [ ] **Task 1 — point `config/roles.toml` at Ollama** (dev box). For `[responder]`, `[embedder]`, `[reranker]`: set `endpoint = "http://127.0.0.1:11434/v1"`; keep `adapter = "openai"`; set `model_id` to the Ollama tag (resolve the exact tag at pull — Ollama-library-empirical, like M0-c Task 4):
  - `[responder]` → `model_id = "qwen3:4b"` (the Qwen3-4B-Instruct variant; verify the exact Ollama tag at pull)
  - `[embedder]` → `model_id = "qwen3-embedding:0.6b"` (1024-dim; verify exact tag)
  - `[reranker]` → `model_id = "qwen3-reranker:0.6b"` (verify exact tag)
  - Leave the prior mlx values as a trailing `# prod (M0-c, Mac): http://127.0.0.1:8040/v1` comment per role. Do NOT touch `[teacher]`, `[responder_cloud]`, `[sensitive_reasoner]`. Add a top-of-file comment: "dev = Ollama (this box); prod mlx config regenerated at Mini bring-up (M0-c)."
  - done when: `config/roles.toml` parses (the brain boots) and the three roles resolve to `:11434`.

- [ ] **Task 2 — `scripts/dev_chat.py` `--real` flag.** Parse `--real` from `sys.argv` (no new deps). When present: `gateway = Gateway(compose_brain(settings))` (real `OpenAIEmbeddingModel` via the default path). When absent: the existing `FakeEmbedder` path, unchanged. Update the startup print + module docstring to say which embedder is active.
  - done when: `uv run --frozen ruff check scripts/dev_chat.py` + `uv run --frozen mypy --strict scripts/dev_chat.py` pass; `--real` composes without `FakeEmbedder`.

- [ ] **Task 3 — `docs/bring-up/DEV-MODEL-STACK.md`.** Write the runbook:
  1. **Install Ollama** (Windows; CUDA auto-detected on the RTX 5060 Ti).
  2. **Pull models:** `ollama pull qwen3:4b` · `ollama pull qwen3-embedding:0.6b` · `ollama pull qwen3-reranker:0.6b` (note: confirm exact tags / embedding-dim 1024; record the resolved tags back into Task 1).
  3. **Keep-alive:** set `OLLAMA_KEEP_ALIVE` long (e.g. `-1` / `60m`) so the ~4GB lean set (embedder + reranker + 4B) stays hot — no eviction needed at this scope (M9 load/evict policy only applies once vision/8B join).
  4. **Run:** `uv run python scripts/dev_chat.py --real`.
  5. **Verify checklist** (= ADR-022 parked (b) empirical): (a) real-embedding semantic routing differs from FakeEmbedder; (b) a tool-routed query returns a tool-backed answer (tool-calling through Ollama OpenAI-compat + Qwen3); (c) a structured-output call returns schema-valid JSON via Ollama (`format`/json-schema + Qwen3).
  6. Note the deferred models (8B sensitive reasoner = N/A till distilled post-Mac; vision = M3-d; voice = M5) and that the cloud non-sensitive path = Codex (separate adapter).
  - done when: the doc exists with the install + 3 pulls + keep-alive + run + the 3-item verify checklist.

## Acceptance criteria
1. `grep 11434 config/roles.toml` → 3 endpoints (responder/embedder/reranker). 
2. `uv run python scripts/dev_chat.py --real` boots, and a question returns a streamed response using the **real** Ollama embedder (not FakeEmbedder).
3. A tool-routed query (e.g. asking the time) returns a tool-backed answer → tool-calling works through Ollama.
4. A structured-output probe returns schema-valid JSON via Ollama → structured output works (records the parked-(b) answer in the runbook).

## Commands to run
```
ollama pull qwen3:4b
ollama pull qwen3-embedding:0.6b
ollama pull qwen3-reranker:0.6b
uv run --frozen ruff check scripts/dev_chat.py
uv run --frozen mypy --strict scripts/dev_chat.py
uv run python scripts/dev_chat.py --real
```
