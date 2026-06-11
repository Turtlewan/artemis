---
spec: m8-d-c2-capture-integration
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seams 3, 5, 6) + m8-productivity.md BLOCKs B1, B5, B6, B7, F1/F13 -->
<!-- Seam 3: no gated tools in this spec (capture + knowledge push are auto/internal); no staging
     service calls needed. Seam 5: no hooks here; payload safety already enforced. Seam 6: GOAL entity
     creation deferred — see note at Task 6 below.
     B1 fix: manifest signature stated cumulatively; tool count is relative.
     B5 fix: Recipe.provenance field dropped (does not exist in M7-a1); origin encoded in description.
     B6 fix: temp file written under scope_dir staging subdir, not /tmp.
     B7 fix: graduation guard checks all statuses (not just CANDIDATE); never re-writes if any recipe
     for the key exists.
     F1/F13 fix: exactly ONE CaptureService definition (Task 4 canonical fields); "Wait — simpler approach"
     self-revision narration removed; commitment_shape stored in dedicated column (U7) not notes field. -->

# Spec: M8-d-c2 — Productivity capture + knowledge/memory integration

**Identity:** `CaptureService` (commitment detection → inert `suggestions` row; email via DR-a `QuarantinedReader`), capture-recipe graduation (repeated `accept_suggestion` → `Promoter.note_occurrence` → `RecipeStore.write(CANDIDATE)` → M7-b Review), and knowledge/memory push on project completion (`IngestPipeline.ingest` + `MemoryWriteQueue.enqueue`).
→ why: see docs/technical/modules/productivity.md §G (capture) · §H (knowledge/memory) · docs/technical/adr/ADR-012-gated-action-staging.md (recurrence→recipe bridge) · docs/technical/adr/ADR-009-untrusted-content-and-deep-research.md (quarantine for email capture)

<!-- Split note: TWO logical phases (1: capture service + graduation; 2: knowledge/memory push). Total src files = capture.py (create) + tools.py (modify) + hooks.py (modify, thin call-site addition). This is at the 2-phase limit; phases share the `accept_suggestion` seam and the same test file, so splitting would leave phase 1 untestable without the project-complete trigger. Kept together. If review wants leaner: split into M8-d-c2a (capture+graduation) and M8-d-c2b (knowledge+memory). -->

## Assumptions

- **M8-d-a** complete: `ProductivityRepository.create_suggestion`, `accept_suggestion`, `list_suggestions`, `reject_suggestion` (the suggestions table with `source`, `status`, `raw_context`, `notes`, **`commitment_shape TEXT`** columns — U7 fix: `commitment_shape` is a dedicated column, not a notes prefix) + `ProductivityStore` + `ProductivityRepository.complete_task` and `archive_project` are all importable. `get_suggestion(id)` may need to be added (conditional modify per Files to Change). → impact: Stop.
- **M8-d-c1** complete: `hooks.py` exists at `src/artemis/modules/productivity/hooks.py`; `build_productivity_hooks` is importable. This spec adds `CaptureService` wiring to the same module — it DOES NOT modify `hooks.py` unless a `make_capture_check` factory is needed (no proactive capture hook is in scope per §E — capture is reactive only). → impact: Caution (c1 must exist before this spec so import paths are stable; no hook changes required).
- **DR-a** complete: `QuarantinedReader`, `Extract`, `EXTRACTION_SCHEMA` importable from `artemis.untrusted`. The `FakeModelPort` + `FakeQuarantinedReader` pattern mirrors DR-a's test approach. → impact: Stop (email capture MUST route through quarantine before any LLM-generative step; this is load-bearing).
- **M3-a** complete: `IngestPipeline.ingest(source: Source) -> IngestResult` importable from `artemis.ingest.pipeline`; `Source(kind, uri, scope)` from `artemis.ingest.connectors`; `ScopeLockedError` propagates from the unlocked-volume precondition. → impact: Stop (project-complete knowledge push calls this exactly).
- **M4-b** complete: `MemoryWriteQueue.enqueue(text: str, turn_id: str) -> None` importable from `artemis.memory`; `build_write_path` factory available. → impact: Stop (standing-fact memory push calls this).
- **M7-a1** complete: `Recipe`, `RecipeClass`, `ActionClass`, `RecipeStatus`, `RecipeStore` importable from `artemis.recipes`. `RecipeStore.write(recipe: Recipe)` signs + upserts. → impact: Stop (graduation step writes a `CANDIDATE` recipe via this).
- **M7-b** complete: `Promoter.note_occurrence(task_class_key: str)`, `RecurrenceStore` importable from `artemis.recipes.promotion`. `classify_safety` on a `TOUCHES_DATA` recipe returns `"gated"` → `Promoter` moves it to `PENDING`, never auto-enables. `ReviewSurface` surfaces it; owner calls `approve`. → impact: Stop (the gated promotion path is load-bearing).
- The `capture_pattern_key` (the graduation identity) is defined as `f"{source_class}:{commitment_shape}"` where `source_class` is the coarse source bucket (`"email"`, `"chat"`, `"calendar"`) and `commitment_shape` is the normalized commitment verb/category (e.g. `"will_send"`, `"will_call"`, `"meeting_follow_up"`) extracted by the detection step. Paraphrases collapse onto the same key so recurrence counts accumulate. Full normalisation rules in Task 3 below. → impact: Caution (if the normalisation produces too many unique keys, threshold N≥2 never fires; the FakeModelPort fixture is designed to reproduce the same shape key).
- The commitment detection (constraint extraction: "is this a commitment? → {title, due?}") runs via the `sensitive_reasoner` `ModelPort` role with a `response_schema` (DR-a `EXTRACTION_SCHEMA`-style constrained decode), NOT the cloud teacher. Email paths run through `QuarantinedReader` FIRST; the extraction runs on the `Extract.summary`/`Extract.claims` from the quarantined reader, never on raw email text. → impact: Stop (security invariant: raw mail never enters the extraction model directly).
- Off-hardware: `FakeModelPort` (deterministic — returns a fixed `{is_commitment: true, title: "...", due: null, commitment_shape: "will_send"}` JSON for test inputs); `FakeQuarantinedReader` (returns a canned `Extract`); `FakeRecipeStore`; `FakeRecurrenceStore`; `FakeIngestPipeline`; `FakeMemoryWriteQueue`; `ProductivityRepository` over a temp SQLCipher (or plain-sqlite fallback). Real served model is GATED. → impact: Caution (same pattern as M8-d-a/c1).
- `CaptureService` does NOT expose any brain tool directly (it is an internal service wired at composition; `suggestion_accept` in `tools.py` is the brain-facing seam that wraps the combined accept + graduation). → impact: Low.

