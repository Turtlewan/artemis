---
spec: m7-a1-recipe-format-store-signing
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seam 1) + m7-cap-teacher-distill.md BLOCKs B4, UPGRADE U1 -->
<!-- amended 2026-06-17: EmbeddingModel port split embed→embed_documents/embed_query (embedding-layer decision; research/2026-06-17-embedding-implementation.md) -->

# Spec: M7-a1 — Recipe format + store + RAG-for-recipes index + signing

**Identity:** Defines the **recipe** artifact (Anthropic-style SKILL.md shape — frontmatter + instructions + optional script), the file-backed `RecipeStore` + RAG-for-recipes index (recipe *description* embedded for retrieval, mirroring M1-a RAG-for-tools), and HMAC signing (sign-on-write, verify-on-load, refuse unsigned/invalid). This is the recipe **data model + storage layer**; the escalate→distill write path is **M7-a2**, rule-based dedupe/retire is **M7-a3**.
→ why: see docs/technical/architecture/brain.md § "Self-improvement — the Curiosity Loop" (recipe distillation bullets) · docs/technical/adr/ADR-007 (recipes on the M2 encrypted volume).

<!-- TERMINOLOGY: "recipe" not "skill". -->
<!-- Sub-split of the former M7-a (gate 2026-06-08): a1 = format+store+index+signing; a2 = escalation+distill+replay-verify+brain-seam+claude-cli; a3 = dedupe/retire. ONE logical phase here (the Recipe data model + its storage/retrieval/signing), 4 src files + 1 test. -->

<!-- RESHAPE PENDING (ADR-024 Refinement 2026-06-23, M9 design): a recipe is being reframed from a WHOLE-TASK unit to an ATOMIC COMPOSABLE PRIMITIVE (one verified capability) so the M9 planner can compose fresh plans from recipe-refs. A "whole task" becomes a saved PLAN = an ordered list of recipe-refs (a new artifact, NOT a recipe). This changes: the `Recipe` model (atomic-capability-shaped — one capability, its own inputs/outputs schema), how M7-a2 distills/graduates (produce atomic recipes, not whole-task automations), and signing (sign the atomic unit). On-disk shape stays frontmatter+body, but the format is MODEL-AGNOSTIC — rendered into a prompt for whatever the ModelPort routes to; NOT Codex AGENTS.md, NOT vendor-tied; write the instructions body in model-neutral language. Apply at M7 spec time — M7 is NOT built. -->

## Assumptions
- M0-a (`config`/`paths`/`Settings`, `mypy --strict` + `pydantic.mypy`), M0-d (`ports`: `EmbeddingModel`, `VectorStore`, `RetrievedChunk`, `Vector`, `Scope`), M1-a (`InMemoryToolIndex` cosine `VectorStore`, the RAG-for-tools pattern to mirror) are complete. → impact: Stop (M7-a1 consumes these ports/types; signatures must match exactly).
- A recipe is **data, loaded at runtime** (brain.md). On-disk form = a SKILL.md-shaped file: YAML frontmatter (`name`, `description`, `version`, `recipe_class`, `action_class`, `task_class_key`, `inputs`/`outputs` JSON schema, `script` path optional, `signature`) + a markdown instructions body. The in-code form is a Pydantic `Recipe` model that round-trips to/from that file. → impact: Stop (dual form mirrors the M1-a hybrid manifest contract).
- The recipe store + index for M7's small recipe count is a **file-backed store + an in-memory cosine index** wrapped behind the M0-d `VectorStore` port (same justification as M1-a `InMemoryToolIndex`), so LanceDB swaps in later with no caller change. → impact: Caution (if the port signature differs, fix the wrapper, not callers).
- **Recipes live on the M2 encrypted volume** (gate 2026-06-08): `recipes_dir(s)` returns a path under the per-scope encrypted volume **unconditionally** — a `touches-data`/`takes-action` recipe's instructions can encode sensitive structure, so all recipes are encrypted at rest. → impact: Stop (do NOT place recipes in a plain config dir).
- Recipe **signing** is HMAC-SHA256 over the recipe's deterministic canonical bytes using an owner-held key from the M2 Keychain/Secure-Enclave `KeyProvider` seam; M7-a1 verifies signatures on load and refuses to return an unsigned/invalid-signature recipe when a signer is set. → impact: Caution (concrete binding to M2's `KeyProvider` is a one-line wiring; off-hardware uses a `FakeKeyProvider`). HMAC, not asymmetric (single-box, single owner; integrity not third-party verifiability).

