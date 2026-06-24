# Dev model stack — real local models via Ollama (Windows dev box)

The dev twin of M0-c's `mlx-openai-server`. Both sit behind `config/roles.toml`'s
OpenAI-compatible seam, so pointing a role at Ollama needs **no adapter code change** —
only the config edits already applied in this spec. This lets the brain run + be tested
against **real** embeddings/responder instead of the `FakeEmbedder`/cloud-only path.

- **dev** (this box, RTX 5060 Ti 8 GB / Ryzen / CUDA): Ollama at `http://127.0.0.1:11434/v1`.
- **prod** (Mac Mini): `mlx-openai-server` at `:8040` — regenerated at Mini bring-up (M0-c).
  The mlx values are preserved as per-role comments in `config/roles.toml`.

## 1. Install Ollama (Windows)

Download + install from <https://ollama.com/download> (or `winget install Ollama.Ollama`).
CUDA is auto-detected on the RTX 5060 Ti — no extra config. Confirm the server is up:

```
ollama --version
curl http://127.0.0.1:11434/api/tags        # should return JSON (empty list before pulls)
```

## 2. Pull the lean model set (≈4 GB, all hot)

```
ollama pull qwen3:4b               # responder + sensitivity classifier (reuses this role)
ollama pull qwen3-embedding:0.6b   # embedder (expect 1024-dim)
ollama pull qwen3-reranker:0.6b    # reranker
```

> ⚠ **Verify the exact tags + embedding dimension at pull.** Ollama library tags drift
> (official vs community e.g. `dengcao/*`). After pulling, run `ollama list`, confirm the
> resolved tags + that the embedder reports **1024** dims, and reconcile them back into
> `config/roles.toml` ([responder]/[embedder]/[reranker] `model_id`) if they differ from
> the placeholders. If `qwen3-embedding`/`qwen3-reranker` aren't available as official tags,
> use the closest community tag and record it here.

## 3. Keep the set hot (no eviction at this scope)

```
setx OLLAMA_KEEP_ALIVE -1          # (PowerShell: $env:OLLAMA_KEEP_ALIVE = "-1"); or "60m"
```

The ≈4 GB lean set (embedder + reranker + 4B) stays resident. The M9 load/evict policy
only applies once the heavier models (vision M3-d, 8B sensitive reasoner) join.

## 4. Run

```
uv run python scripts/dev_chat.py --real      # real Ollama embedder
uv run python scripts/dev_chat.py             # FakeEmbedder (offline, non-semantic)
```

## 5. Verify checklist (= the ADR-022 parked-(b) empirical answer)

1. **Real-embedding routing differs from FakeEmbedder.** Ask a few semantically-related
   questions under `--real` and confirm tool/route selection is meaningfully better than the
   hash-based FakeEmbedder run (which has no semantic signal).
2. **Tool-calling works through Ollama.** A tool-routed query (e.g. "what time is it?")
   returns a tool-backed answer → Ollama's OpenAI-compatible `/chat/completions` +
   Qwen3 tool-calling round-trips.
3. **Structured output works through Ollama.** A structured-output call returns schema-valid
   JSON via Ollama (`format`/json-schema + Qwen3). Record the result of (2) + (3) here — they
   are the empirical answer to ADR-022 parked item (b) (can the local stack do tool-calling +
   structured output).

## Deferred / not in this set

- **8 B sensitive reasoner** — N/A until distilled post-Mac (`distill-datagen-pipeline`).
- **Vision** — M3-d. **Voice** — M5.
- **Non-sensitive cloud path** — Codex (separate `codex` adapter, not an Ollama role).

## Known follow-up

`config/roles.toml [sensitivity_classifier]` still points at the prod mlx endpoint
(`:8040`). It reuses the responder model (decided 2026-06-23) and must stay loopback. When
the sensitivity path is exercised on this dev box, point it at Ollama `:11434` too (out of
this spec's scope — flagged for planning).