Simplicity check: considered making `CaptureService.suggest_from_text` do both detection AND graduation in one step — rejected; the suggestion is inert until `accept_suggestion` is called (§G invariant), so graduation can only fire at accept time. The detection step is minimal (constrained decode to `{is_commitment, title, due, commitment_shape}`); no multi-step reasoning. This is the minimum faithful §G implementation.

## Prerequisites

- Specs complete: **M8-d-a** (suggestions table + `accept_suggestion`), **M8-d-c1** (hooks.py exists), **DR-a** (`QuarantinedReader`), **M3-a** (`IngestPipeline`), **M4-b** (`MemoryWriteQueue`), **M7-a1** (`Recipe`/`RecipeStore`), **M7-b** (`Promoter`/`RecurrenceStore`/`ReviewSurface`).
- Environment: no new PyPI deps. `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/capture.py` | create | `CaptureService`: `suggest_from_text` (detection + quarantine gate) + `accept_with_graduation` (graduation logic) + `build_capture_pattern_key` normaliser |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` | modify | SURGICAL: wrap `suggestion_accept` callable to call `capture_service.accept_with_graduation` instead of bare `store.accept_suggestion`; wire `project_complete` / `project_archive` to call `_push_knowledge` (IngestPipeline + MemoryWriteQueue) |
| `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` | modify | SURGICAL: add `CaptureService`, `IngestPipeline`, `MemoryWriteQueue` injected params to `productivity_manifest(...)` signature; call `init_capture(capture_service, ingest_pipeline, memory_queue)` |
| `/Users/artemis-build/artemis/tests/test_productivity_capture.py` | create | off-hardware: detect+suggest round-trip (trusted + email quarantine gate), graduation seam (note_occurrence → CANDIDATE written), knowledge/memory push on project complete |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

### Phase 1 — CaptureService: detection + quarantine + inert suggestion

- [ ] **Task 1: Define the commitment detection schema and FakeModelPort** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/capture.py` —

  At top of file define:

  ```python
  COMMITMENT_SCHEMA: dict[str, object] = {
      "type": "object",
      "required": ["is_commitment", "title", "commitment_shape"],
      "properties": {
          "is_commitment": {"type": "boolean"},
          "title": {"type": "string", "maxLength": 200},
          "due": {"type": ["string", "null"], "description": "ISO date or null"},
          "commitment_shape": {
              "type": "string",
              "enum": [
                  "will_send", "will_call", "will_meet", "will_pay",
                  "will_review", "will_schedule", "will_complete", "other"
              ]
          }
      },
      "additionalProperties": False
  }
  ```

  `commitment_shape` is the vocabulary that drives `capture_pattern_key` normalisation. The enum collapses paraphrases ("I'll send", "sending it", "will forward" → all `"will_send"`). This is the detection model's bounded output.

  Define `class FakeCommitmentDetector` (TEST only — do NOT import in prod): deterministic — maps substrings like `"send"` → `will_send`, `"call"` → `will_call`, returns `is_commitment=True` with a stable `title` for any non-empty text; `"not a task"` → `is_commitment=False`. Used in tests to avoid a model call.

  — done when: `uv run mypy --strict src` passes; `COMMITMENT_SCHEMA` is a valid JSON Schema (assert via `jsonschema.validate({...}, COMMITMENT_SCHEMA)` in tests).

