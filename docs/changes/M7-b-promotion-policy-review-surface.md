---
spec: m7-b-promotion-policy-review-surface
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seam 1) + m7-cap-teacher-distill.md BLOCKs B3; FLAGs F5, F6 -->

# Spec: M7-b — Recipe promotion policy (#8) + owner review surface (recurrence/owner-command promotion, auto-enable-safe vs gate-data/action classification, list/explain/approve/reject API, owner-gated commit)

**Identity:** Implements preference-fork #8: a recurrence-counter (N≥2) OR owner-command promoter for `CANDIDATE` recipes, the auto-enable-clearly-safe vs gate-data/action-taking classification, and the owner **review surface** (Python API: list auto-enabled + pending recipes, a plain-language explanation per recipe, approve/reject) — with owner-gated commit for the gated class.
→ why: see preference fork #8 (docs/drafts/sp0-braindump.md session-6 forks) + docs/technical/architecture/brain.md § "Self-improvement" (promote after N≥2 or owner command; promotion owner-gated) · docs/technical/adr/ADR-003-teacher-email-bootstrapping.md (owner-gated rule-growth lifecycle).

<!-- TERMINOLOGY: "recipe" not "skill". -->

<!-- Split rule: TWO logical phases (1: promotion policy = recurrence counter + classifier + promoter; 2: the owner review-surface API). 3 src files + 1 test. At the limit; kept together because the review surface is the owner-facing face of the promotion policy (list = pending-from-the-policy; approve = invoke-the-promoter) and they share the recurrence-counter + the M7-a RecipeStore. Splitting would leave the policy untested against its only consumer. Flagged per rules. If review wants leaner: M7-b1 (promotion policy + recurrence) / M7-b2 (review surface API). -->

