---
spec: sens-enforce-ragcompose
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
depends_on: sens-carry-m3b, sens-carry-m4c1
---
<!-- ADR-029 §3 (enforcer) — the missing call-site + the FIRST spec that assembles the full cloud-bound
     prompt (request + retrieved chunks + recalled facts). Risk R2: this is genuinely new corpus surface;
     built INTEGRALLY so the privacy wall exists from the first line and is never retrofitted onto a live
     retrieval path. Enforcer extends sensitivity.py (the one home: classifier + router + enforcer).
     cross_model_review: true (privacy wall — a false-negative leaks owner data to cloud). -->

# Spec: SENS-enforce-ragcompose — RAG-compose-with-gate (assemble → enforce → route) + per-item held-back surface + one-time inline release + audit

**Identity:** The RAG-compose seam: retrieve (M3-b) + recall (M4-c-1) → assemble the cloud-bound context → run the `SensitivityEnforcer` (filter sensitive items out of the cloud prompt; if the request itself is sensitive, whole turn local) → route to `responder`/`responder_cloud`. Surfaces held-back items per-item, offers a one-time inline release, and writes every release to the audit log. The enforcer is added to `sensitivity.py` (one home with the classifier + conversation gate).
→ why: see docs/technical/adr/ADR-029-sensitivity-ingestion-gate.md §3 (enforcer + posture) · brain-sensitivity-routing (the conversation gate this composes with).

## Assumptions