- [ ] **Task 2: Implement `suggest_from_text` with quarantine gate** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/capture.py` —

  `CaptureService` is defined ONCE in Task 4 (canonical, all six fields). **Do not add a `@dataclass class CaptureService` block here.** (F13 fix: a second definition in Task 2 was present in an earlier draft and has been removed.) Implement only `suggest_from_text` as a method of the class that will be defined in Task 4.

  `async def suggest_from_text(self, source: Literal["chat", "email", "calendar"], text: str, *, untrusted: bool = False) -> str | None`:

  1. If `untrusted` is True (email paths): `self.quarantine` MUST be set (raise `ValueError("quarantine required for untrusted source")`). Call `extract = await self.quarantine.read(raw_content=text, source_url="", source_domain="email", query="task commitments")`. If `extract.parse_failed` → log a WARNING and return `None` (degrade-don't-crash). The detection LLM receives `extract.summary`, never `text`.
  2. If `untrusted` is False (chat, calendar): run detection directly on `text` (trusted, owner-authored).
  3. Detection: `detection_input = extract.summary if untrusted else text`. Call `resp = await self.model.complete(role=self.role, messages=[{"role":"system","content":"Extract task commitments from the following text. Respond in JSON."},{"role":"user","content":detection_input}], response_schema=COMMITMENT_SCHEMA)`. Parse `resp.text` as JSON. If parse error or `is_commitment == False` → return `None`.
  4. Extract `commitment_shape = detected.get("commitment_shape", "other")`. Call `suggestion_id = self.store.create_suggestion(title=detected["title"], notes=None, source=source, raw_context=None, commitment_shape=commitment_shape)` — **U7 fix: `commitment_shape` is stored in its own dedicated column (added to `suggestions` schema in M8-d-a Task 1 as `commitment_shape TEXT`), NOT encoded in the `notes` field.** `raw_context` is deliberately `None`. Return `suggestion_id`.

  **Schema note (U7):** M8-d-a's `suggestions` table must include `commitment_shape TEXT` column (add to the DDL in M8-d-a Task 1). `ProductivityRepository.create_suggestion` must accept and write the `commitment_shape` kwarg.

  **Security invariant (inline comment):** `# SECURITY: raw email text (the text arg when untrusted=True) is NEVER passed to store.create_suggestion or to the extraction model. Only Extract.summary reaches the detection model. raw_context is always None.`

  — done when: `uv run mypy --strict src` passes; `suggest_from_text("email", "I'll send the report", untrusted=True)` with a `FakeQuarantinedReader` returns a `suggestion_id`; `suggest_from_text("email", ..., untrusted=True)` with `quarantine=None` raises `ValueError`; `suggest_from_text("chat", "not a task", untrusted=False)` returns `None`; `parse_failed` extract returns `None` without raising.

- [ ] **Task 3: Implement `build_capture_pattern_key` normaliser** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/capture.py` —

  ```python
  def build_capture_pattern_key(source_class: str, commitment_shape: str) -> str:
      """
      Stable identity for a recurring capture pattern.
      source_class: "email" | "chat" | "calendar"
      commitment_shape: one of COMMITMENT_SCHEMA enum values
      Returns: "email:will_send" etc. — collapses paraphrases from the same source + shape.
      Mirrors M7-a2 task_class_key normalisation.
      """
      safe_source = source_class.strip().lower()
      safe_shape = commitment_shape.strip().lower()
      if safe_source not in {"email", "chat", "calendar"}:
          safe_source = "other"
      if safe_shape not in {
          "will_send", "will_call", "will_meet", "will_pay",
          "will_review", "will_schedule", "will_complete", "other"
      }:
          safe_shape = "other"
      return f"{safe_source}:{safe_shape}"
  ```

  — done when: `uv run mypy --strict src` passes; `build_capture_pattern_key("email", "will_send") == "email:will_send"`; unknown values collapse to `"other:other"`.

### Phase 2 — Capture-recipe graduation on `accept_suggestion`

- [ ] **Task 4: Implement `accept_with_graduation`** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/capture.py` —

  Add to `CaptureService`:

  ```python
  @dataclass
  class CaptureService:
      store: ProductivityStore
      model: ModelPort
      quarantine: QuarantinedReader | None
      recipe_store: RecipeStore
      promoter: Promoter
      role: str = "sensitive_reasoner"
  ```

  `async def accept_with_graduation(self, suggestion_id: str, *, project_id: str | None = None, area_id: str | None = None, due_at: str | None = None) -> str` **(ADR-016: `async def` — it `await`s `RecipeStore.write` in the Task-5 graduation flow; called via the `await`ing `suggestion_accept` async `callable_ref`. The `accept_suggestion`/`get_suggestion`/`note_occurrence`/`set_status` SQLCipher calls inside it stay sync.)**:

  1. Load the suggestion: add `get_suggestion(id) -> dict | None` to `ProductivityRepository` if not present (thin SELECT by id; listed in Files to Change as conditional). Extract `source_class = suggestion["source"]` and `commitment_shape = suggestion.get("commitment_shape") or "other"` — **U7 fix: `commitment_shape` is read from its dedicated column, not parsed from a notes string**.
  2. `task_id = self.store.accept_suggestion(suggestion_id, project_id=project_id, area_id=area_id, due_at=due_at)`.
  3. Compute `capture_key = build_capture_pattern_key(source_class, commitment_shape)`.
  4. Graduation logic — see Task 5 for the full flow (count + threshold check + CANDIDATE write + `note_occurrence`).
  5. Return `task_id`.

  — done when: `uv run mypy --strict src` passes; `await accept_with_graduation(id)` (async test — `accept_with_graduation` is `async def` per ADR-016) reads `commitment_shape` from the suggestion column and computes the capture key correctly; the returned `task_id` is the one from `store.accept_suggestion`.