## Assumptions
- M7-a1 + M7-a2 complete: `Recipe`, `RecipeStatus` (`CANDIDATE`/`PENDING`/`ENABLED`/`RETIRED`), `ActionClass` (`READ_ONLY`/`NO_DATA`/`TOUCHES_DATA`/`TAKES_ACTION`), `RecipeStore` (`get`/`list`/`set_status`/`retrieve_recipes`), `RecipeSignatureError` [M7-a1]; `task_class_key` + the candidate-on-verified-teacher-success write path [M7-a2]. → impact: Stop (M7-b consumes these exactly; it only changes recipe `status` and adds a recurrence store + the review API).
- "Clearly-safe" (auto-enable) = `action_class in {READ_ONLY, NO_DATA}`. "Gated" (owner approval required) = `action_class in {TOUCHES_DATA, TAKES_ACTION}`. This is the #8 split encoded as a pure function over `Recipe.action_class`. → impact: Stop (the safe/gated boundary IS fork #8; mis-classifying gates is a privacy/safety regression).
- Recurrence is counted by `task_class_key`: each time a task class recurs (a candidate already exists for that key and the same class is escalated/seen again), a counter increments; **N≥2 occurrences** promote a candidate (clearly-safe → auto-enable; gated → move to `PENDING` for owner approval). The recurrence counter is a small persisted store (count per `task_class_key`). → impact: Caution. RESOLVED (gate 2026-06-08): **recurrence counts ONLY re-escalations of the same `task_class_key`** (a request hit the escalation path again for that class — a genuine "this hard task recurred" signal), NOT every router classification (counting all router hits would make a common class reach N≥2 instantly = no real threshold). `note_occurrence(task_class_key)` is called from the Brain escalate path (M7-a2) only when a CANDIDATE exists for that key. N≥2 threshold config-tunable.
- Owner-command promotion: an explicit owner action (via the review surface `approve` or a direct `promote(name)` call) promotes a candidate to `ENABLED` regardless of recurrence count, for any class (the owner is the authority). → impact: Stop (owner command is the always-available override per brain.md/#8).
- The "owner-gated commit" for the gated class = the act of flipping a `PENDING` (gated) recipe to `ENABLED` requires an explicit owner approve call (no auto-flip). M7-b exposes this as a function; the *delivery* of the pending list to the owner (e.g. via the M6 Heartbeat digest / app) is a presentation concern — M7-b ships the API + plain-language explanation; the M6/app wiring is referenced, not built here. → impact: Caution. RESOLVED (gate 2026-06-08, IG1=B): the **approve/reject action surface is the client-app Review screen** (over its M2-authenticated connection); the M6 ntfy digest is **informational only** ("N recipes pending review"), carrying no action. M7-b exposes `pending_for_review() -> list[RecipeReview]` (each with a plain-language explanation) as the stable data contract the client-app Review screen renders + `approve`/`reject` call back into. NOTE: the client-app spec is not yet written — it MUST include this Review screen; until it ships, gated (`TOUCHES_DATA`/`TAKES_ACTION`) recipes park in `PENDING` (clearly-safe still auto-enable).
- "Plain-language explanation" = a deterministic, template-rendered sentence per recipe (NO LLM at review time — keep the review surface token-free, consistent with brain.md's rule-based library-time discipline) describing what the recipe does, its action class, whether it touches data / takes actions, and why it is auto-enabled or gated. → impact: Low (template, not a model call).

Simplicity check: considered an LLM-generated explanation per recipe — rejected; a deterministic template keeps the review surface token-free and predictable (and library-time is rule-based by brain.md). Considered auto-enabling on first verified success — rejected; #8 + brain.md require N≥2 OR owner command, and auto-enable is restricted to the clearly-safe class. Considered storing recurrence inside the Recipe — rejected; recurrence is keyed by `task_class_key` (can predate/outlive a specific recipe version), so a separate small counter store is the minimum.

## Prerequisites
- Specs that must be complete first: M7-a1 (`Recipe`/`RecipeStatus`/`ActionClass`/`RecipeStore`/`RecipeSignatureError`), M7-a2 (`task_class_key`). The approve/reject action surface is the client-app Review screen (IG1=B; client-app spec TBD); the M6 digest is informational-only (referenced, not a build dependency here).
- Environment setup required: none beyond M7-a. Fully deterministic; no on-hardware gate (no model calls in M7-b — promotion + classification + explanation are all rules/templates).
- **Reservation note (architecture-validation 2026-06-23, reservation H2 — recipe-quality gate + re-seed; ADR-022 Refinement 2026-06-23):** recipe quality is *baked in from the teacher at seeding time*, so a recipe distilled under a degraded/unavailable teacher would imprint that weakness permanently. Beyond the recurrence (N≥2) + replay-verify gates, reserve a **teacher-quality field** on the candidate (e.g. which teacher rung authored it + a quality/confidence stamp) and a **`needs_reseed` flag + a re-seed/refresh path** that re-authors a recipe once a stronger teacher is available — keeping the promotion surface itself token-free/rule-based (the re-seed runs in the distill pipeline, not at review time). M7-b reserves the fields/flag; the re-seed producer lives in `distill-datagen-pipeline`. → impact: Low (additive fields + one flag; no v1 behaviour change).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/recipes/promotion.py | create | `classify_safety` (auto-enable-safe vs gate), `RecurrenceStore` (count per task_class_key, persisted), `Promoter` (N≥2 / owner-command → ENABLED or PENDING), `promote`/`note_occurrence` |
| /Users/artemis-build/artemis/src/artemis/recipes/review.py | create | `RecipeReview` model + `explain(recipe) -> str` (plain-language template) + `ReviewSurface` API: `auto_enabled()`, `pending_for_review()`, `approve(name)`, `reject(name)` |
| /Users/artemis-build/artemis/src/artemis/recipes/__init__.py | modify | re-export the new promotion + review symbols |
| /Users/artemis-build/artemis/tests/test_recipes_promotion_review.py | create | classification, recurrence-N≥2 promotion, owner-command override, auto-enable-safe vs gate, review list/explain/approve/reject |

## Tasks
- [ ] Task 1: Implement the safety classifier + recurrence store — files: `/Users/artemis-build/artemis/src/artemis/recipes/promotion.py` —
  - `def classify_safety(recipe: Recipe) -> Literal["auto-enable", "gated"]`: pure function — return `"auto-enable"` iff `recipe.action_class in {ActionClass.READ_ONLY, ActionClass.NO_DATA}`, else `"gated"`. (This is the #8 split.)
  - `class RecurrenceStore` constructed with a `path: Path` (a JSON file under the recipes dir). `def note(self, task_class_key: str) -> int`: increment + persist the count for the key, return the new count (**same-dir atomic** temp + `os.replace`; corrupt-load → start empty). Assumes the Heartbeat is single-process/single-threaded (documented); a lost increment under hypothetical concurrency only delays promotion, never breaks the N≥2 gate. `def count(self, task_class_key: str) -> int`: read (0 if absent). `def reset(self, task_class_key: str) -> None`. Pure stdlib JSON; no model. — done when: `uv run mypy --strict src` passes; `classify_safety` returns `"gated"` for a `TAKES_ACTION` recipe and `"auto-enable"` for a `READ_ONLY` recipe; `RecurrenceStore.note` increments persistently across instances over the same path.

- [ ] Task 2: Implement the Promoter (N≥2 / owner-command) — files: `/Users/artemis-build/artemis/src/artemis/recipes/promotion.py` — `class Promoter` constructed with `(store: RecipeStore, recurrence: RecurrenceStore, threshold: int = 2)`. **Store ctor args as public attributes: `self.store`, `self.recurrence`, `self.threshold`** (required public surface for downstream consumers). Methods:
  - `def note_occurrence(self, task_class_key: str) -> None`: if a `CANDIDATE` recipe exists for this key (via `store.list(status=CANDIDATE)` filtered by `task_class_key`), `recurrence.note(key)`, then if `count >= threshold` call `_auto_promote(recipe)`.
  - `def _auto_promote(self, recipe: Recipe) -> None`: if `classify_safety(recipe) == "auto-enable"` → `store.set_status(recipe.name, ENABLED)` (auto-enable clearly-safe); else → `store.set_status(recipe.name, PENDING)` (gated → await owner approval; do NOT enable). Idempotent (no-op if already ENABLED/PENDING).
  - `def promote(self, name: str) -> Recipe`: OWNER COMMAND — load the recipe **via `store.get(name)` (which verifies the HMAC signature; raises `RecipeSignatureError` on mismatch — refuse to enable an unsigned/tampered recipe even by owner command)**; **if its status is `RETIRED`, raise `RecipeAlreadyRetiredError`** (never silently re-enable a deduped recipe — owner must explicitly un-retire first); else set status `ENABLED` regardless of recurrence count or action_class (owner is the authority); return it. Define `RecipeAlreadyRetiredError(Exception)`. (The always-available owner override — but signature-gated.)
  - `def reject(self, name: str) -> Recipe`: set status `RETIRED` (owner declines a pending/candidate recipe).
  — done when: `uv run mypy --strict src` passes; two `note_occurrence` calls on a CANDIDATE's key auto-ENABLE a clearly-safe recipe but only move a gated recipe to PENDING; `promote(name)` ENABLEs a gated recipe directly; **`promote` on a bad-signature recipe raises `RecipeSignatureError`; `promote` on a RETIRED recipe raises `RecipeAlreadyRetiredError`.** [FLAG gated: `Promoter.promote` and `_auto_promote(gated→PENDING)` are the owner-gated commit boundary — auto-promotion NEVER enables a `TOUCHES_DATA`/`TAKES_ACTION` recipe without an explicit owner `promote`/`approve`.]

- [ ] Task 3: Implement the plain-language explanation + review-surface API — files: `/Users/artemis-build/artemis/src/artemis/recipes/review.py` —
  - frozen dataclass `RecipeReview { name: str, description: str, status: str, action_class: str, safety: Literal["auto-enable","gated"], explanation: str }`.
  - `def explain(recipe: Recipe) -> str`: deterministic template (NO LLM) — e.g. `f"'{recipe.name}': {recipe.description}. This recipe {('reads no personal data' if action_class==NO_DATA else 'only reads data, never changes it' if READ_ONLY else 'reads or writes your data' if TOUCHES_DATA else 'takes actions on your behalf')}. It was {('auto-enabled because it is clearly safe' if safety=='auto-enable' else 'kept pending your approval because it touches data or takes actions')}."` Cover all four `action_class` values + both safety outcomes.
  - `class ReviewSurface` constructed with `(store: RecipeStore, promoter: Promoter)`. Methods (the owner-facing API):
    - `def auto_enabled(self) -> list[RecipeReview]`: every `ENABLED` recipe whose `classify_safety == "auto-enable"` (the owner sees what was auto-enabled, each explained).
    - `def pending_for_review(self) -> list[RecipeReview]`: every `PENDING` recipe (gated, awaiting approval), each explained.
    - `def approve(self, name: str) -> RecipeReview`: owner approves a pending gated recipe → `promoter.promote(name)` (ENABLE) → return its review. (Owner-gated commit.)
    - `def reject(self, name: str) -> RecipeReview`: owner rejects → `promoter.reject(name)` (RETIRE) → return its review.
  Each method builds `RecipeReview` via `explain`. — done when: `uv run mypy --strict src` passes; `pending_for_review()` lists only PENDING recipes with non-empty explanations; `approve(name)` flips a PENDING recipe to ENABLED.

- [ ] Task 4: Re-export the promotion + review surface — files: `/Users/artemis-build/artemis/src/artemis/recipes/__init__.py` — add `classify_safety`, `RecurrenceStore`, `Promoter`, `RecipeReview`, `explain`, `ReviewSurface`, **`RecipeAlreadyRetiredError`** to the re-exports + `__all__`. Add `recurrence_path(s: Settings) -> Path` = `recipes_dir(s) / "recurrence.json"`. (`RecipeAlreadyRetiredError` is defined in Task 2; CLIENT-b Task 4 imports it to map → HTTP 409.) — done when: `uv run python -c "from artemis.recipes import Promoter, ReviewSurface, classify_safety, RecipeReview, RecipeAlreadyRetiredError"` exits 0.

- [ ] Task 5 (B3 — Brain wiring): Wire `Promoter.note_occurrence` into the Brain escalate path — files: `/Users/artemis-build/artemis/src/artemis/brain.py` — **additive ctor param** `promoter: Promoter | None = None` (default `None` → M7-a2/M1 tests still pass unchanged). In the escalate branch of `respond`, after returning `path="escalation_queued"` (M7-a2 Task 4(c)), call `self.promoter.note_occurrence(key)` if `self.promoter is not None` AND `any(r.task_class_key == key for r in self._store.list(status=RecipeStatus.CANDIDATE))` (M7-a1's `list(*, status=...)` returns `list[Recipe]`). This is the only call-site for `note_occurrence` from the teacher-escalation path (M8-d-c2 wires it for capture-pattern keys separately). — done when: `uv run mypy --strict src` passes; a `Brain(store=..., promoter=Promoter(...))` that receives two escalations for the same `task_class_key` (with a CANDIDATE present) ends with the CANDIDATE auto-promoted per `classify_safety` (asserted in Task 6 below).

- [ ] Task 6: Write the promotion + review tests (off-hardware, fakes) — files: `/Users/artemis-build/artemis/tests/test_recipes_promotion_review.py` — typed pytest reusing the M7-a `FakeEmbedder` + `FakeKeyProvider`; build a real `RecipeStore` over a `tmp_path` recipes dir, a `RecurrenceStore` over a tmp JSON, a `Promoter`, a `ReviewSurface`. Tests:
  - classification: a `READ_ONLY` and a `NO_DATA` recipe → `classify_safety == "auto-enable"`; a `TOUCHES_DATA` and a `TAKES_ACTION` recipe → `"gated"`.
  - recurrence auto-enable (safe): write a CANDIDATE `READ_ONLY` recipe; two `note_occurrence(key)` calls → the recipe is now `ENABLED` (auto-enabled clearly-safe).
  - recurrence gate (data/action): write a CANDIDATE `TOUCHES_DATA` recipe; two `note_occurrence(key)` calls → status is `PENDING` (NOT enabled — gated); `pending_for_review()` includes it.
  - below threshold: one `note_occurrence` on a safe candidate → still `CANDIDATE` (not yet promoted).
  - owner command override: `promoter.promote(name)` on a gated CANDIDATE → `ENABLED` directly (owner authority).
  - review surface: `auto_enabled()` lists the auto-enabled safe recipe with a non-empty `explanation`; `pending_for_review()` lists the gated PENDING recipe; `approve(pending_name)` → it becomes `ENABLED` and is no longer in `pending_for_review()`; `reject(other_pending)` → it becomes `RETIRED`.
  - explanation coverage: `explain` returns a distinct, non-empty sentence for each of the four `action_class` values.
  - brain wiring (B3): a `Brain` with `promoter=Promoter(store, recurrence, threshold=2)` and a CANDIDATE `READ_ONLY` recipe; two escalations for its `task_class_key` → the recipe status becomes `ENABLED` (auto-promoted via `note_occurrence`). A `Brain(promoter=None)` receiving the same escalations leaves the recipe `CANDIDATE` (backward-compat).
  — done when: `uv run pytest -q tests/test_recipes_promotion_review.py` passes AND `uv run mypy --strict src tests/test_recipes_promotion_review.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/recipes/promotion.py, /Users/artemis-build/artemis/src/artemis/recipes/review.py, /Users/artemis-build/artemis/tests/test_recipes_promotion_review.py |
| Modify | /Users/artemis-build/artemis/src/artemis/recipes/__init__.py (re-export promotion + review symbols) |
| Modify | /Users/artemis-build/artemis/src/artemis/brain.py (additive `promoter` ctor param + `note_occurrence` call — Task 5) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_recipes_promotion_review.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_recipes_promotion_review.py` | Test gate (classification, recurrence, owner-command, review API — all deterministic) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/recipes/promotion.py, src/artemis/recipes/review.py, src/artemis/recipes/__init__.py, src/artemis/brain.py, tests/test_recipes_promotion_review.py |
| `git commit` | "feat: M7-b recipe promotion policy (#8) + owner review surface (recurrence/owner-command, auto-enable-safe vs gate, list/explain/approve/reject) + brain note_occurrence wiring" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings → recipes_dir + recurrence_path resolution |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No model calls, no network — pure rules + templates |

## Specialist Context
### Security
The auto-enable boundary is the load-bearing #8 safety control: ONLY `READ_ONLY`/`NO_DATA` recipes ever auto-enable; `TOUCHES_DATA`/`TAKES_ACTION` recipes can only become `ENABLED` via an explicit owner `approve`/`promote` (owner-gated commit). [FLAG apex-security + gated: verify no code path auto-flips a gated recipe to ENABLED; `_auto_promote` must move gated recipes only to `PENDING`. The classifier `classify_safety` is the single source of truth for the boundary — review it.]

### Performance
The review surface is token-free: explanations are deterministic templates, classification + promotion are pure rules over stored metadata (consistent with brain.md's rule-based library-time discipline). No model call anywhere in M7-b.

### Accessibility
The `pending_for_review()`/`auto_enabled()` API returns plain-language explanations intended for an owner-facing surface (app/digest); the actual UI is a later client spec — [a11y applies when that UI is built, not here].

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/recipes/promotion.py, src/artemis/recipes/review.py | Type + docstring all exports; document the #8 auto-enable-safe vs gate boundary + the N≥2/owner-command promotion rule + the owner-gated commit for the gated class |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_recipes_promotion_review.py` → verify: exit 0.
- [ ] Run `uv run python -c "from artemis.recipes.model import Recipe, ActionClass; from artemis.recipes.promotion import classify_safety; r=Recipe(name='a',description='d',version='0.1.0',recipe_class='instructions',action_class='takes-action',task_class_key='k',inputs_schema={},outputs_schema={},instructions='x'); print(classify_safety(r))"` → verify: prints `gated`.
- [ ] Run `uv run pytest -q tests/test_recipes_promotion_review.py` → verify: two occurrences auto-ENABLE a clearly-safe candidate but only move a gated candidate to PENDING; `promote` ENABLEs a gated recipe directly; `approve` flips a PENDING recipe to ENABLED; `explain` covers all four action classes.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_