Simplicity check: considered storing recipes directly in LanceDB — rejected; an in-memory cosine index behind the port is the M1-a-proven minimum for a small count. Considered asymmetric signing — rejected; single-box single-owner integrity needs only HMAC.

## Prerequisites
- Specs that must be complete first: M0-a, M0-d, M1-a. Sequenced-with: M2 (the `KeyProvider` seam the `RecipeSigner` binds to + the encrypted volume `recipes_dir` lives on; off-hardware uses `FakeKeyProvider` + a tmp dir).
- Environment setup required: none beyond M0/M1 for the off-hardware suite (deterministic fakes for embedder + key provider).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/recipes/__init__.py | create | package marker + re-exports (`Recipe`, `RecipeClass`, `ActionClass`, `RecipeStatus`, `RECIPE_SCHEMA`, `RecipeStore`, `RecipeIndex`, `RecipeSigner`, `KeyProvider`, `RecipeSignatureError`, `recipes_dir`); M7-a2/a3 extend `__all__` |
| /Users/artemis-build/artemis/src/artemis/recipes/model.py | create | `Recipe` Pydantic model + `RecipeClass`/`ActionClass`/`RecipeStatus` enums + `RECIPE_SCHEMA` + SKILL.md frontmatter (de)serialise |
| /Users/artemis-build/artemis/src/artemis/recipes/store.py | create | file-backed `RecipeStore` + `RecipeIndex` (cosine `VectorStore` over recipe *descriptions*) + `retrieve_recipes(query, k)` + `recipes_dir` |
| /Users/artemis-build/artemis/src/artemis/recipes/signing.py | create | `KeyProvider` Protocol + `RecipeSigner` (HMAC-SHA256 deterministic canonical-bytes sign/verify) + `RecipeSignatureError` |
| /Users/artemis-build/artemis/tests/test_recipes_store_signing.py | create | model round-trip, sign/verify (incl. SKILL.md round-trip), store + RAG-for-recipes retrieval, set_status upsert |