- [ ] **Task 5: Build and write the CANDIDATE capture recipe at graduation threshold** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/capture.py` —

  M7-b's `Promoter.note_occurrence` already calls `_auto_promote` when `count >= threshold` and a CANDIDATE exists. The gap is that no CANDIDATE exists yet — it must be created when the threshold is first crossed.

  **Graduation flow (canonical — implement exactly this in `accept_with_graduation` after step 3):**

  <!-- (resolved by ADR-016: callable_ref + accept_with_graduation are async) — ADR-016 makes every `ToolSpec.callable_ref` uniformly `async def`, so the `suggestion_accept` brain-tool callable is `async def` and `await`s `accept_with_graduation`, which is itself `async def` and `await`s `RecipeStore.write` (async since ADR-015). The `note_occurrence`/`set_status` SQLCipher calls stay sync inside the async method. -->
  ```python
  count_before = self.promoter.recurrence.count(capture_key)
  self.promoter.recurrence.note(capture_key)
  new_count = count_before + 1

  if new_count >= self.promoter.threshold:
      # B7 fix: check ALL statuses — if any recipe for this key exists (CANDIDATE, PENDING,
      # or ENABLED), do NOT write again. Never clobber an owner-approved ENABLED recipe.
      all_for_key = [r for r in self.recipe_store.list() if r.task_class_key == capture_key]
      if not all_for_key:  # create the candidate only if no recipe exists for this key
          candidate = _build_capture_recipe(capture_key, source_class, commitment_shape)
          await self.recipe_store.write(candidate)  # ADR-016/ADR-015: RecipeStore.write is async → await it; writes CANDIDATE, signed
          # Promoter sees the new CANDIDATE and promotes it to PENDING
          # classify_safety(TOUCHES_DATA) → gated → PENDING (never ENABLED automatically)
          # note_occurrence/set_status are sync SQLCipher calls inside this async method
          self.promoter.note_occurrence(capture_key)
  ```

  `def _build_capture_recipe(capture_key: str, source_class: str, commitment_shape: str) -> Recipe`:

  ```python
  Recipe(
      name=f"capture_{capture_key.replace(':', '_')}",
      description=f"Auto-capture {commitment_shape.replace('_', ' ')} commitments from {source_class} into task suggestions",
      version="0.1.0",
      recipe_class=RecipeClass.INSTRUCTIONS,
      action_class=ActionClass.TOUCHES_DATA,   # creates tasks → TOUCHES_DATA → gated
      task_class_key=capture_key,
      inputs_schema={
          "type": "object",
          "properties": {
              "source": {"type": "string"},
              "text": {"type": "string"}
          },
          "required": ["source", "text"]
      },
      outputs_schema={
          "type": "object",
          "properties": {
              "suggestion_id": {"type": "string"}
          }
      },
      instructions=(
          f"When a {commitment_shape.replace('_', ' ')} commitment is detected in a {source_class} message, "
          f"automatically call suggest_from_text(source='{source_class}', text=<text>, untrusted={'true' if source_class == 'email' else 'false'}) "
          f"and create an inert suggestion. The owner reviews and accepts it from the suggestion inbox. "
          f"Origin: capture_graduation/{capture_key}."
          # B5 fix: Recipe has no provenance field (not in M7-a1 schema). Origin is encoded in
          # description + instructions strings above. Do NOT pass provenance= to Recipe().
      ),
      status=RecipeStatus.CANDIDATE,
  )
  ```

  **Security assertion (inline comment):** `# ACTION_CLASS=TOUCHES_DATA → classify_safety → "gated" → Promoter._auto_promote moves this to PENDING only (never ENABLED). Owner must explicitly approve via ReviewSurface.approve(). Verified: see M7-b Assumptions + test_productivity_capture.py graduation_gated test.`

  — done when: `uv run mypy --strict src` passes; `await accept_with_graduation` (async test) called N≥threshold times with the same source+shape pattern → `recipe_store.list(status=CANDIDATE)` contains the recipe (and `recipe_store.list(status=PENDING)` contains it after the promoter fires); the recipe is `TOUCHES_DATA`; `ReviewSurface.pending_for_review()` includes it.

### Phase 3 — Knowledge + memory push on project completion

