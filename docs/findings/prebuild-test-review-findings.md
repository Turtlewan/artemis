# Pre-build test-review — synthesis & findings

_Created 2026-06-18. Synthesises the section-by-section owner walkthrough of the 121-test
validation suite (`docs/drafts/prebuild-test-review.md`, all 12 sections reviewed). This is the
durable home for the findings; the draft holds the per-section owner commentary._

**Verified baseline (live run @ commit `5975b30`):** 121 tests pass · ruff clean · `mypy src` clean
(43 files) but **14 errors under `mypy src tests`** (the scope gap — see Bucket 1). 0 real model
calls; all fakes/deterministic vectors.

**Overall verdict:** the validation slice is healthy. No correctness bugs in production code were
found. Every finding is one of: (a) a *test-quality / coverage-honesty* gap, (b) a "what the green
bar does **not** prove" item that resolves on the Mini, or (c) a forward design follow-up. The
recurring theme is **"the green bar proves less than it looks like it does"** — driven mostly by the
single root cause that test files were never type-checked (`mypy src`, not `mypy src tests`).

---

## Bucket 1 — Fix-queue (one small DeepSeek session, ~15 min)

Mechanical and decided. All low-risk; clears the 14 mypy errors + the flaky test + the hollow asserts.

| ID | Fix | Files |
|----|-----|-------|
| **Root** | Make the corpus **Verification Recipe** `mypy src tests` (was `mypy src`). This is the root cause that hid F3-a, F6-b, F10-b, F11-a, F12-a. | stack-skill Verification Recipe / CI step |
| **F6-a** | Flaky `test_retrieve_tools_returns_fq_ids` — `FakeEmbedder._hash_vec` uses per-process-salted `hash()`. Replace with `hashlib.sha256(word.encode())`. (The bitemporal test's `sum(ord(c))` fake is already the stable pattern — F9-b.) | `tests/test_manifest_registry.py` |
| **F11-a** | 4 mypy errors — fakes return `list[list[float]]` where ports expect `list[Sequence[float]]` (list-invariance). Widen fake return annotations. | `tests/test_offline_compose.py` |
| **F12-a** | 10 mypy errors — test fns omit the `tmp_path: Path` annotation (`no-untyped-def`). | `tests/test_vector_store.py` |
| **F3-a** | `test_static_conformance` is hollow (weak `isinstance`; the real check needed `mypy --strict src tests`). Resolved once the Recipe changes; verify it actually exercises the Protocol conformance. | `tests/test_ports.py` |
| **F6-b** | `test_port_conformance` — `vs: Any = index` checks nothing. Annotate `vs: VectorStore`. | `tests/test_manifest_registry.py` |
| **F5-a** | Stray duplicate docstring (leftover `"""Engine-agnostic embedding vector."""` on `Mode`, lines 18–20). | `src/artemis/ports/types.py` |
| **F7-a** | Stale comment (lines 234–236) describes a "bag-of-words hash" match, but this file's `FakeEmbedder` returns a constant unit vector. | `tests/test_router_brain.py` |
| **F10-b** | Async tests rely on `asyncio_mode=auto` with no explicit `@pytest.mark.asyncio` (inconsistent w/ other files). Cosmetic — align if touching. | `tests/test_model_auth.py` |

---

## Bucket 2 — Mini-verification checklist (carry to first Mac build)

These are **not bugs** — they are the things the offline green bar *cannot* prove. Verify on hardware.

| ID | Verify on the Mini |
|----|--------------------|
| **F7-b / F9-c / F12-c** | **Ranking quality with real embeddings.** All recall/routing tests use deterministic/one-hot fakes that match everything-to-everything or are perfectly separable → they prove plumbing, not "picks the *right* one among similar candidates." Re-verify with served Qwen3 embeddings. |
| **F12-b** | **FTS actually runs.** The 3 full-text tests `pytest.skip()` when native FTS is unavailable — a host without it shows green while testing nothing. Assert FTS is live on the Mini (fail loud / count skips), don't trust the green run. |
| **F9-d** | **SQLCipher encryption + encrypted-store crash-safety.** Memory tests run plain sqlite (Tasks 1/3/5 Mini-gated). Verify encryption-at-rest and that the *encrypted* store survives a mid-write kill. |
| **F8-c** | **Power-loss / hard-kill posture** (from the owner's power-trip question). Graceful cancellation is tested; SIGKILL is untestable with fakes. On the Mini confirm: (a) SQLCipher + LanceDB survive a kill mid-write; (b) the heartbeat resumes cleanly under launchd; (c) decide missed-tick **catch-up vs skip** for M6; (d) GATE actions are **idempotent** across a crash. Ties to the agent-loop invariant (idempotent · bounded · clean-state · externally-verified). |
| **F4-a** | **`/readyz` real checks.** Readiness currently asserts `checks == {}` — populate real dependency checks (model server / vault / DB) before prod, or it gives the exact false-"ready" readiness exists to prevent. |
| **streaming** | Live free-form **token** streaming — only tool-path SSE is proven offline. |

---

## Bucket 3 — Design follow-ups (spec flags / BACKLOG)

| ID | Follow-up | Home |
|----|-----------|------|
| **F2-a** | Tighten the `guest-` prefix in `scope_dir` (any `guest-*` string passes; a poisoned id `guest-../../owner-private` would slip). Require a clean charset before untrusted input can reach `scope_dir`. NB the vector store **already** does this kind of scope validation (`test_invalid_scope_rejected`) — reuse that discipline. | flag near DR-a / identity layer |
| **F2-b** | Confirm `ValueError` from `scope_dir` is caught + surfaced sensibly (OBS-a logging w/o sensitive data → ntfy via M6 for serious → router softening for user-facing), not crashing the brain. | flag on later wiring specs |
| **F9-a** | Cross-store provenance unclosed: the suite tests conversation-turn provenance (`source_turn_id`) only. Does a fact extracted during **M3 document ingestion** point back to its source M3 chunk? Decide at the M4-b / M3↔M4 seam. (Already an Open Question in status.md.) | M4-b / M3↔M4 seam |
| **F8-b** | Heartbeat is a skeleton (every beat returns `HEARTBEAT_OK`). Real hooks/LLM/proactive work land in M6 — expected, noted. | M6 |
| **F8-a** | `test_manifest_data_scope` docstring over-claims ("SHARED maps to 'general' at storage") but only asserts the enum value is `"shared"`. Stale comment or a missing storage-mapping assertion. | minor / M1-d cleanup |
| **V-1** | **Whole-document & aggregate retrieval gap** (video fit-eval). Vector chunking fails faithful whole-doc summarisation + table aggregates. → BACKLOG (cross-ref existing summary-first + structured-token items). | BACKLOG |
| **V-2** | **Active knowledge elicitation ("grill me")** (video fit-eval). No owner-interview path to populate M4; M7-c curiosity is web-grounded only. → BACKLOG. | BACKLOG |

---

## Video fit-eval — "5 Levels of an AI Second Brain" (2026-06-18)

Owner shared the transcript mid-walkthrough. **Verdict: Artemis spans/exceeds all 5 levels**
(L1 router → M1-a; L2 wiki/auto-memory → M3 + M4; L3 vector/hybrid/rerank → M3-a/b; L4 graph →
M4-d entity backbone ADR-013; L5 always-on → M6 + M7). The video's admitted weakness — the author's
whole second brain ships to Anthropic ("that's not private") — is exactly Artemis's local-first,
SQLCipher-encrypted reason to exist. **Strong validation of the locked stack; nothing to change.**

Three takeaways → **V-1** and **V-2** to BACKLOG (above); **V-3** ("Context vs Connections":
evergreen vs ephemeral — don't ingest volatile data, fetch live in a defined order) is a **validation
only** — it maps 1:1 onto Artemis's router→memory→knowledge→spoke chain + M4 decay + Gmail quarantine;
could become an explicit one-line ingestion principle if/when M3-a is revisited.

---

## Next action

Bucket 1 is drafted as a ready spec → **`docs/changes/fix-validation-test-quality.md`** (`coder_tier: flash`,
7 files, no Mini dependency — WSL2-buildable now for a clean baseline, or batched for the Mini). Buckets 2 & 3
are carry-forward, no action now.