## Tasks
- [ ] Task 1: Define the Recipe model + enums + distillation schema — files: `/Users/artemis-build/artemis/src/artemis/recipes/model.py` — pure Pydantic v2, `mypy --strict`-clean:
  - `class RecipeClass(StrEnum)`: `INSTRUCTIONS = "instructions"`, `SCRIPT = "script"`.
  - `class ActionClass(StrEnum)`: `READ_ONLY = "read-only"`, `NO_DATA = "no-data"`, `TOUCHES_DATA = "touches-data"`, `TAKES_ACTION = "takes-action"` (the classification M7-b's auto-enable-safe-vs-gate policy consumes; "clearly-safe" = `READ_ONLY`/`NO_DATA`).
  - `class RecipeStatus(StrEnum)`: `CANDIDATE`, `PENDING`, `ENABLED`, `RETIRED`.
  - `class Recipe(BaseModel)` (`ConfigDict(arbitrary_types_allowed=False)`): `name: str` (slug `^[a-z][a-z0-9_]*$`), `description: str` (the field EMBEDDED for retrieval), `version: str`, `recipe_class: RecipeClass`, `action_class: ActionClass`, `task_class_key: str`, `inputs_schema: dict[str, object]`, `outputs_schema: dict[str, object]`, `instructions: str`, `script: str | None = None`, `status: RecipeStatus = RecipeStatus.CANDIDATE`, `signature: str | None = None`, `provenance: dict[str, str] = {}`. `model_validator` rejects an empty `description`.
  - `def to_skill_md(self) -> str` / `@classmethod def from_skill_md(cls, text: str) -> Recipe`: YAML frontmatter + `\n---\n` + instructions body (+ fenced `script` block if present). Round-trip lossless for ALL fields.
  - `RECIPE_SCHEMA: Final[dict[str, object]]` = the distillation output schema (name, description, recipe_class, action_class, inputs_schema, outputs_schema, instructions, script?). Derive from `Recipe.model_json_schema()` restricted to those keys. **Inline/flatten `$defs`/`$ref` (enums) into a self-contained schema** so the constrained-decode/post-validate path (M7-a2) accepts it without ref-resolution.
  — done when: `uv run mypy --strict src` passes and `Recipe.from_skill_md(r.to_skill_md()) == r` for a sample recipe (lossless round-trip).

- [ ] Task 2: Implement the recipe store + RAG-for-recipes index — files: `/Users/artemis-build/artemis/src/artemis/recipes/store.py` —
  - `class RecipeIndex` structurally satisfying `artemis.ports.VectorStore` (do NOT subclass; add `# satisfies artemis.ports.VectorStore` + a static type-assert in the test). Reuse the M1-a `InMemoryToolIndex` cosine approach (L2-normalised dot-product, scope-filtered, returns `RetrievedChunk`). **`add` MUST be upsert-by-id** (remove any existing entry for the same `id` before adding) — else `set_status` leaves a stale entry and RAG-for-recipes returns a RETIRED recipe's old ENABLED row.
  - `def recipes_dir(s: Settings) -> Path` = `<per-scope encrypted volume root>/recipes` (NOT a plain config dir — see Assumptions).
  - `class RecipeStore` constructed with `(embedder: EmbeddingModel, recipes_dir: Path, index: VectorStore | None = None, signer: RecipeSigner | None = None)`. Methods:
    - `async def write(self, recipe: Recipe) -> None`: sign first if a signer is set (set `recipe.signature`); persist `recipe.to_skill_md()` atomically (same-dir temp + `os.replace`) to `recipes_dir / f"{recipe.name}@{recipe.version}.skill.md"`; embed `recipe.description` (STORED/indexed text → `embed_documents`, NO query prefix) via `vec = (await self.embedder.embed_documents([recipe.description]))[0]` (M0-d split port — async, ADR-015) and **upsert** `index.add(scope="recipes", ids=[recipe.name], vectors=[vec], metadata=[{"text": recipe.description, "name": recipe.name, "status": recipe.status, "action_class": recipe.action_class}])` (`VectorStore.add` stays sync — no `await`).
    - `get(self, name, version=None) -> Recipe`: load **latest version by parsed numeric tuple** (`tuple(int(x) for x in v.split("."))`) if `version` is None, else the exact version; verify signature via the signer (raise `RecipeSignatureError` on mismatch when a signer is set); `KeyError` if absent. **Version ordering is always parsed numeric tuple — never lexicographic** (so `0.10.0 > 0.9.0`).
    - `list(self, *, status: RecipeStatus | None = None) -> list[Recipe]`: returns **latest-version-per-name** (deduplicated by name, keeping the highest numeric-tuple version); all names if `status` is None, else filtered. **When a signer is set, verifies each loaded recipe's signature; skip (log warning) on mismatch — never silently return a tampered recipe.**
    - `async def retrieve_recipes(self, query, k=3, *, status: RecipeStatus | None = RecipeStatus.ENABLED) -> list[str]`: embed the query (SEARCH text → `embed_query`: single string in, single `Vector` out, the adapter applies the query instruction prefix) via `vec = await self.embedder.embed_query(query)` (M0-d split port — async, ADR-015), `index.search` (`VectorStore.search` stays sync — no `await`), return recipe names (default scoped to `ENABLED` — RAG-for-recipes, exactly like RAG-for-tools).
    - `async def set_status(self, name, status, *, version=None) -> None`: **load via `self.get(name, version=version)` (sync — verifies the HMAC signature — raises `RecipeSignatureError` on mismatch; refuse to re-sign a tampered recipe)**; mutate status; `await self.write(...)` (re-sign + **upsert** re-index; `write` is async — ADR-015). The `version=` param targets a specific version; None → latest.
  — done when: `uv run mypy --strict src` passes; a static `_check: VectorStore = RecipeIndex()` type-checks; `await`-writing an ENABLED recipe then `await set_status(name, RETIRED)` → `await retrieve_recipes(status=ENABLED)` does NOT return it (upsert proven); `get("foo")` on a store with `foo@0.9.0` and `foo@0.10.0` returns `foo@0.10.0` (numeric version ordering, not lexicographic); a tampered recipe loaded via `set_status` raises `RecipeSignatureError` (verify-before-resign, U1).

- [ ] Task 3: Implement recipe signing — files: `/Users/artemis-build/artemis/src/artemis/recipes/signing.py` — `class KeyProvider(Protocol)`: `def signing_key(self) -> bytes: ...` (the seam M2's Keychain provider satisfies). `class RecipeSigner` constructed from a `KeyProvider`. `def canonical_bytes(self, recipe: Recipe) -> bytes`: **deterministic** — `json.dumps(recipe.model_dump(exclude={"signature"}), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")` (pinned so nested `dict` fields serialise identically across runs/Python versions). `def sign(self, recipe) -> str`: `hmac.new(key, canonical_bytes, sha256).hexdigest()`. `def verify(self, recipe) -> bool`: recompute + `hmac.compare_digest` against `recipe.signature` (constant-time). `RecipeSignatureError(Exception)`. — done when: `uv run mypy --strict src` passes; signing then verifying returns True; tampering any field other than `signature` makes verify False; **verify is still True after a `from_skill_md(to_skill_md(r))` round-trip** (canonical determinism).

- [ ] Task 4: Package surface — files: `/Users/artemis-build/artemis/src/artemis/recipes/__init__.py` — re-export `Recipe`, `RecipeClass`, `ActionClass`, `RecipeStatus`, `RECIPE_SCHEMA`, `RecipeStore`, `RecipeIndex`, `recipes_dir`, `RecipeSigner`, `KeyProvider`, `RecipeSignatureError`, with `__all__` (M7-a2/a3 extend it). — done when: `uv run python -c "from artemis.recipes import Recipe, RecipeStore, RecipeSigner, recipes_dir, RECIPE_SCHEMA"` exits 0.

- [ ] Task 5: Write the model+store+signing tests — files: `/Users/artemis-build/artemis/tests/test_recipes_store_signing.py` — typed pytest with `FakeEmbedder` (deterministic hash-based vectors, reuse M1-a pattern; implements BOTH `async def embed_documents(self, texts) -> list[Vector]` and `async def embed_query(self, query) -> Vector` per the split port — same mapping so a query matches its recipe description; async per ADR-015; `dimension` stays a sync property) + `FakeKeyProvider` (fixed bytes), a real `RecipeStore` over `tmp_path`. The store-touching tests are `async def` (mark per the repo's pytest-asyncio convention; if none is established, add `pytest.mark.asyncio` and note it) and `await` the async store methods:
  - model round-trip: `Recipe.from_skill_md(r.to_skill_md()) == r` (lossless).
  - sign/verify: sign then `verify` True; mutate `description` → False; verify still True after a `from_skill_md(to_skill_md())` round-trip.
  - store + RAG-for-recipes: `await store.write(...)` two ENABLED recipes with clearly different descriptions; `await store.retrieve_recipes("<matches A>", k=1, status=ENABLED)` returns A's name; a `CANDIDATE` recipe is NOT returned by the default ENABLED-scoped retrieve.
  - set_status upsert: `await store.write(...)` ENABLED, `await store.set_status(name, RETIRED)` → `await store.retrieve_recipes(status=ENABLED)` excludes it (no stale index row).
  - port conformance: `_check: VectorStore = RecipeIndex()` type-checks (mypy).
  — done when: `uv run pytest -q tests/test_recipes_store_signing.py` passes AND `uv run mypy --strict src tests/test_recipes_store_signing.py` passes.

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/recipes/__init__.py, /Users/artemis-build/artemis/src/artemis/recipes/model.py, /Users/artemis-build/artemis/src/artemis/recipes/store.py, /Users/artemis-build/artemis/src/artemis/recipes/signing.py, /Users/artemis-build/artemis/tests/test_recipes_store_signing.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_recipes_store_signing.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_recipes_store_signing.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/recipes/__init__.py, src/artemis/recipes/model.py, src/artemis/recipes/store.py, src/artemis/recipes/signing.py, tests/test_recipes_store_signing.py |
| `git commit` | "feat: M7-a1 recipe format + store + RAG-for-recipes index + signing" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings → recipes_dir (encrypted-volume path) resolution |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure local; deterministic fakes off-hardware |

## Specialist Context
### Security
- **Recipes are encrypted at rest** — `recipes_dir` is on the M2 per-scope encrypted volume (a touches-data recipe's instructions can encode sensitive structure).
- **Signing** (HMAC) + verify-on-load + refuse-unsigned protects against a tampered/poisoned recipe being loaded. Canonical bytes are deterministic (pinned `sort_keys`/separators) so verify never spuriously fails after a round-trip.
- RAG-for-recipes retrieves only `ENABLED` recipes at runtime by default — `CANDIDATE`/`PENDING` never fire automatically (the promotion gate is M7-b).

### Performance
RAG-for-recipes keeps the recipe library OUT of model context (only the matched handful retrieved), mirroring RAG-for-tools.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/recipes/model.py, store.py, signing.py | Type + docstring all exports; document the SKILL.md-shaped recipe form, the encrypted-volume `recipes_dir`, the upsert-by-id index contract, and the deterministic-canonical-bytes signing |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_recipes_store_signing.py` → verify: exit 0 (incl. `VectorStore = RecipeIndex()`).
- [ ] Run `uv run python -c "from artemis.recipes.model import Recipe; r=Recipe(name='a', description='d', version='0.1.0', recipe_class='instructions', action_class='read-only', task_class_key='k', inputs_schema={}, outputs_schema={}, instructions='do x'); assert Recipe.from_skill_md(r.to_skill_md()).name=='a'"` → verify: exit 0 (lossless round-trip).
- [ ] Run `uv run pytest -q tests/test_recipes_store_signing.py` → verify: round-trip + sign/verify (incl. post-round-trip) + RAG-for-recipes ENABLED-only + set_status upsert all pass.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
- [x] Task 1 model.py (Recipe + RecipeClass/ActionClass/RecipeStatus + RECIPE_SCHEMA + SKILL.md round-trip)
- [x] Task 2 store.py (RecipeStore + RecipeIndex cosine VectorStore, upsert-by-id, numeric version order, RAG-for-recipes)
- [x] Task 3 signing.py (KeyProvider proto + RecipeSigner HMAC deterministic canonical-bytes + RecipeSignatureError)
- [x] Task 4 recipes/__init__.py re-exports
- [x] Task 5 tests/test_recipes_store_signing.py
- Verify: 203 passed · ruff + mypy --strict clean · scope = 5 spec files (no out-of-scope edits)
- DEVIATION (minor): `recipes_dir(s)` = `paths.scope_dir(s, "owner-private")/recipes` (M2 dev-stub has no real encrypted volume; resolves to a plain dir on dev). No new Settings field, no new dep (pyyaml already available).