- [ ] **Task 6: Implement `_push_knowledge` helper and wire to `project_complete` and `project_archive`** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` (SURGICAL modify) —

  Add module-level singletons: `_ingest_pipeline: IngestPipeline | None = None`, `_memory_queue: MemoryWriteQueue | None = None`, `_settings: Settings | None = None` (needed by `_push_knowledge` for the B6 staging path), and `_capture_service: CaptureService | None = None`. Add `def init_capture(capture_service: CaptureService, ingest_pipeline: IngestPipeline, memory_queue: MemoryWriteQueue, settings: Settings) -> None` (sets all four module-level handles).

  Add `def _push_knowledge(project: dict) -> None`:

  ```python
  def _push_knowledge(project: dict) -> None:
      """Push completed-project summary to knowledge index + standing facts to memory."""
      if _ingest_pipeline is None or _memory_queue is None:
          return  # degrade-don't-crash: knowledge push is best-effort
      try:
          summary_text = (
              f"Project completed: {project['title']}. "
              f"Notes: {project.get('notes') or '(none)'}. "
              f"Completed at: {project.get('updated_at', '')}."
          )
          # M3-a IngestPipeline: trusted owner-authored source → no untrusted layer
          source = Source(kind="file", uri=f"project:{project['id']}", scope="owner-private")
          # ingest is synchronous in M3-a's off-hardware path; wrap in try
          _ingest_pipeline.ingest(source)  # pipeline is pre-built with the summary text via a wrapper
          # M4-b MemoryWriteQueue: enqueue standing-fact text (working patterns, estimates)
          fact_text = (
              f"Completed project '{project['title']}'. "
              + (f"Target date was {project['target_date']}. " if project.get('target_date') else "")
              + "This is a completed milestone for the owner."
          )
          _memory_queue.enqueue(fact_text, turn_id=f"project_complete:{project['id']}")
      except Exception:
          import logging
          logging.getLogger("productivity.capture").warning(
              "Knowledge push failed for project %s", project.get("id"), exc_info=True
          )
  ```

  **NOTE on IngestPipeline seam (B6 fix):** M3-a's `FileConnector` rejects paths outside an allowed roots set. Writing to `tempfile.NamedTemporaryFile` (system `/tmp`) would produce a `ValueError` — the composition root's `FileConnector` is rooted at the data dirs, not `/tmp`. **Use a staging subdir inside `scope_dir` instead:**

  ```python
  import os
  staging_dir = paths.scope_dir(settings, OWNER_PRIVATE) / "ingest-staging"
  staging_dir.mkdir(parents=True, exist_ok=True)
  tmp_path = staging_dir / f"project-{project['id']}.txt"
  try:
      tmp_path.write_text(summary_text, encoding="utf-8")
      source = Source(kind="file", uri=str(tmp_path), scope=OWNER_PRIVATE)
      _ingest_pipeline.ingest(source)
  finally:
      tmp_path.unlink(missing_ok=True)
  ```

  `settings` must be accessible in `_push_knowledge` — add `_settings: Settings | None = None` as a module-level singleton alongside `_ingest_pipeline` / `_memory_queue`, and set it in `init_capture`. The `FileConnector` at the composition root must include `scope_dir(settings, OWNER_PRIVATE)` (and its subdirs) in its allowed roots — document this wiring requirement for the composition root author.

  **Do NOT use `tempfile.NamedTemporaryFile` with a system temp path** — M3-a `FileConnector` will reject it.

  SURGICAL modifications to `tools.py`:
  1. Add `from artemis.modules.productivity.capture import CaptureService, _push_knowledge` (or move `_push_knowledge` inline — either is fine; `capture.py` is cleaner).
  2. In the `suggestion_accept` callable: make it `async def` (ADR-016: every `ToolSpec.callable_ref` is uniformly async) and replace `store.accept_suggestion(...)` with `await _capture_service.accept_with_graduation(...)` (`accept_with_graduation` is `async def` per Task 4). The callable's `args`/return models are unchanged; only the `def` → `async def` + the `await` on the graduation call change.
  3. In `project_archive` callable: after the store call, call `_push_knowledge(store.get_project(args.id))` (degrade: wrapped in try/except per the function body).
  4. Add `project_complete` tool if not already present (it was not in M8-d-a's tool list — M8-d-a has `project_archive` but no explicit `project.complete`). Add `project_complete` as a WRITE tool, defined `async def` (ADR-016: every `ToolSpec.callable_ref` is uniformly async — same as all M8-d-a callables; `store.update_project`/`_push_knowledge` stay sync inside the async body): calls `store.update_project(id, status="done")` then `_push_knowledge`. Add the `ToolSpec` for `"project.complete"` (one additional tool — total becomes 32; update manifest task count accordingly).

  **B1 fix — tool count (cumulative):** M8-d-a: 30 tools. M8-d-b adds `task.schedule` → 31. M8-d-c1 adds no tools → still 31. M8-d-c2 (this spec) adds `project.complete` → **32 total**. The manifest count assertion in this spec must be 32. The "31" note in earlier task descriptions was based on a pre-M8-d-b count — 32 is correct after the full a→b→c1→c2 build.

  — done when: `uv run mypy --strict src` passes; `init_capture(...)` sets the module handles; `suggestion_accept` is `async def` and `await`s `accept_with_graduation`; `project_archive` calls `_push_knowledge` (asserted in tests via FakeIngestPipeline call count); `project.complete` tool exists and calls `_push_knowledge`.

- [ ] **Task 7: Manifest wiring** — files: `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` (SURGICAL modify) —

  Extend `productivity_manifest` signature:

  ```python
  def productivity_manifest(
      store: ProductivityStore,
      schedule_fn: ...,
      write_tools: CalendarWriteTools,
      registry: TemplateRegistry,
      capture_service: CaptureService,
      ingest_pipeline: IngestPipeline,
      memory_queue: MemoryWriteQueue,
  ) -> ModuleManifest:
  ```

  Inside, add:
  ```python
  from artemis.config import get_settings
  from artemis.modules.productivity.tools import init_capture
  init_capture(capture_service, ingest_pipeline, memory_queue, get_settings())
  ```
  Do NOT add `settings` as an 8th parameter to `productivity_manifest(...)` — that would contradict the canonical 7-param signature and all three call sites (the Task-7 done-when, the Task-8 manifest-smoke AC line 378, and the AC line 483). `init_capture` genuinely needs `settings` (its signature requires it; `_push_knowledge` reads `_settings` for `paths.scope_dir`), so obtain it via the module-level `get_settings()` accessor (M0-a convention — same accessor CAL-a/M8-d-a use) inside the function body. The `productivity_manifest(...)` signature stays the 7-param order unchanged.

  Add the `project.complete` `ToolSpec` to the tools list (**B1 fix: total = 32 after the full a→b→c1→c2 build**). Update `__init__.py` re-export to reflect the new params.

  **B1 fix — cumulative signature:** M8-d-c1 already added `registry`; M8-d-b added `schedule_fn`/`write_tools`. The cumulative signature after this spec is: `productivity_manifest(store, schedule_fn, write_tools, registry, capture_service, ingest_pipeline, memory_queue)`. This spec adds only the last three params; verify c1's `registry` and M8-d-b's `schedule_fn`/`write_tools` are already present before editing.

  SURGICAL: touch ONLY the new param wiring, `init_capture` call, and the `project.complete` ToolSpec. Do NOT change hooks, data_scope, permissions, or existing tool specs.

  — done when: `uv run mypy --strict src` passes; `productivity_manifest(store, schedule_fn, write_tools, registry, capture_svc, ingest, queue).tools` has 32 entries; the `project.complete` tool is in the list.

### Phase 4 — Tests

- [ ] **Task 8: Off-hardware tests** — files: `/Users/artemis-build/artemis/tests/test_productivity_capture.py` — typed pytest.

  **Fixtures:**
  - `FakeKeyProvider({"owner-private": os.urandom(32)}, owner_unlocked=True)` + `Settings(data_root=tmp_path)` + `ProductivityStore(settings, fake_key)` (plain-sqlite fallback).
  - `FakeModelPort`: `async def complete(role, messages, response_schema=None, ...)` → returns `ModelResponse(text=json.dumps({"is_commitment": True, "title": "Send the report", "due": None, "commitment_shape": "will_send"}), finish_reason="stop", usage=None, origin="local", model_id="fake")` for any input; for the `"not a task"` input, `text` encodes `{"is_commitment": False, "title": "", "commitment_shape": "other"}`. (Seam 1: `ModelPort.complete` is `async def`; `ModelResponse` includes `origin` + `model_id` fields.)
  - `FakeQuarantinedReader`: `read(...)` → `Extract(source_url="", source_domain="email", summary="I'll send the report on Friday", claims=(), flagged_injection=False, parse_failed=False)`. Variant: `FakeFailingQuarantinedReader`: `parse_failed=True`.
  - `FakeRecipeStore` (in-memory `dict[str, Recipe]`): implements `async def write(self, recipe)` (ADR-015/ADR-016: `RecipeStore.write` is async and is `await`ed by `accept_with_graduation` — the fake's `write` must be `async def` too; stores by name), `list(status=None)` (sync — filters by status), `get(name)` (sync).
  - `FakeRecurrenceStore`: implements `note(key)`, `count(key)`, `reset(key)` over an in-memory `dict`.
  - `FakePromoter`: wraps `FakeRecipeStore` + `FakeRecurrenceStore` + `threshold=2`; exposes real `note_occurrence` logic (just calls `recurrence.note` + checks threshold; if CANDIDATE exists, calls `store.set_status → PENDING`).
  - `FakeIngestPipeline`: `ingest(source)` → `IngestResult(document_id="x", chunks_written=1, skipped=False)`; records calls.
  - `FakeMemoryWriteQueue`: `enqueue(text, turn_id)` → records calls.
  - **F12 fix — shared store instances:** define `shared_recipe_store = FakeRecipeStore()` and `shared_recurrence_store = FakeRecurrenceStore()` ONCE as pytest fixtures; pass the SAME instances to `CaptureService`, `FakePromoter`, and `ReviewSurface`. Never pass fresh `FakeRecipeStore()` / `FakeRecurrenceStore()` at multiple call sites — doing so gives each component an isolated empty store and graduation assertions will always fail.
  - `CaptureService` fixture: `CaptureService(store=store, model=FakeModelPort(), quarantine=FakeQuarantinedReader(), recipe_store=shared_recipe_store, promoter=FakePromoter(shared_recipe_store, shared_recurrence_store), role="sensitive_reasoner")`.

  **Tests:**

  **Commitment detection — trusted path (chat):**
  - `suggest_from_text("chat", "I'll send the report", untrusted=False)` → returns a `suggestion_id` (not None); `store.list_suggestions(status="pending")` contains one row with `title="Send the report"`, `source="chat"`; `raw_context` is `None`.
  - `suggest_from_text("chat", "not a task", untrusted=False)` → returns `None`; `store.list_suggestions(status="pending")` is empty.

  **Email quarantine gate:**
  - `suggest_from_text("email", "I'll send the report", untrusted=True)` with `FakeQuarantinedReader` → returns a `suggestion_id`; the `FakeModelPort` received `summary` as the input text (not the raw email text `"I'll send the report"` — the extraction runs on `Extract.summary`). Assert `FakeModelPort.last_user_content == FakeQuarantinedReader.fixed_summary`.
  - `suggest_from_text("email", ..., untrusted=True)` with `quarantine=None` → raises `ValueError`.
  - `suggest_from_text("email", ..., untrusted=True)` with `FakeFailingQuarantinedReader` → returns `None` (no raise).
  - Assert `store.list_suggestions()` row's `raw_context` is `None` for email-sourced suggestions.

  **`capture_pattern_key` normalisation:**
  - `build_capture_pattern_key("email", "will_send") == "email:will_send"`.
  - `build_capture_pattern_key("EMAIL", "WILL_SEND") == "email:will_send"` (case-fold).
  - `build_capture_pattern_key("sms", "will_send") == "other:will_send"` (unknown source → "other").
  - `build_capture_pattern_key("email", "unknown_verb") == "email:other"` (unknown shape → "other").

  **Graduation — below threshold:**
  - Create a suggestion and `await accept_with_graduation` once (async test — `accept_with_graduation` is `async def` per ADR-016). Assert `FakeRecurrenceStore.count("email:will_send") == 1`; `FakeRecipeStore.list(status=RecipeStatus.CANDIDATE)` is empty (threshold not yet met).

  **Graduation — at threshold (CANDIDATE written, gated):**
  - `await accept_with_graduation` a second time for the same source+shape. Assert:
    - `FakeRecipeStore.list(status=RecipeStatus.CANDIDATE)` is NOT empty (the candidate was written at threshold).
    - The candidate recipe's `name` starts with `"capture_email_will_send"`.
    - `recipe.action_class == ActionClass.TOUCHES_DATA`.
    - After the promoter fires: the recipe is in `PENDING` status (not `ENABLED` — gated path confirmed).
    - `ReviewSurface(FakeRecipeStore(), FakePromoter(...)).pending_for_review()` includes the recipe.
    - The recipe is NOT in `ENABLED` state (explicit assertion: `assert recipe.status != RecipeStatus.ENABLED`).

  **Graduation — idempotency:**
  - A third `await accept_with_graduation` call for the same key does NOT write a second CANDIDATE recipe (the `if not existing` guard — `FakeRecipeStore.list(status=CANDIDATE)` still has exactly one entry).

  **Knowledge push on project complete:**
  - Create a project; `await tools.project_complete(args)` (or `project_archive` — whichever triggers `_push_knowledge`; both are `async def` tool callables per ADR-016, so the test is async and `await`s the call). Assert `FakeIngestPipeline.calls` has 1 entry; `FakeMemoryWriteQueue.calls` has 1 entry; the memory enqueue `turn_id` starts with `"project_complete:"`.

  **Knowledge push degrades gracefully:**
  - `_push_knowledge(project)` where `_ingest_pipeline` raises → no exception propagates to the caller; tool returns `OkResult(ok=True)`.

  **Manifest smoke:**
  - `productivity_manifest(store, schedule_fn, write_tools, registry, capture_svc, ingest, queue).tools` has **32** tools; `"project.complete"` tool name is in the list; no duplicate names. (B1 fix.)

  — done when: `uv run pytest -q tests/test_productivity_capture.py` passes AND `uv run mypy --strict src tests/test_productivity_capture.py` passes.

- [ ] **Task 9 (GATED — on-hardware):** On the Mini with vault mounted, a served `sensitive_reasoner` model, and the M2-c binding:
  - `suggest_from_text("chat", "I'll send the report by Friday", untrusted=False)` with the real model → `suggestion_id` returned; suggestion confirmed in the DB.
  - `suggest_from_text("email", raw_email_text, untrusted=True)` with a real `QuarantinedReader` (real model for quarantine read) → suggestion created with `raw_context=None`.
  - Threshold graduation: accept 2 suggestions of the same shape → `RecipeStore.list(status=CANDIDATE)` has the capture recipe on disk (encrypted); `RecipeStore.list(status=PENDING)` after promoter → recipe is `PENDING` (not `ENABLED`); `ReviewSurface.pending_for_review()` lists it.
  - Owner approves via `ReviewSurface.approve(name)` → recipe becomes `ENABLED`; thereafter `retrieve_recipes("will send email")` returns it.
  - Project complete → `ingest_pipeline.ingest` writes a chunk to LanceDB (on the mounted volume); `memory_queue.enqueue` adds the project-complete fact to the write queue.
  — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/modules/productivity/capture.py` |