- **SENS-carry-M3b** + **SENS-carry-M4c1** complete: `RetrievedChunk.chunk.sensitivity` and `Fact.sensitivity` (both `Literal["general","sensitive"]`, fail-closed) are populated. The enforcer reads `chunk.sensitivity` / `fact.sensitivity` on every assembled item. → impact: Stop (the enforcer's input contract is the tagged chunk/fact; an untagged item is `"sensitive"` by the carriers' fail-closed default).
- **brain-sensitivity-routing** complete: `src/artemis/sensitivity.py` defines `SensitivityClassifier` (loopback-guarded, fail-closed, `async def classify(request_text) -> Sensitivity`), `Sensitivity = Literal["general","sensitive"]`, `SensitivityClassifierProtocol`. The `Brain` has `_responder_role(request_text)` choosing `responder`/`responder_cloud` from the request classification + the `cloud_reasoning_enabled` kill-switch. This spec EXTENDS `sensitivity.py` (adds the enforcer alongside the classifier — one home) and composes the enforcer with `_responder_role`. → impact: Stop (do not create a second sensitivity module; the enforcer lives in `sensitivity.py`).
- **M3-b** `AdaptiveRetriever.retrieve(query, scope, mode, k) -> list[RetrievedChunk]` (async) and **M4-c-1** `MemoryStore.inject_context(person_id, token_budget, as_of) -> list[Fact]` / `recall(...) -> list[Fact]` (async) are the two context sources. The Brain currently injects ONLY the recalled inject-block on the local path (M4-c-1) and does NOT yet wire `retrieve` into the responder prompt — **the RAG-compose step is unspecced (ADR-029's own finding). This spec DEFINES that seam.** It is net-new corpus surface, not a fiction. → impact: Stop (the assemble→enforce→route stages are new; the Brain gains a `compose_with_gate` path for queries that pull retrieved context).
- **Release is inline + audited, NOT GATE staging** (ADR-029, load-bearing): the held-back items are offered inline ("say 'include the medical email' to redo"); the owner acts only to get the fuller answer; releases do NOT go through `ActionStagingService`/`PendingActionStore` (ADR-012) — a blocking approval per sensitive-context hit is too heavy for a single-owner appliance. Every release is written to an audit log. Release is **one-time per query** — it never silently re-tags the item as `general` (a future "always allow this source" is reserved, not built). → impact: Stop (do not wire GATE; do not persist a re-tag; one-time release only).
- The audit log is an injected thin seam: `audit_log: Callable[[ReleaseAuditEntry], None]` (sync — a local append, mirroring the SQLCipher-write-stays-sync rule). The Brain composition root supplies it (a SQLCipher append-only log, the same family as CAL-b's `ActivityLog.record` but enforcer-scoped). This spec defines `ReleaseAuditEntry` + the seam; the concrete store is wired at composition (a `FakeAuditLog` records calls in tests). → impact: Caution (do not couple to CAL-b's `WriteResult`-typed log; define a `ReleaseAuditEntry` of the enforcer's own shape).
- Off-hardware: fully testable with a `FakeSensitivityClassifier` (returns a configured request label), hand-built tagged `RetrievedChunk`/`Fact` lists, and a `FakeAuditLog`. End-to-end against real Ollama is dev-box-buildable (the classifier reuses the small local model). → impact: Low.

Simplicity check: considered a separate `rag_compose.py` module — rejected; ADR-029 locks `sensitivity.py` as the one home (classifier + router + enforcer compose tightly and share the `Sensitivity` vocabulary + the fail-closed posture). Considered routing release through GATE — rejected by ADR-029 (too heavy). The minimal enforcer is: classify the request (reuse), partition assembled items by tag, filter sensitive-from-cloud, return a decision object the Brain acts on. No new persistence beyond the audit seam.

## Prerequisites

- Specs complete: **SENS-carry-M3b**, **SENS-carry-M4c1**, **brain-sensitivity-routing**, **M3-b** (`retrieve`), **M4-c-1** (`recall`/`inject_context` + the Brain turn loop).
- Environment: no new PyPI deps. Dev-box-buildable end-to-end against Ollama; off-hardware fakes.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/sensitivity.py` | modify | add `HeldBackItem`, `ReleaseAuditEntry`, `ComposedContext`, `GateDecision`, `SensitivityEnforcer` (the enforcer class) + `compose_with_gate(...)` |
| `/Users/artemis-build/artemis/src/artemis/brain.py` | modify | wire `compose_with_gate` into the RAG path: assemble retrieved+recalled → enforcer → route responder/responder_cloud; surface held-back; handle one-time release re-compose |
| `/Users/artemis-build/artemis/src/artemis/gateway.py` | modify | construct the enforcer + audit-log seam on the real path; pass them into `Brain` |
| `/Users/artemis-build/artemis/tests/test_sensitivity_enforcer.py` | create | partition/filter, request-sensitive-whole-turn-local, held-back surface, one-time release + audit, fail-closed-on-untagged, kill-switch |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Define the enforcer types + `SensitivityEnforcer`** — files: `/Users/artemis-build/artemis/src/artemis/sensitivity.py` (modify, additive) —

  Add (all Pydantic v2 `model_config = ConfigDict(frozen=True)` or frozen dataclasses; no model/ntfy imports):

  ```python
  @dataclass(frozen=True)
  class HeldBackItem:
      kind: Literal["chunk", "fact"]
      ref_id: str                # chunk_id or fact_id — the stable id used to release it
      label: str                 # a short owner-facing descriptor (e.g. "medical email", "journal note");
                                 # derived from category if present, else a generic "private item" —
                                 # NEVER the raw content (privacy: the held-back surface lists WHAT was held,
                                 # not the sensitive text itself)
      category: str | None

  @dataclass(frozen=True)
  class ReleaseAuditEntry:
      query_id: str
      ref_id: str
      kind: Literal["chunk", "fact"]
      released_at: str           # ISO-8601 UTC
      category: str | None

  @dataclass(frozen=True)
  class ComposedContext:
      cloud_safe_chunks: tuple[RetrievedChunk, ...]   # general items → may go to cloud
      cloud_safe_facts: tuple[Fact, ...]
      held_back: tuple[HeldBackItem, ...]             # filtered-out sensitive items (surfaced per-item)
      request_sensitive: bool                         # the request itself classified sensitive

  @dataclass(frozen=True)
  class GateDecision:
      role: str                          # "responder" (local) or "responder_cloud"
      context: ComposedContext           # what survived the filter (what the prompt is built from)
  ```

  `class SensitivityEnforcer` constructed with `(classifier: SensitivityClassifierProtocol | None, *, cloud_reasoning_enabled: bool = True)`:

  ```python
  async def enforce(
      self,
      *,
      request_text: str,
      chunks: Sequence[RetrievedChunk],
      facts: Sequence[Fact],
      released_ref_ids: frozenset[str] = frozenset(),   # one-time release set for THIS query (Task 3)
  ) -> GateDecision:
  ```
  Logic (fail-closed at every layer — ADR-029):
  1. **Request classification (reuse the conversation gate):** if `not cloud_reasoning_enabled` or `classifier is None` → `request_sensitive = True` (kill-switch / no classifier → whole turn local). Else `request_sensitive = (await classifier.classify(request_text)) == "sensitive"`; on any exception → `request_sensitive = True` (fail-closed).
  2. **If `request_sensitive`:** the whole turn stays local — `role = "responder"`. ALL context (sensitive AND general) may go into the LOCAL prompt (local handling is the point of the hybrid). `held_back = ()` (nothing is held from a local prompt — held-back only applies to a cloud-bound prompt). Return `GateDecision(role="responder", context=ComposedContext(cloud_safe_chunks=tuple(chunks), cloud_safe_facts=tuple(facts), held_back=(), request_sensitive=True))`.
  3. **Else (request general):** partition each chunk/fact by its `sensitivity`. An item is cloud-safe iff `item.sensitivity == "general"` OR `item.ref_id in released_ref_ids` (one-time release). A sensitive, non-released item → a `HeldBackItem` (kind, ref_id=chunk_id/fact_id, label from `category` or `"private item"`, category). If `held_back` is non-empty, `role` stays `"responder_cloud"` (cloud answers on the general remainder + any released items) — UNLESS every item was held AND the policy is whole-turn-local-on-any-sensitive… but ADR-029 chose FILTER-by-default (cloud answers on the general remainder), so `role = "responder_cloud"` whenever the request is general. Return the `GateDecision` with the cloud-safe partition + the held-back list.

  **Fail-closed invariant (inline comment + assert):** a chunk/fact with `sensitivity == "sensitive"` and `ref_id not in released_ref_ids` is NEVER in `cloud_safe_*`. Add an inline assertion at the end of the general branch: `assert all(c.chunk.sensitivity == "general" or c.chunk.chunk_id in released_ref_ids for c in cloud_safe_chunks)` (and the fact analogue).

  — done when: `uv run mypy --strict src` passes; a general request with a mix of general + sensitive chunks → `cloud_safe_chunks` has only the general ones (+ released), `held_back` lists the sensitive ones, `role == "responder_cloud"`; a sensitive request → `role == "responder"`, `held_back == ()`, all items in `cloud_safe_*` (local prompt); `cloud_reasoning_enabled=False` → `role == "responder"`; an untagged (fail-closed `"sensitive"`) chunk in a general request is held back.

- [ ] **Task 2: `compose_with_gate` — the assemble→enforce→route seam** — files: `/Users/artemis-build/artemis/src/artemis/sensitivity.py` (modify) —

  ```python
  async def compose_with_gate(
      *,
      request_text: str,
      query_id: str,
      retrieve_fn: Callable[[str], Awaitable[list[RetrievedChunk]]],   # bound AdaptiveRetriever.retrieve(query, scope, ...)
      recall_fn: Callable[[], Awaitable[list[Fact]]],                  # bound MemoryStore.inject_context / recall
      enforcer: SensitivityEnforcer,
      released_ref_ids: frozenset[str] = frozenset(),
      audit_log: Callable[[ReleaseAuditEntry], None] | None = None,
  ) -> GateDecision:
      """Assemble retrieved + recalled context, run the enforcer, return the routing decision.
      The Brain builds the prompt from decision.context and calls model.complete(role=decision.role).
      Releases (released_ref_ids that were actually applied this turn) are audit-logged here."""
  ```
  Steps:
  1. `chunks = await retrieve_fn(request_text)` (degrade-don't-crash: on exception → `chunks = []`, log a warning — a retrieval failure must not crash the turn).
  2. `facts = await recall_fn()` (same degrade).
  3. `decision = await enforcer.enforce(request_text=request_text, chunks=chunks, facts=facts, released_ref_ids=released_ref_ids)`.
  4. **Audit releases:** for each `ref_id` in `released_ref_ids` that corresponds to an item that WAS sensitive (i.e. an item the enforcer would otherwise have held), if `audit_log` is set, call `audit_log(ReleaseAuditEntry(query_id=query_id, ref_id=ref_id, kind=..., released_at=now_iso(), category=...))`. (Determine the kind/category by matching `ref_id` against the assembled chunks/facts before the filter.)
  5. Return `decision`.

  — done when: `uv run mypy --strict src` passes; `compose_with_gate` returns the enforcer's decision; a retrieval/recall exception degrades to an empty list without raising; a `released_ref_id` for a previously-sensitive item triggers exactly one `audit_log` call with the correct `kind`/`category`.

- [ ] **Task 3: Wire into the Brain RAG path + one-time release** — files: `/Users/artemis-build/artemis/src/artemis/brain.py` (modify) —

  Add a RAG-compose path the Brain uses when a query pulls retrieved context (the free-form/local responder path, extending M4-c-1's inject wiring):
  1. The Brain gains `enforcer: SensitivityEnforcer | None`, `retrieve_fn`/`recall_fn` seams (bound at composition; `None` ⇒ no RAG context, fall back to M4-c-1's local-inject-only behaviour — no regression), and `audit_log`.
  2. On a turn that composes context: `decision = await compose_with_gate(request_text=..., query_id=<turn id>, retrieve_fn=..., recall_fn=..., enforcer=enforcer, released_ref_ids=<from this turn's release state>, audit_log=audit_log)`. Build the responder prompt from `decision.context` (the cloud-safe chunks + facts rendered into the prompt; the inject-block render from M4-c-1 is reused for facts). Call `await self._model.complete(role=decision.role, messages=...)`.
  3. **Surface held-back per-item:** if `decision.context.held_back` is non-empty, the Brain's response carries the held-back list to the client (a `held_back: list[HeldBackItem]` field on `BrainResponse`, defaulted `[]` — additive, no regression). The client renders the "held back / include & redo" chip row (Wave U / CLIENT-ask, U10). The answer text notes it is filtered.
  4. **One-time release (re-compose):** when the owner says "include the medical email", the gateway/client maps the held-back item's `ref_id` into `released_ref_ids` and re-issues the SAME query with that set. `compose_with_gate` then includes that item in the cloud-safe partition for THIS query only and audit-logs the release. The release set is NOT persisted (one-time; a future "always allow this source" is reserved, not built). Document the release-mapping as the client/gateway's responsibility (the Brain accepts `released_ref_ids` per-turn).
  5. **If `decision.request_sensitive`:** the whole turn is `role="responder"` (local) — the held-back list is empty (a local prompt holds nothing back). No cloud egress.

  Guard the whole RAG-compose path with try/except → on failure, degrade to the existing M4-c-1 local-inject behaviour (a compose failure must never break the turn or leak).

  — done when: `uv run mypy --strict src` passes; a Brain with no enforcer behaves exactly as M4-c-1 (no regression); a Brain with the enforcer on a general request + a sensitive chunk routes `responder_cloud` with the sensitive chunk held back + surfaced on `BrainResponse.held_back`; re-issuing with `released_ref_ids={that chunk_id}` includes it (cloud) and audit-logs once; a sensitive request routes `responder` with no held-back.

- [ ] **Task 4: Gateway wiring** — files: `/Users/artemis-build/artemis/src/artemis/gateway.py` (modify) —

  On the real-port path (`model is None`, mirroring brain-sensitivity-routing's pattern): construct `SensitivityEnforcer(SensitivityClassifier(OpenAIModelPort(settings), settings), cloud_reasoning_enabled=settings.cloud_reasoning_enabled)`, a concrete SQLCipher-backed `audit_log` (append-only `ReleaseAuditEntry` log under the owner scope), and bind `retrieve_fn`/`recall_fn` from the composed `AdaptiveRetriever` + `MemoryStore`. Pass them into `Brain`. On the injected/test/offline path, pass `enforcer=None` (no RAG gate; M4-c-1 behaviour). Reuse the existing `SensitivityClassifier` instance from brain-sensitivity-routing rather than constructing a second (the classifier is shared across the conversation gate + the enforcer — one resident model).

  — done when: `uv run mypy --strict src` passes; `compose_brain(settings)` builds a `Brain` with the enforcer on the real path; an injected-model `compose_brain` builds with `enforcer=None`; the classifier is constructed once and shared.

- [ ] **Task 5: Tests** — files: `/Users/artemis-build/artemis/tests/test_sensitivity_enforcer.py` — typed pytest. Fakes: `FakeSensitivityClassifier` (`async def classify` → configured label), hand-built tagged `RetrievedChunk`/`Fact` lists, `FakeAuditLog` (records `ReleaseAuditEntry` calls). All enforcer/compose calls are `async def` tests under the project async convention.

  - **General request, mixed context → filter:** request `"general"`; chunks = [general A, sensitive B], facts = [general F1, sensitive F2]. `enforce(...)` → `cloud_safe_chunks == (A,)`, `cloud_safe_facts == (F1,)`, `held_back` lists B + F2 (kind/ref_id/category correct), `role == "responder_cloud"`, `request_sensitive is False`.
  - **Sensitive request → whole turn local:** request `"sensitive"` → `role == "responder"`, `held_back == ()`, ALL chunks+facts in `cloud_safe_*` (local prompt), `request_sensitive is True`.
  - **Kill-switch:** `SensitivityEnforcer(classifier, cloud_reasoning_enabled=False)` → `role == "responder"` regardless of request; classifier NOT called (assert call count 0).
  - **No classifier:** `SensitivityEnforcer(None)` → `role == "responder"` (fail-closed).
  - **Classifier raises → fail-closed:** `FakeSensitivityClassifier` set to raise → `request_sensitive is True`, `role == "responder"`.
  - **Fail-closed on untagged item:** a general request with a chunk whose `sensitivity == "sensitive"` (the carrier fail-closed default) → that chunk is held back, never cloud-safe.
  - **One-time release:** general request with sensitive chunk B; `enforce(..., released_ref_ids={B.chunk_id})` → B is now in `cloud_safe_chunks`, NOT in `held_back`.
  - **Release is audited:** `compose_with_gate(..., released_ref_ids={B.chunk_id}, audit_log=fake)` → `fake.entries` has exactly one `ReleaseAuditEntry` with `ref_id == B.chunk_id`, `kind == "chunk"`, correct `category`, ISO `released_at`. A release of an ALREADY-general item is NOT audited (only previously-sensitive releases are logged).
  - **Held-back label carries no raw content:** assert `HeldBackItem.label` is derived from `category`/generic, and does NOT equal the chunk text (privacy — the surface lists what, not the content).
  - **compose degrade:** `retrieve_fn`/`recall_fn` raising → `compose_with_gate` returns a decision with empty context, does not raise.
  - **fail-closed assertion holds:** the `assert all(... general or released ...)` never trips across all cases.

  — done when: `uv run pytest -q tests/test_sensitivity_enforcer.py` passes AND `uv run mypy --strict src tests/test_sensitivity_enforcer.py` passes.

- [ ] **Task 6 (GATED — on-hardware / dev-box-Ollama-eligible):** End-to-end against real Ollama: ingest a general doc + a sensitive (health) doc via M3-a (tagged by SENS-prod-M3a); a general query that retrieves both → the enforcer holds the sensitive chunk out of the cloud prompt, the cloud (Codex/responder_cloud) answers on the general remainder, the held-back item is surfaced; an inline release re-runs with the sensitive chunk included and writes one audit entry; a sensitive query keeps the whole turn local (`responder`, no cloud egress — confirm via `ModelResponse.origin == "local"`). — done when: recorded in handoff. (This is dev-box-buildable — the only Mac-gated tail is the distilled `sensitive_reasoner` quality upgrade, NOT this gate's logic.)

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/sensitivity.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/brain.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/gateway.py` |
| Create | `/Users/artemis-build/artemis/tests/test_sensitivity_enforcer.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_sensitivity_enforcer.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_sensitivity_enforcer.py tests/test_brain_routing.py` | Test gate (enforcer + conversation-gate regression) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/sensitivity.py`, `src/artemis/brain.py`, `src/artemis/gateway.py`, `tests/test_sensitivity_enforcer.py` |
| `git commit` | `"feat: ADR-029 enforcer — RAG-compose-with-gate (assemble→enforce→route) + held-back surface + one-time release + audit"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings (classifier role, cloud_reasoning_enabled, scope_dir for the audit log) |

### Network
| Action | Purpose |
|--------|---------|
| local `127.0.0.1` to the local served model (GATED) | request classification (reuses the conversation-gate classifier) |
| Codex/cloud egress (GATED) | `responder_cloud` answers on the FILTERED (general-only) context |

## Specialist Context

### Security

**This is the privacy wall — a false-negative leaks owner data to the cloud unrecoverably. Load-bearing invariants:**
1. **Fail-closed at every layer:** request classifier failure / kill-switch off / no classifier → whole turn local. An untagged context item (carrier fail-closed default `"sensitive"`) → held back. The `assert all(general-or-released)` on `cloud_safe_*` is a structural guard that no sensitive item reaches the cloud prompt.
2. **The enforcer covers ALL THREE cloud-bound prompt terms** (request + retrieved chunks + recalled facts) — ADR-029's whole point. The conversation gate (brain-sensitivity-routing) covered term 1 only; this closes terms 2+3. There is never a window where retrieval reaches the cloud ungated because the wall is built integrally with the RAG-compose seam (R2 mitigation).
3. **Release is inline + audited, never a silent re-tag:** a release applies for ONE query (`released_ref_ids` is per-turn, not persisted) and is written to the audit log. It does NOT go through GATE staging (ADR-029 rejects the blocking gate for this). A future "always allow this source" persistent re-tag is reserved, not built.
4. **Held-back surface carries no raw sensitive content:** `HeldBackItem.label` is a category-derived descriptor ("medical email"), NOT the chunk/fact text. The owner sees WHAT was held, not the sensitive text, until they explicitly release.
5. **No fact/chunk plaintext logged at info:** the enforcer logs counts + ref_ids + the audit entry (category label), never the content (consistent with M3-b/M4-c-1).

[apex-security review: the load-bearing line is the general-branch partition — confirm no code path puts a `sensitivity=="sensitive"` non-released item into `cloud_safe_*`. The classifier reuse means one resident model (not a second). Confirm the audit log is append-only and owner-scoped. cross_model_review covers the privacy-wall correctness.]

### Performance

- One request-classification local call per turn (reused from the conversation gate — not an extra model). Partitioning is O(chunks + facts) string-label comparisons — free. Retrieval/recall are the existing M3-b/M4-c-1 costs. The cloud call runs on the FILTERED (smaller) context — strictly cheaper than unfiltered.

### Accessibility

(none — the held-back chip row + "include & redo" UI is Wave U / CLIENT-ask, U10; this spec only produces the `held_back` data the client renders)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/sensitivity.py` | Document the three-stage assemble→enforce→route flow; the fail-closed partition; the filter-by-default + per-item-surface + one-time-inline-release + audit posture (ADR-029 §3); the one-home rationale (classifier + router + enforcer) |
| Inline | `src/artemis/brain.py` | Document the RAG-compose path, the `held_back` surface on `BrainResponse`, and the per-turn `released_ref_ids` one-time-release contract |
| ADR | `docs/technical/adr/ADR-029-sensitivity-ingestion-gate.md` | Mark the enforcer seam as built (reconcile at execution) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_sensitivity_enforcer.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_sensitivity_enforcer.py tests/test_brain_routing.py` → verify: general request filters sensitive items from cloud + surfaces held-back + routes `responder_cloud`; sensitive request → whole turn `responder` (no held-back); kill-switch/no-classifier/classifier-raises → `responder`; untagged item fail-closed held back; one-time release includes the item + audits exactly once; held-back label carries no raw content; compose degrades on retrieve/recall failure; conversation-gate regression (`test_brain_routing.py`) green.
- [ ] `uv run python -c "from artemis.sensitivity import SensitivityEnforcer, compose_with_gate, HeldBackItem, GateDecision, ReleaseAuditEntry; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, dev-box Ollama or Mini) end-to-end: general query holds a sensitive chunk out of the cloud prompt, cloud answers on the remainder, inline release re-includes + audits once, sensitive query stays local (`ModelResponse.origin == "local"`) → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
