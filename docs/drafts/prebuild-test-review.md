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

- [x] 1. `test_config.py` (5) — reading the settings file
- [x] 2. `test_paths.py` (10) — where files live (privacy-zone folders)
- [x] 3. `test_ports.py` (9) — the pluggable interface "shapes" (incl. embed split, no-tools guarantee)
- [x] 4. `test_health.py` (2) — liveness/readiness stubs
- [x] 5. `test_gateway_surfaces.py` (8) — the front-door API + SSE streaming
- [x] 6. `test_manifest_registry.py` (17) — the tool catalogue + search index
- [x] 7. `test_router_brain.py` (8) — routing a request / escalation / degrade-on-error
- [x] 8. `test_time_tool_heartbeat.py` (12) — the clock tool + recurring heartbeat
- [x] 9. `test_memory_bitemporal.py` (33) — the second-brain memory (facts + full history)
- [x] 10. `test_model_auth.py` (4) — model-server bearer auth
- [x] 11. `test_offline_compose.py` (2) — fake-model offline path (← 4 mypy nits)
- [x] 12. `test_vector_store.py` (9) — LanceDB doc search (dense + FTS + dimension-lock) (← 10 mypy nits)

### Owner comments (filled in during the walkthrough)

**Section 1 — `test_config.py`:** No defect raised. Owner worked through the layman framing
(config = the "staff directory / phone book" — *who* the models are and how to reach them, NOT the
deciding-which-to-call logic, which is the router in section 7). Agent flagged (not owner): tests 2 & 5
are conditional and can go green without asserting much (test 4 already hard-asserts the role set, so
test 2's adapter checks could be unconditional). Carry as a soft tightening candidate.

**Section 2 — `test_paths.py`:** No defect in the tests; foundation (path math + fail-loud on unknown
scope) is solid. Discussion clarified that a `scope` is a **trust label the system stamps around the AI**
(derived from identity + sensitivity), NOT a prompt into the AI and NOT raw user text. Two follow-ups to
carry forward (both future-spec, not slice bugs):
  - **(F2-a) Tighten the `guest-` prefix.** `scope_dir` accepts any string starting with `guest-`
    (`paths.py:35`), so a malformed/poisoned guest id (`guest-../../owner-private`) would pass. Before
    untrusted input can reach `scope_dir` (real spokes / DR-a quarantine), require guest ids to be a clean
    charset (e.g. alphanumeric). Security follow-up; lives near DR-a + the identity layer.
  - **(F2-b) Confirm error surfacing.** `ValueError` is fail-loud (good). Verify that when it throws, it's
    caught and surfaced sensibly (logged w/o sensitive data → OBS-a; serious ones → ntfy via M6; user-facing
    softening → router/brain) rather than crashing the brain. Wiring lives in later specs, not the slice.

**Section 3 — `test_ports.py`:** Owner grasped the ports model fully (sockets/plug-shapes; modules must
conform to a shared contract on BOTH inputs and outputs; can't drift unilaterally; contract changes are
deliberate + system-wide; type-checker flags every broken site automatically but a coding session does the
actual fix — "it can never lie about what's broken"). Two notable findings:
  - **Test 7 (`test_model_port_no_tools_param`) is a security shape, well-designed** — the raw `ModelPort`
    has no `tools`/`tool_choice`/`stream` slot, so the model that scores untrusted content physically cannot
    act (DR-a quarantine expressed as plumbing). Good; no action.
  - **(F3-a) Test 9 (`test_static_conformance`) is currently HOLLOW.** Its docstring relies on
    `mypy --strict src tests` to validate the dummy→Protocol conformance, but builds ran `mypy src` only — so
    the check it claims never ran; at runtime it only does weak `isinstance` asserts. **Upgrades the
    mypy-scope gap from cosmetic to "a conformance test ran unverified."** Reinforces: Verification Recipe must
    be `mypy src tests`.

**Section 4 — `test_health.py`:** No defect; owner satisfied. Covers the two checkup endpoints
(`/healthz` = liveness "are you alive", `/readyz` = readiness "are you ready for traffic"). One
"fill-before-prod" marker (by design, not a bug):
  - **(F4-a) `/readyz` is a stub.** Test asserts `checks == {}` (`test_health.py:28`) — readiness answers
    "ready" without checking any real dependency (model server reachable? vault mounted? DB open?). Fine for
    the slice; must be populated before prod or it gives the exact false-"ready" that readiness exists to
    prevent. The empty dict is the literal seam where those checks plug in.

**Section 5 — `test_gateway_surfaces.py`:** No defect; owner satisfied. Front door (Gateway) +
`/ask` + `/ask/stream` (SSE). Confirms the section-2 point in code: the Gateway **stamps `OWNER_SCOPE`** on
every request (FakeBrain even asserts it). Notes:
  - Everything is owner-scoped, always — no guest/multi-user path at the door yet (correct for single-owner
    appliance + slice). The multi-scope privacy machinery isn't *exercised* here; this is where guest/auth
    later plugs in.
  - `[DONE]` terminal SSE marker is tested (good — prevents client hang).
  - Only **tool-path** streaming is proven (fake yields one fixed chunk). Real **token** streaming from a
    live model is unverified until the Mini — matches the "what's not proven" note.

**Side discussion — data-structure-first?** Confirmed yes: structure designed before code, in 3 layers —
`data-model.md` (blueprint) → `contracts.md` (frozen cross-module seams) → `src/artemis/ports/types.py`
(real typed shapes: `Fact`/`Document`/`Chunk`/`RetrievedChunk`/`Message`/`Usage`/`AsOf`/`PersonId`/`Scope`/
`Vector`). Core spine data is designed AND built; spoke data (Gmail/Calendar/Productivity) is designed in
module docs but tables not yet built (Mini-gated). Cosmetic finding:
  - **(F5-a) Stray docstring in `types.py`.** Lines 18–20: `Mode` has its correct docstring (line 19) but
    line 20 is a leftover `"""Engine-agnostic embedding vector."""` copy-pasted from `Vector`. Harmless no-op
    string; one-line cleanup when next touching the file.

**Section 6 — `test_manifest_registry.py`: REVIEWED ✅** (owner: "move" — no further comment, findings
stand: #1/#2 = good/no-action; **F6-a flaky FakeEmbedder → stable hash** + **F6-b annotate `vs: VectorStore`**
into the fix-queue).
Agent breakdown delivered (tool catalogue + RAG-for-tools, M1-a): ModuleManifest = department menu card
(name + `data_scope` + permissions + tools); ToolSpec = one dish (+ `action_risk`); ToolRegistry = maître d'
with a search-by-meaning index. 17 tests in 3 groups (menu validation ×5 · search index ×3 incl. scope
filter · registry ×9). Agent-surfaced findings to confirm on resume:
  - **(#1, good — no action) `_execute` twin = write-safety at the catalogue level.** WRITE-risk tools get a
    hidden `..._execute` twin; `retrieve_tools` deliberately never surfaces it, so the AI can stage/propose
    but never directly fire the world-changing verb (ties to GATE-a/b). Strong design; tests
    `test_execute_twin_registration` + `test_retrieve_tools_no_execute_twins` enforce it.
  - **(#2, good) Export drops `callable_ref`** (`test_export_round_trip:402`) — index is pure data, no live
    function pointer serialized.
  - **(F6-a, RECOMMENDED FIX) Root cause of the "known flaky test" `test_retrieve_tools_returns_fq_ids`.**
    The handoff blamed "iterator ordering"; agent's read is deeper — `FakeEmbedder._hash_vec` (lines 51–61)
    uses Python's builtin `hash(word)`, which is **per-process salted** (`PYTHONHASHSEED`). So the
    "deterministic" embedder is deterministic only *within* a run, not *across* runs → "what time is it" vs
    time/email similarity can shift/tie between runs = the intermittent failure. **Fix = make the fake truly
    deterministic** (`hashlib.sha256(word.encode())` instead of `hash()`), not `sorted()`. Queue as a
    ~10-min fix alongside the mypy-scope fix.
  - **(F6-b, minor) `test_port_conformance` oversells itself.** Line 242 `vs: Any = index` with a comment
    claiming "type-checks under mypy --strict" — assigning to `Any` checks nothing about `VectorStore`
    conformance. Same family as F3-a. Tighten by annotating `vs: VectorStore`.

**Section 7 — `test_router_brain.py`: REVIEWED ✅** (owner: "continue" — no defect raised; re-explained
in plain English). Covers all three reactive outcomes (tool succeeds · escalate · tool-error degrade) +
streaming + pre-route peek. Findings stand:
  - **(#1, good)** All three outcomes tested — a thrown tool returns `TOOL_ERROR`, never crashes the brain.
  - **(F7-a, minor)** Stale comment lines 234–236: claims a "bag-of-words hash" match, but this file's
    `FakeEmbedder` returns a **constant unit vector** (matches everything at cosine 1.0). Misleading; trivial cleanup.
  - **(F7-b, what's-not-proven)** Constant-unit fake ⇒ every query matches every tool, so routing *plumbing*
    is proven but **semantic discrimination is not** (picking the right tool among several). Real embeddings on
    the Mini close this. Negative cases use an empty registry, not a wrong-tool case.
  - **(#2, known)** Escalation still a stub (`ESCALATION_NOT_AVAILABLE`) — matches the global "escalation is a stub" note.

**Section 8 — `test_time_tool_heartbeat.py`: REVIEWED ✅** (owner: "oki"). Time tool (basic/tz/invalid-tz) +
6 manifest-contract checks + heartbeat (tick/bounded-count/clean-cancel). Owner asked the sharp question
**"what about a sudden power trip?"** → surfaced a new finding:
  - **(#1, good)** Heartbeat tests cover the three forever-loop essentials: beats · counts exactly · **stops cleanly** (cancellation).
  - **(F8-a, minor)** `test_manifest_data_scope` docstring over-claims — says "SHARED maps to scope **'general'** at
    storage" but only asserts the enum value is `"shared"`; the claimed `general` storage mapping is never checked.
    Stale comment or missing assertion (same family as F3-a/F6-b).
  - **(F8-b, what's-not-proven)** Heartbeat is a skeleton — every beat just returns `HEARTBEAT_OK`; no hooks/LLM/proactive
    work yet (M6). Proves the engine turns over, not that it does anything.
  - **(F8-c, crash-recovery posture — NEW, from owner's power-trip question)** Graceful cancellation is tested ✅ but
    **hard power-loss / SIGKILL is untested and untestable with fakes** (no cleanup runs). Intended protection =
    crash-safe storage (atomic SQLite/SQLCipher transactions + **append-only bitemporal** facts that can't clobber good
    rows) + LanceDB versioning + **launchd auto-restart** (ADR-002). Sharp edges to verify **on the Mini**: (a) SQLCipher
    + LanceDB survive a kill mid-write; (b) heartbeat resumes cleanly under launchd; (c) decide missed-tick **catch-up vs
    skip** for M6; (d) confirm GATE actions are **idempotent** across a crash (ties to the agent-loop-reliability
    invariant: idempotent · bounded · clean-state · externally-verified).

**Section 9 — `test_memory_bitemporal.py`: REVIEWED ✅** (owner: "oki"; explained the two-clocks/bitemporal
model). 33 tests across schema · cardinality (SINGLE/MULTI) · add+idempotency · update+bitemporal · tombstone/purge
· provenance · access-tracking · vector recall · episodic · edge-cases. Findings:
  - **(#1, strong)** "Never lose history" is actually tested — update closes-not-overwrites, tombstone keeps history,
    only purge truly deletes, DB physically forbids two current values (partial-unique index).
  - **(#2, good)** Idempotent re-ingest tested (same fact twice = no-op) → the property that makes crash-replay safe
    (answers the §8 power-trip question).
  - **(#3, good)** Dimension-lock enforced (wrong-sized vector rejected) → guards the locked Qwen3 @1024 decision.
  - **(F9-a, open-question unclosed)** Provenance only tests conversation-turn link (`source_turn_id`); the standing
    cross-store question (document-extracted fact → M3 source chunk?) is NOT covered here.
  - **(F9-b, contrast w/ F6-a)** This file's deterministic fake uses `sum(ord(c))` — stable across runs (the safe
    pattern); the F6-a fix should align the manifest fake to this.
  - **(F9-c, what's-not-proven)** Recall plumbing proven, ranking quality not (Alice vs Bob); real embeddings on Mini.
  - **(F9-d, known)** SQLCipher absent (plain sqlite; Tasks 1/3/5 Mini-gated) → encryption-at-rest + encrypted-store
    crash-safety unproven until the Mini.

**Section 10 — `test_model_auth.py`: REVIEWED ✅** (owner: "continue"). 4 tests: header present-when-key /
absent-when-no-key / client-carries-bearer / **bearer-on-wire** (MockTransport inspects actual transmitted header).
Findings:
  - **(#1, good)** On-the-wire test verifies transmitted bytes, not just internal state — a real test, not hollow.
  - **(#2, good security)** Absent-when-no-key explicitly tested (env-only `ARTEMIS_MODEL_API_KEY`; clean local-MLX calls).
  - **(F10-a, what's-not-proven)** Only the model adapter is wire-tested; the embedding adapter shares `_auth_headers`
    but has no equivalent on-the-wire test (low risk, shared helper).
  - **(F10-b, minor)** Async tests here have no explicit `@pytest.mark.asyncio` (rely on `asyncio_mode=auto`) —
    inconsistent with explicitly-marked async tests elsewhere.

### Video fit-eval — "5 Levels of an AI Second Brain" (PARKED, not filed; side-track 2026-06-18)
Owner shared the transcript mid-walkthrough. Verdict: **Artemis spans/exceeds all 5 levels** (L1 router→M1-a;
L2 wiki/auto-memory→M3+M4; L3 vector/hybrid/rerank→M3-a/b; L4 graph→M4-d entity backbone ADR-013; L5 always-on→M6+M7).
The video's admitted weakness (data ships to Anthropic, "not private") is exactly Artemis's local-first reason to exist.
**Three takeaways (awaiting owner's word to file):**
  - **(V-1) Whole-document & aggregate retrieval gap** — vector chunking fails "summarise the WHOLE doc" + "aggregate
    over a table" (the highest-sales example). M3-c agentic is still chunk-based + read-only; aggregates live in M8 spoke
    tables, but **faithful whole-document summarisation is a genuine M3 gap.** → flag M3 / BACKLOG.
  - **(V-2) Active knowledge elicitation ("grill me")** — interview-the-owner to populate memory. M7-c curiosity is
    web-grounded only; no owner-interview path to enrich M4. Natural for a voice-first assistant. → BACKLOG.
  - **(V-3, validation)** "Context vs Connections" (evergreen vs ephemeral; don't ingest volatile data, fetch live in a
    defined order) maps 1:1 onto Artemis's router→memory→knowledge→spoke chain + M4 decay + Gmail quarantine. Confirms
    design; could become an explicit one-line ingestion principle.

**Section 11 — `test_offline_compose.py`: REVIEWED ✅** (owner: "okay continue"). 2 tests: `compose_brain`
accepts fake embedder+model overrides; full Gateway request runs offline without raising. Findings:
  - **(#1, keystone)** This seam is *why all 121 tests run offline* — clean DI (`embedder=`/`model=`, default None →
    real adapters), backward-compatible.
  - **(F11-a, the 4 known mypy nits)** Fakes return `list[list[float]]` where ports expect `list[Sequence[float]]`
    (list-invariance) → widen fake return annotations; bundle with mypy-scope + F6-a fix.
  - **(F11-b, weak assert)** Test 2 only asserts `resp.text` truthy — liveness smoke test, not correctness.
  - **(F11-c, minor)** `_FakeModel.complete(**kwargs: Any)` loosely typed — won't catch signature drift.

**Section 12 — `test_vector_store.py`: REVIEWED ✅** (owner: "go ahead"; explained F12-a/b/c in depth).
9 tests: dense round-trip · **cosine contract pinned 1/0/−1** · FTS round-trip · FTS incremental-add ·
scope isolation (dense+FTS) · dimension-lock on write · dimension-lock on reopen · invalid-scope rejected ·
empty-store. Findings:
  - **(#1, strong)** Cosine contract pinned numerically — locks score semantics for downstream RRF (M3-b).
  - **(#2, good security)** Scope isolation tested for both dense + FTS (no cross-zone leak); `invalid-scope`
    is a real injection guard — the same charset/validation discipline **F2-a** wants, already present here.
  - **(#3, good)** Dimension-lock on write *and* reopen (the reopen case = model-swap corruption guard).
  - **(F12-a, 10 known mypy nits)** Test fns omit `tmp_path: Path` (`no-untyped-def`) → annotate; bundle with fix-queue.
  - **(F12-b, what's-not-proven)** FTS tests `pytest.skip()` when native FTS missing → green bar can hide untested
    FTS; assert FTS is live on the Mini. Also reaches into private `_fts_ok`.
  - **(F12-c, what's-not-proven)** One-hot vectors prove metric + plumbing, not real ranking quality (family of F7-b/F9-c).

## ✅ COMPLETE — all 12 sections reviewed; synthesised 2026-06-18
**Synthesis written to `docs/findings/prebuild-test-review-findings.md`** (durable home), with three buckets:
1. **Fix-queue** (~15-min DeepSeek): mypy-scope root + F6-a flaky · F11-a/F12-a annotations · F3-a/F6-b hollow
   asserts · F5-a/F7-a/F10-b cosmetics. Ready to promote to a `docs/changes/fix-validation-test-quality.md` spec on owner's word.
2. **Mini-verification checklist:** F7-b/F9-c/F12-c ranking quality · F12-b FTS-live · F9-d SQLCipher+crash-safety ·
   F8-c power-loss posture · F4-a `/readyz` · live token streaming.
3. **Design follow-ups:** F2-a guest-prefix · F2-b error surfacing · F9-a cross-store provenance · F8-a/F8-b ·
   **V-1 whole-doc/aggregate** + **V-2 grill-me elicitation** → both filed to `BACKLOG.md` 2026-06-18 (V-3 = validation only).

The draft above holds the per-section owner commentary; the findings doc is the actionable synthesis.
