# Spec: v2-01 — Model layer (Codex subscription provider + schema-normalization shim)

status: ready
slice: 0
builds-on: v2-00 (ports + types, committed e28361e)

## Identity
First concrete `ModelPort` implementation: a subscription-first model client backed by the Codex CLI, with the schema-normalization shim + client-side validation + re-ask that permanently fixes the strict-vs-lenient structured-output break. LiteLLM + multi-provider router are deferred to Slice 1 (widening); this slice proves one provider end-to-end behind `ModelPort`.

## Files to change
- create `src/artemis/model/__init__.py`
- create `src/artemis/model/schema_norm.py`
- create `src/artemis/model/codex_provider.py`
- create `src/artemis/model/client.py`
- create `tests/test_schema_norm.py`
- create `tests/test_model_client.py`
- create `tests/test_codex_provider.py`
- modify `pyproject.toml` (add runtime dep `jsonschema>=4`)

## Exact changes

### Task 1 — schema-normalization shim (`schema_norm.py`)
The fix for the break: author one canonical JSON schema; down-convert to each backend's dialect.
- `to_strict_schema(schema: dict) -> dict` — produce an OpenAI/Codex **strict**-mode schema:
  - recurse every object node: set `additionalProperties = false`; set `required` = **all** property keys; for each property, allow null by unioning `"null"` into its `type` (so the model can emit null for inapplicable fields without violating all-required).
  - recurse into `properties` values and `items`.
  - **strip unsupported keywords** anywhere: `minLength, maxLength, pattern, format, minimum, maximum, exclusiveMinimum, exclusiveMaximum, multipleOf, minItems, maxItems, uniqueItems, minProperties, maxProperties, minContains, maxContains, contains, propertyNames, unevaluatedItems, unevaluatedProperties`.
  - keep: `type, properties, items, enum, required, additionalProperties, description, anyOf/oneOf/allOf` (recurse those).
  - pure function, no mutation of the input (deep-copy).
- `to_ollama_schema(schema: dict) -> dict` — pass-through (Ollama's `format` is lenient); return a deep copy.
- Note in a docstring: Anthropic tool-`input_schema` conversion is deferred to Slice 1 (no Anthropic backend yet).

### Task 2 — Codex provider (`codex_provider.py`)
A thin subscription-CLI provider (no LiteLLM yet).
- internal `Protocol` `RawProvider` with `async def generate(self, *, messages: Sequence[Message], model: str, schema: dict | None) -> str` (returns the final assistant text).
- `class CodexProvider:` implements `RawProvider`. `__init__(self, *, binary: str = "codex", model_default: str = "gpt-5.5")`.
  - **resolve the binary with `shutil.which(binary) or binary`** in `__init__` (Windows ships a `.cmd` npm shim that `create_subprocess_exec` cannot launch by bare name — this is a known gotcha; the resolved full path works).
  - `generate(...)`: build argv `[resolved_binary, "exec", "-m", model, "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check", "--color", "never", "-o", <tmp out file>]`; when `schema is not None`, write it to a temp file and append `["--output-schema", <schema file>]`; append `"-"`; render messages to one prompt (role-tagged); spawn via `asyncio.create_subprocess_exec`, write the prompt to stdin, await; on non-zero return code raise `CodexProviderError(rc, stderr_excerpt)`; read the `-o` file, return its stripped text.
  - use `tempfile.TemporaryDirectory`; no network commands beyond codex itself.

### Task 3 — model client (`client.py`, implements `ModelPort`)
- `class ModelClient:` `__init__(self, provider: RawProvider, *, model_default: str = "gpt-5.5", max_reasks: int = 2)`.
- `async def complete(self, *, messages, model=None, response_schema=None, temperature=0.7, max_tokens=None) -> ModelResponse`:
  - resolve `model_id = model or self._model_default`.
  - if `response_schema is None`: call provider once, return `ModelResponse(text=..., model_id=model_id, structured=None, finish_reason="stop", usage=Usage(0,0,0))`.
  - else: `strict = to_strict_schema(response_schema)`; loop up to `max_reasks + 1`: call provider with `schema=strict`; `json.loads` the text and `jsonschema.validate` against `response_schema` (the original); on success return `ModelResponse(text=raw, model_id=model_id, structured=parsed, finish_reason="stop", usage=Usage(0,0,0))`; on `JSONDecodeError`/`ValidationError`, append a corrective user `Message` ("Your previous reply was not valid against the schema: <err>. Return only valid JSON.") and retry; after the last attempt raise `ModelOutputError`.
  - satisfies the `ModelPort` Protocol (assert with `isinstance(ModelClient(fake), ModelPort)` in tests).
- `temperature`/`max_tokens` accepted; may be unused by the Codex path (documented).

### Task 4 — tests
- `test_schema_norm.py`: a schema with optional fields + `maxLength`/`maxItems` → assert output has `additionalProperties False`, every key in `required`, `null` unioned into types, and **no** stripped keywords remain (recurse to verify). Assert input is not mutated.
- `test_model_client.py`: a `FakeProvider(RawProvider)` returning canned text. Assert: (a) `isinstance(ModelClient(FakeProvider()), ModelPort)`; (b) schema path returns parsed `structured`; (c) provider first returns bad JSON then good → client re-asks and succeeds; (d) always-bad → raises `ModelOutputError` after `max_reasks`.
- `test_codex_provider.py`: assert `CodexProvider` resolves a binary path and builds the expected argv (inject a fake spawn or assert argv construction via a seam); a live end-to-end call is an **optional** `@pytest.mark.live` test, skipped by default.

## Acceptance criteria
- `uv sync` succeeds (jsonschema added).
- `uv run mypy src tests` → clean (strict).
- `uv run pytest -q` → green (live test skipped by default).
- `to_strict_schema` output passes a real `jsonschema` strict-shape check; the original schema object is unmodified.

## Commands to run
```
uv sync
uv run mypy src tests
uv run pytest -q
```
