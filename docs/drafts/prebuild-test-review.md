# Prebuild test-review walkthrough (resume artifact)

_Created 2026-06-17. Purpose: drive a section-by-section review of the validation-slice test
suite. Owner reads one section at a time and writes comments; agent collects them here. This is a
**review/discussion**, not a spec — output may become findings, backlog items, or small fix specs._

## Verified results (live run, 2026-06-17, committed tree @ 5975b30)

- **121 tests pass** (`uv run --frozen pytest -q`) — 4.0s, 0 real model calls.
- **ruff clean** (`ruff check .` → all checks passed).
- **mypy `--strict` NOT fully clean** — `src` clean (43 files), but **14 errors in 2 test files**:
  - `tests/test_vector_store.py` (10×) — `no-untyped-def`: test functions missing param annotations (slice-3a).
  - `tests/test_offline_compose.py` (4×) — fake doubles return `list[list[float]]` where the split
    `EmbeddingModel.embed_documents` / `ModelPort.embed` expect `list[Sequence[float]]` (list-invariance nit).
  - **Root cause:** build sessions ran `mypy src`, not `mypy src tests`. Handoff/status overstated "mypy clean."
  - **Action candidates (not yet decided):** (1) record the mypy-scope gap so the corpus Verification
    Recipe is `mypy src tests`; (2) queue a ~10-min DeepSeek fix (annotate test fns + widen 2 fake return types).
- **Known flaky:** `test_manifest_registry.py::TestToolRegistry::test_retrieve_tools_returns_fq_ids`
  depends on iterator ordering (passed in all runs here; wants a `sorted()` when next touched).

## Walkthrough order (13 sections = 13 test files) + owner comments

Agent shows one section, owner comments, agent records below. Tick when reviewed.

- [ ] 1. `test_config.py` (5) — reading the settings file
- [ ] 2. `test_paths.py` (10) — where files live (privacy-zone folders)
- [ ] 3. `test_ports.py` (9) — the pluggable interface "shapes" (incl. embed split, no-tools guarantee)
- [ ] 4. `test_health.py` (2) — liveness/readiness stubs
- [ ] 5. `test_gateway_surfaces.py` (8) — the front-door API + SSE streaming
- [ ] 6. `test_manifest_registry.py` (17) — the tool catalogue + search index
- [ ] 7. `test_router_brain.py` (8) — routing a request / escalation / degrade-on-error
- [ ] 8. `test_time_tool_heartbeat.py` (12) — the clock tool + recurring heartbeat
- [ ] 9. `test_memory_bitemporal.py` (33) — the second-brain memory (facts + full history)
- [ ] 10. `test_model_auth.py` (4) — model-server bearer auth
- [ ] 11. `test_offline_compose.py` (2) — fake-model offline path (← 4 mypy nits)
- [ ] 12. `test_vector_store.py` (9) — LanceDB doc search (dense + FTS + dimension-lock) (← 10 mypy nits)

### Owner comments (filled in during the walkthrough)
_(none yet — start at section 1)_

## What's NOT proven by the green bar (carry into review)
All fakes / deterministic vectors. Unverified until the Mini: real MLX serving + real embeddings
(Qwen3 loading, 3 resident models in RAM); live free-form token streaming (only tool-path SSE tested);
SQLCipher encryption (M4-a Tasks 1/3/5 Mini-gated); the escalation path is a stub assertion.

## Resume instructions (for the fresh context)
1. Read this file. Do NOT re-run the whole suite unless asked — results above are current as of @ 5975b30.
2. Routing is PLANNING mode (Anthropic). This is a review discussion, not a build.
3. Start at the first unticked section. Show the agent's plain-English breakdown of that file's tests,
   wait for owner comments, record them under "Owner comments," tick the box, move to the next.
4. When all sections reviewed: synthesise owner comments into findings / backlog / fix-spec candidates.
