---
spec: provider-usage-parse
status: draft
token_profile: lean
autonomy_level: L3
coder_tier: codex
---

# Spec: provider-usage-parse — real token counts in `ModelResponse.usage` (codex + claude-code)

**Identity:** Populate `ModelResponse.usage` with real prompt/completion tokens parsed from the codex
and claude-code CLI outputs, so the model-role meter's token columns read real numbers instead of the
fabricated `Usage(0,0,0)`. Parse-and-populate only — no change to text/schema handling.
→ consumer: docs/changes/model-role-metering.md "Open items flagged #1" (token counts currently zero).

AI-systems review 2026-07-04: findings folded — 2 FLAGs + 1 note (negative-int guard parity on the
codex path; cache tokens kept distinct via new `Usage` fields, never folded into `prompt_tokens`;
codex live smoke upgraded to an env-gated real-call pytest).

## Design (grounded — verified against the real code)

- `RawProvider.generate` (Protocol in `codex_provider.py`) returns `str`; its ONLY consumer is
  `ModelClient.complete`, which builds `ModelResponse` with a hard-coded `Usage(0,0,0)` (client.py
  lines 51 and 71). `reachout/web_tool.py` and `api/app.py` go through `ModelClient`, never raw
  `.generate` — verified `grep '\.generate('` hits only client.py.