| Create | `/Users/artemis-build/artemis/tests/test_productivity_capture.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/tools.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/manifest.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/__init__.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/productivity/repository.py` (if `get_suggestion` helper is missing — one SELECT by id) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_productivity_capture.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_productivity_capture.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/productivity/capture.py`, `src/artemis/modules/productivity/tools.py`, `src/artemis/modules/productivity/manifest.py`, `src/artemis/modules/productivity/__init__.py`, `src/artemis/modules/productivity/repository.py` (if modified), `tests/test_productivity_capture.py` |
| `git commit` | `"feat: M8-d-c2 capture service + recipe graduation + knowledge/memory push"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir resolution (off-hardware: tmp_path fixture) |

### Network
| Action | Purpose |
|--------|---------|
| (none off-hardware) | Tests use fakes; real model is GATED on-hardware |

## Specialist Context

### Security

**Load-bearing invariants — all must be honoured by the build:**

1. **Email quarantine first:** raw email text (`text` arg when `untrusted=True`) is NEVER passed to `store.create_suggestion`, `raw_context`, or the extraction model. The only thing that reaches the extraction model is `Extract.summary` from `QuarantinedReader.read`. Enforced by: (a) `suggest_from_text` passing `raw_context=None` to `create_suggestion`; (b) test asserting `raw_context is None` for email-sourced suggestions; (c) `suggest_from_text` with `untrusted=True, quarantine=None` raises `ValueError`.

2. **Suggestions are inert until accept:** the `suggestions` table row has `status="pending"`. No task is created until `accept_suggestion` is called by the owner. No LLM-generative step may act on a suggestion's content without owner confirmation. This is the §G invariant (phantom-task protection).

3. **Capture recipe is `TOUCHES_DATA` → gated → NEVER auto-enabled:** `_build_capture_recipe` hardcodes `action_class=ActionClass.TOUCHES_DATA`. `classify_safety(TOUCHES_DATA) == "gated"` (M7-b pure function). `Promoter._auto_promote` for a gated recipe calls `store.set_status(PENDING)` ONLY — it never calls `set_status(ENABLED)`. The only path to `ENABLED` is owner `approve` via `ReviewSurface`. The graduation test explicitly asserts `recipe.status != RecipeStatus.ENABLED` after the threshold fires.

4. **No prompt injection via accepted suggestion title:** the task title written by `accept_suggestion` comes from the detection model's bounded `COMMITMENT_SCHEMA` output (`title: maxLength 200`). It is stored as a plain string in the tasks table, never interpolated into SQL (parameterised queries, M8-d-a contract), never fed into an LLM without the owner's turn context.

5. **Knowledge push is trusted source only:** `IngestPipeline.ingest` is called with owner-authored project summary text (trusted). No `untrusted` layer is applied (correct per §H). Email-sourced suggestions that were accepted do NOT push their `raw_context` to the knowledge index (it is `None`).