- **Minimal seam:** widen the Protocol return to `str | Generation` (a new frozen result carrying
  `text` + `usage`). Return types are **covariant**, so a provider whose `generate` still returns a
  plain `str` (anthropic, ollama, and the tests' `FakeProvider(RawProvider)`) **continues to satisfy
  the Protocol unchanged** and falls through to zero usage. Only codex + claude return `Generation`.
  This is why anthropic/ollama need no edit (see "Out of scope").
- claude-code: the JSON envelope already parsed by `_extract_result` (`json.loads(stdout)`) carries a
  sibling `usage` object — extract it from the SAME decoded envelope; no invocation change.
- codex: current invocation reads final text from the `-o` file and **discards stdout**. Add `--json`
  (verified via `codex exec --help`: "Print events to stdout as JSONL"; coexists with `-o`, which
  still writes the clean final message to the file — text extraction is unaffected) and parse token
  totals from the now-captured stdout event stream, fail-soft.
- Fail-soft everywhere: a missing/unparseable usage block yields `Usage(0,0,0)`, never raises.

## Files to change
| # | File | Op | What |
|---|------|----|------|
| 0 | `src/artemis/types.py` | modify | Add `cache_read_tokens: int = 0` + `cache_creation_tokens: int = 0` to `Usage` — defaults keep every existing constructor call valid (zero mypy ripple). |
| 1 | `src/artemis/model/codex_provider.py` | modify | Add `Generation` frozen dataclass; widen `RawProvider.generate -> str \| Generation`; add `--json` to argv; capture+parse stdout token stream (`_parse_codex_usage`, `>= 0` guarded); return `Generation`. |
| 2 | `src/artemis/model/claude_code_provider.py` | modify | Add `_extract_usage` (reads the `usage` sibling of the JSON envelope; cache fields kept distinct); return `Generation`. |
| 3 | `src/artemis/model/client.py` | modify | `_split(result) -> (text, Usage)`; populate `ModelResponse.usage` on both the schema and non-schema paths. |
| 4 | `tests/model/test_codex_provider.py` | modify | Update the one return-value assertion to `.text`; add `--json` to the expected-argv test; add usage-parsed + absent→zeros + negative→zeros cases; env-gated live smoke. |
| 5 | `tests/model/test_claude_code_provider.py` | modify | Update `.generate()` return assertions to `.text`; add usage-in-envelope (cache split asserted) + missing-usage→zeros cases. |
| 6 | `tests/test_model_client.py` | modify | Add a `Generation`-returning fake → usage flows through; assert the existing `str` fake path yields zeros. |

> **⚠️ Scope flag (grows past ≤4):** lands at **7 files (4 source + 3 test)**. Usage is a cross-cutting
> seam — the shared `generate` return contract is touched once, two providers parse it, the client
> normalizes it, and each provider's existing test asserts on the (now-`Generation`) return so all
> three test files must update those assertions. The `types.py` touch is two defaulted fields (review
> FLAG 2 — preserve the cache distinction end-to-end). Not splittable below this without leaving the
> meter half-zero. `Generation` is homed in `codex_provider.py` beside the `RawProvider` Protocol it
> is returned from (avoids a fifth source file).

## Exact changes

### Task 0 — `src/artemis/types.py` (modify)

Extend `Usage` with defaulted cache fields (review FLAG 2). Defaults keep every existing
`Usage(prompt_tokens=..., completion_tokens=..., total_tokens=...)` call site valid — confirmed the
only constructors are in `client.py` (this spec rewrites them) and tests; mypy ripple is nil.
```python
class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
```
**Semantics (explicit formula):** `prompt_tokens` = non-cached input tokens only; cache fields are
NOT folded in. `total_tokens = prompt_tokens + cache_read_tokens + cache_creation_tokens +
completion_tokens` — i.e. the sum of ALL input (cached + non-cached) + output; its meaning is
unchanged from "everything in + everything out".

### Task 1 — `src/artemis/model/codex_provider.py` (modify)

**a.** Add imports (top, with existing):
```python
from dataclasses import dataclass
from artemis.types import Message, Usage
```

**b.** Add the shared result type ABOVE `class RawProvider` and widen the Protocol return:
```python
@dataclass(frozen=True)
class Generation:
    """A raw provider reply plus parsed token usage. Providers that don't parse usage return a
    plain ``str`` instead (covariant with ``str | Generation``) and the client fills zeros."""

    text: str
    usage: Usage


class RawProvider(Protocol):
    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict | None,  # type: ignore[type-arg]
    ) -> str | Generation:
        """Generate final assistant text, optionally with parsed usage."""
        ...
```

**c.** In `_build_argv`, insert `--json` right after `--color never` (before `-o`):
```python
            "--color",
            "never",
            "--json",
            "-o",
            str(output_path),
```

**d.** In `generate`, capture stdout (currently `_stdout`) and return a `Generation`:
```python
            returncode, stdout, stderr = await cli_support.run_cli(
                argv,
                stdin=cli_support.render_messages(messages).encode("utf-8"),
                env={**os.environ, CODEX_SPAWN_MARKER: "1"},
                timeout=self._timeout,
            )
```
…and replace the final `return output_path.read_text(...).strip()` with:
```python
            text = output_path.read_text(encoding="utf-8").strip()
            usage = _parse_codex_usage(stdout.decode("utf-8", errors="replace"))
            return Generation(text=text, usage=usage)
```

**e.** Add the fail-soft parser (module-level, near the bottom):
```python
def _parse_codex_usage(stdout_text: str) -> Usage:
    """Best-effort token totals from the codex ``--json`` JSONL stream; fail-soft to zeros.

    Scans each line for a token-usage object (prefers a ``total_token_usage`` block, else any object
    with integer input_tokens/output_tokens) and keeps the LAST match so cumulative end-of-run
    totals win. An empty/unknown stream yields zeros — never raises.
    """
    best: Usage | None = None
    for raw_line in stdout_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = _find_token_usage(event)
        if found is not None:
            best = found
    return best or Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def _find_token_usage(node: object) -> Usage | None:
    if isinstance(node, dict):
        total = node.get("total_token_usage")
        if isinstance(total, dict):
            pair = _usage_from_pair(total)
            if pair is not None:
                return pair
        pair = _usage_from_pair(node)
        if pair is not None:
            return pair
        for value in node.values():
            nested = _find_token_usage(value)
            if nested is not None:
                return nested
    elif isinstance(node, list):
        for item in node:
            nested = _find_token_usage(item)
            if nested is not None:
                return nested
    return None


def _usage_from_pair(node: dict[str, object]) -> Usage | None:
    """Same non-negative-int guard as the claude path's ``_int`` — a malformed negative token
    field disqualifies the pair, degrading to zeros rather than recording garbage."""
    inp = node.get("input_tokens")
    out = node.get("output_tokens")
    if (
        isinstance(inp, int)
        and not isinstance(inp, bool)
        and inp >= 0
        and isinstance(out, int)
        and not isinstance(out, bool)
        and out >= 0
    ):
        return Usage(prompt_tokens=inp, completion_tokens=out, total_tokens=inp + out)
    return None
```

> **Build-time verification (do NOT skip):** the exact codex `--json` token-event field path is not
> confirmable from the source alone. Run the env-gated live smoke (Task 4f: `ARTEMIS_LIVE_SMOKE=1`)
> and confirm `usage.total_tokens > 0` on a real call — adjust the key names in
> `_usage_from_pair`/`_find_token_usage` if the live schema differs. The structural scan tolerates
> flat vs `msg`/`info`-wrapped envelopes; only the leaf field names are the risk.

### Task 2 — `src/artemis/model/claude_code_provider.py` (modify)

**a.** Add imports:
```python
from artemis.model.codex_provider import Generation
from artemis.types import Message, Usage
```
(`Message` is already imported — merge; do not duplicate.)

**b.** Change the tail of `generate` to return a `Generation` (parse usage from the SAME `text`
envelope, before extraction):
```python
        result = _extract_result(text)
        final_text = _strip_code_fence(result) if schema is not None else result
        return Generation(text=final_text, usage=_extract_usage(text))
```

**c.** Add the fail-soft usage extractor (module-level, near `_extract_result`):
```python
def _extract_usage(stdout: str) -> Usage:
    """Read the ``usage`` sibling of the claude ``--output-format json`` envelope; fail-soft to zeros.

    Cache tokens stay DISTINCT (never folded into prompt_tokens): prompt = non-cached input only;
    total = prompt + cache_read + cache_creation + completion (all input + output).
    """
    zero = Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        return zero
    if not isinstance(value, dict):
        return zero
    raw = value.get("usage")
    if not isinstance(raw, dict):
        return zero

    def _int(key: str) -> int:
        v = raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0

    prompt = _int("input_tokens")
    cache_read = _int("cache_read_input_tokens")
    cache_creation = _int("cache_creation_input_tokens")
    completion = _int("output_tokens")
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + cache_read + cache_creation + completion,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
    )
```

### Task 3 — `src/artemis/model/client.py` (modify)

**a.** Import `Generation`:
```python
from artemis.model.codex_provider import Generation, RawProvider
```

**b.** Add a normalizer (module-level, near `_ensure_structured`):
```python
def _split(result: str | Generation) -> tuple[str, Usage]:
    if isinstance(result, Generation):
        return result.text, result.usage
    return result, Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
```

**c.** Non-schema path — replace lines 45-52 body:
```python
        if response_schema is None:
            raw = await self._provider.generate(messages=messages, model=model_id, schema=None)
            text, usage = _split(raw)
            return ModelResponse(
                text=text,
                model_id=model_id,
                structured=None,
                finish_reason="stop",
                usage=usage,
            )
```

**d.** Schema path — inside the loop, split before parsing; parse/return use `text` and `usage`
(the reask error branch is UNCHANGED — it keys off `exc`, not the raw string):
```python
            raw = await self._provider.generate(
                messages=attempt_messages,
                model=model_id,
                schema=response_schema,
            )
            text, usage = _split(raw)
            try:
                parsed = json.loads(text)
                jsonschema.validate(instance=parsed, schema=response_schema)
                structured = _ensure_structured(parsed)
                return ModelResponse(
                    text=text,
                    model_id=model_id,
                    structured=structured,
                    finish_reason="stop",
                    usage=usage,
                )
```

### Task 4 — `tests/model/test_codex_provider.py` (modify)

**a.** `test_codex_provider_resolves_binary_and_builds_expected_argv` — insert `"--json"` between
`"never"` and `"-o"` in the expected list.

**b.** `test_codex_provider_strictifies_schema_internally` — the fake writes `{"answer":"ok"}` to the
output file and returns `(0, b"", b"")`; change `assert result == '{"answer":"ok"}'` to
`assert result.text == '{"answer":"ok"}'` and add `assert result.usage.total_tokens == 0` (empty
stdout → zeros).

**c.** Add a usage-parsed case (realistic JSONL on stdout; text from the `-o` file):
```python
@pytest.mark.asyncio
async def test_codex_provider_parses_usage_from_json_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = (
        b'{"id":"0","msg":{"type":"agent_message","text":"hi"}}\n'
        b'{"id":"1","msg":{"type":"token_count","info":{"total_token_usage":'
        b'{"input_tokens":1200,"cached_input_tokens":256,"output_tokens":340,"total_tokens":1540}}}}\n'
    )

    async def fake_run_cli(argv, *, stdin, env=None, timeout=None):  # type: ignore[no-untyped-def]
        del stdin, env, timeout
        Path(argv[argv.index("-o") + 1]).write_text("hi", encoding="utf-8")
        return (0, stream, b"")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    result = await CodexProvider(binary="codex-test").generate(
        messages=[Message(role="user", content="hello")], model="", schema=None
    )
    assert result.text == "hi"
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (1200, 340)
    assert result.usage.total_tokens == 1540
```

**d.** Add an absent-usage → zeros case (stdout has no token event):
```python
@pytest.mark.asyncio
async def test_codex_provider_usage_falls_back_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_cli(argv, *, stdin, env=None, timeout=None):  # type: ignore[no-untyped-def]
        del stdin, env, timeout
        Path(argv[argv.index("-o") + 1]).write_text("hi", encoding="utf-8")
        return (0, b'{"id":"0","msg":{"type":"agent_message","text":"hi"}}\n', b"")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    result = await CodexProvider(binary="codex-test").generate(
        messages=[Message(role="user", content="hello")], model="", schema=None
    )
    assert result.text == "hi"
    assert result.usage.total_tokens == 0
```

**e.** Add a negative-token → zeros case (review FLAG 1 — guard parity with the claude path):
```python
@pytest.mark.asyncio
async def test_codex_provider_negative_tokens_degrade_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = (
        b'{"id":"1","msg":{"type":"token_count","info":{"total_token_usage":'
        b'{"input_tokens":-5,"output_tokens":340}}}}\n'
    )

    async def fake_run_cli(argv, *, stdin, env=None, timeout=None):  # type: ignore[no-untyped-def]
        del stdin, env, timeout
        Path(argv[argv.index("-o") + 1]).write_text("hi", encoding="utf-8")
        return (0, stream, b"")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    result = await CodexProvider(binary="codex-test").generate(
        messages=[Message(role="user", content="hello")], model="", schema=None
    )
    assert result.text == "hi"
    assert result.usage == Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
```

**f.** Add an env-gated LIVE smoke that actually runs one real codex call (add `import os` and extend
the existing imports with `Generation` / `Usage` from their modules). The default suite stays
hermetic — the test is skipped with a documented reason unless `ARTEMIS_LIVE_SMOKE=1`:
```python
@pytest.mark.skipif(
    os.environ.get("ARTEMIS_LIVE_SMOKE") != "1",
    reason=(
        "live smoke (set ARTEMIS_LIVE_SMOKE=1): runs one real codex call to verify the --json "
        "token-event field path — usage.total_tokens must be > 0"
    ),
)
@pytest.mark.asyncio
async def test_codex_provider_usage_live_smoke() -> None:
    result = await CodexProvider().generate(
        messages=[Message(role="user", content="say OK")], model="gpt-5.5", schema=None
    )
    assert isinstance(result, Generation)
    assert result.usage.total_tokens > 0
```

### Task 5 — `tests/model/test_claude_code_provider.py` (modify)

**a.** `test_generate_defences_structured_output` — `with_schema`/`without_schema` are now
`Generation`; change to `json.loads(with_schema.text)` and `without_schema.text.startswith("```json")`.

**b.** `test_claude_provider_argv_json_output_and_clean_config` — change `assert result == "hi"` to
`assert result.text == "hi"`.

**c.** Add usage-in-envelope + missing-usage cases:
```python
@pytest.mark.asyncio
async def test_claude_provider_parses_usage_from_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    _write_dummy_credentials(home)
    _patch_home(monkeypatch, home)

    async def fake_run_cli(argv, *, stdin, env=None, timeout=None):  # type: ignore[no-untyped-def]
        del argv, stdin, env, timeout
        return (
            0,
            b'{"result":"hi","usage":{"input_tokens":90,"cache_read_input_tokens":10,'
            b'"output_tokens":25}}',
            b"",
        )

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    result = await ClaudeCodeProvider(binary="claude-test").generate(
        messages=[Message(role="user", content="hi")], model="", schema=None
    )
    assert result.text == "hi"
    # cache split preserved: prompt = non-cached input ONLY; total = all input + output
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (90, 25)
    assert result.usage.cache_read_tokens == 10
    assert result.usage.cache_creation_tokens == 0
    assert result.usage.total_tokens == 125


@pytest.mark.asyncio
async def test_claude_provider_usage_missing_falls_back_to_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    _write_dummy_credentials(home)
    _patch_home(monkeypatch, home)

    async def fake_run_cli(argv, *, stdin, env=None, timeout=None):  # type: ignore[no-untyped-def]
        del argv, stdin, env, timeout
        return (0, b'{"result":"hi"}', b"")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    result = await ClaudeCodeProvider(binary="claude-test").generate(
        messages=[Message(role="user", content="hi")], model="", schema=None
    )
    assert result.text == "hi"
    assert result.usage.total_tokens == 0
```

### Task 6 — `tests/test_model_client.py` (modify)

Add a `Generation`-returning fake and assert usage flows through; assert the existing `str` fake
yields zeros. `FakeProvider` (returns `str`) is UNCHANGED and its existing tests still pass.
```python
from artemis.model.codex_provider import Generation
from artemis.types import Usage


class UsageProvider(RawProvider):
    async def generate(self, *, messages, model, schema):  # type: ignore[no-untyped-def]
        del messages, model, schema
        return Generation(
            text='{"answer": "ok"}',
            usage=Usage(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        )


@pytest.mark.asyncio
async def test_generation_usage_flows_into_response() -> None:
    client = ModelClient(UsageProvider())
    resp = await client.complete(
        messages=[Message(role="user", content="q")], response_schema=_answer_schema()
    )
    assert resp.structured == {"answer": "ok"}
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.total_tokens) == (
        11,
        7,
        18,
    )


@pytest.mark.asyncio
async def test_str_provider_yields_zero_usage() -> None:
    resp = await ModelClient(FakeProvider(['{"answer": "ok"}'])).complete(
        messages=[Message(role="user", content="q")], response_schema=_answer_schema()
    )
    assert resp.usage.total_tokens == 0
```

## Out of scope (one line each)
- **anthropic** — usage IS trivially available (`response.usage.input_tokens` / `output_tokens` on the
  SDK `Message`), but wiring it means returning `Generation` from its `generate`; the covariant `str`
  return keeps it correct-at-zero with no edit. Follow-up: same one-line `Generation(...)` return.
- **ollama** — usage IS trivially available (`prompt_eval_count` / `eval_count` in the `/api/chat`
  JSON), same follow-up shape. Left at zeros here to hold the file budget.

## Acceptance criteria
1. codex usage parses → `uv run pytest -q tests/model/test_codex_provider.py` passes (incl. the new
   JSONL-stream case → `(1200, 340, 1540)`, absent-usage → zeros, negative-token → zeros (guard
   parity), updated argv with `--json`).
2. claude usage parses with the cache split → `uv run pytest -q tests/model/test_claude_code_provider.py`
   passes (envelope `usage` → prompt `90`, completion `25`, `cache_read_tokens == 10`,
   `cache_creation_tokens == 0`, total `125`; missing `usage` → zeros; `.text` return assertions).
3. usage flows through the client → `uv run pytest -q tests/test_model_client.py` passes (Generation
   fake → `(11, 7, 18)`; str fake → zeros).
4. No behavior change to text/schema → full suite green: `uv run pytest -q` (the env-gated live smoke
   reports SKIPPED — default suite stays hermetic).
5. Fail-soft is real → `_parse_codex_usage("")`, a negative-token stream, and
   `_extract_usage('{"result":"x"}')` all yield zero `Usage` and never raise (covered by criteria
   1-2's zero cases).
6. Type + lint clean → `uv run mypy` clean (covariant `str | Generation` return; `FakeProvider`'s
   `str` still satisfies the widened Protocol; the two defaulted `Usage` fields ripple nowhere) and
   `uv run ruff check .` + `uv run ruff format --check .`.
7. Surgical → `git diff --stat` shows only the seven files above.
8. **Live-verify codex schema** (build step, not CI) →
   `ARTEMIS_LIVE_SMOKE=1 uv run pytest -q tests/model/test_codex_provider.py -k live_smoke` passes
   (one real codex call, `usage.total_tokens > 0`); if it fails, adjust the leaf field names in
   `_usage_from_pair` / `_find_token_usage` and re-run criteria 1 + 8.

## Commands to run
```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q tests/model/test_codex_provider.py tests/model/test_claude_code_provider.py tests/test_model_client.py
uv run pytest -q
```

## Open items flagged (planning)
1. **codex `--json` token-event schema is not source-confirmable** — parser is structural + fail-soft,
   but the leaf field names (`total_token_usage`/`input_tokens`/`output_tokens`) must be live-verified
   at build (Task 1 note + criterion 8). Worst case if unverified: codex usage stays zero (no breakage).
2. **cache-token distinction preserved but not yet consumed** — `Usage` now carries
   `cache_read_tokens` / `cache_creation_tokens` (review FLAG 2), so a future meter cost column can
   price cached tokens separately with no parse change; today's meter reads only prompt/completion.
   Codex's stream may also expose a cached-input figure (`cached_input_tokens` appears in the fixture)
   — wiring it in is a follow-up once the live smoke confirms the field name.
3. **anthropic/ollama left at zeros** — deliberate (see Out of scope); a 2-file follow-up finishes the
   set once the seam here is proven.