6. **Degrade-don't-crash:** `_push_knowledge` is wrapped in try/except; `suggest_from_text` with `parse_failed=True` returns `None` without raising. A failed knowledge push must not abort a tool call.

[apex-security review: the load-bearing boundary is point 3 — confirm no code path sets a capture recipe to `ENABLED` without explicit owner `approve`. The `if not existing: write(candidate); note_occurrence(key)` sequence is the only place the CANDIDATE is created; `Promoter._auto_promote` for `TOUCHES_DATA` moves it to `PENDING` only. Review `_build_capture_recipe` for hardcoded `ActionClass.TOUCHES_DATA`.]

[apex-data review: the `suggestions.raw_context` column is always `None` for email-sourced suggestions in this spec. The title in the suggestion is owner-visible and Pydantic-validated at the tool layer before DB write.]

### Performance

- Commitment detection is one local `sensitive_reasoner` call per incoming message — async (`suggest_from_text` is `async def`), fire-and-forget off the interactive turn (the brain schedules it). The quarantine read (for email) is also one local call; both are off the hot path.
- `_push_knowledge` is synchronous in the off-hardware path (temp file + `ingest`) but is best-effort (wrapped in try/except); on-hardware the `IngestPipeline` runs async. `MemoryWriteQueue.enqueue` is always non-blocking.
- The graduation path (Recipe CANDIDATE write + Promoter call) is a cheap file write + JSON counter increment — negligible.

### Accessibility

(none — no frontend in M8-d-c2)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/productivity/capture.py` | Docstring all public functions; document the quarantine-first email invariant, the `capture_pattern_key` normalisation, the graduation flow, and the `_build_capture_recipe` TOUCHES_DATA hardcoding rationale |
| Inline | `src/artemis/modules/productivity/tools.py` | Document the `init_capture` wiring seam; document that `suggestion_accept` now calls `accept_with_graduation`; document `_push_knowledge` as best-effort/degrade-don't-crash |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_productivity_capture.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_productivity_capture.py` → verify:
  - trusted `suggest_from_text` creates an inert suggestion with `raw_context=None`.
  - `suggest_from_text("email", ..., untrusted=True)` with `quarantine=None` raises `ValueError`.
  - email path: model received `Extract.summary`, not raw text; `raw_context` is `None` in DB.
  - `parse_failed` quarantine read returns `None` without raising.
  - `build_capture_pattern_key` normalises case + unknown values correctly.
  - graduation below threshold: no CANDIDATE written.
  - graduation at threshold: CANDIDATE written as `TOUCHES_DATA`; Promoter moves it to `PENDING` (not `ENABLED`); `ReviewSurface.pending_for_review()` includes it; `recipe.status != RecipeStatus.ENABLED`.
  - graduation idempotency (B7 fix): after threshold crossing, a third `accept_with_graduation` with the same key does NOT create a duplicate CANDIDATE, AND (if the recipe was promoted to PENDING or ENABLED) does NOT downgrade it back to CANDIDATE. Assert `len([r for r in recipe_store.list() if r.task_class_key == "email:will_send"]) == 1`.
  - `await project_complete` (async tool callable per ADR-016) → `FakeIngestPipeline.calls == 1`; `FakeMemoryWriteQueue.calls == 1`.
  - knowledge push failure does not propagate to tool caller.
  - manifest has **32** tools including `"project.complete"`; no duplicate names. (B1 fix: 30 from M8-d-a + 1 from M8-d-b + 1 from M8-d-c2 = 32.)
- [ ] `uv run python -c "from artemis.modules.productivity.capture import CaptureService, build_capture_pattern_key; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) Task 9: full on-hardware round-trip (real model, real vault, real recipe store, real knowledge push) → verify: recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
