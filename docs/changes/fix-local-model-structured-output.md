---
status: ready
---

# fix-local-model-structured-output

**Identity:** Make `QuarantinedReader.read()` tolerate Ollama's prose / `<think>`-wrapped output (coerce-to-JSON before declaring `parse_failed`) and cap input length so a long email no longer overflows `qwen3:4b`'s context (the 400); gate Ollama-only request knobs (`num_ctx`, native `format`) in the shared adapter so cloud/Codex paths are untouched. Complements (does not duplicate) `fix-quarantine-transport-error` — both edit `quarantine.py:read()`; sequence this after it (or rebase the parse-path edit).

Primary fix = tolerant JSON coercion in the reader (backend-agnostic, the load-bearing change; a no-op on already-clean cloud JSON). Complementary fix = input truncation + Ollama-gated adapter knobs (kills the 400 / reduces prose). Option (a) "switch to Ollama native `/api/chat`" was rejected as too invasive for the shared adapter; we pass Ollama's native `format`/`options` as gated extras on the existing `/v1` body instead. Security note: coercion only reshapes text→JSON; the result still passes `_validate_extract_payload` and `flagged_injection` still blanks — the fail-closed posture is unchanged.

## Files to change

- `C:\Users\User\artemis\src\artemis\untrusted\quarantine.py` — modify
- `C:\Users\User\artemis\src\artemis\adapters\model_adapters.py` — modify
- `C:\Users\User\artemis\tests\test_untrusted.py` — modify
- `C:\Users\User\artemis\tests\test_model_adapters.py` — create

## Exact changes

### Task 1 — tolerant JSON coercion + input cap in `quarantine.py`

Add two module-level constants near `EXTRACTION_SCHEMA`:

```python
_MAX_RAW_CHARS = 12000  # input cap: keep the laundered body inside qwen3:4b's context
```

Add a conservative coercion helper (module-level, after `_validate_extract_payload`). It must be a strict superset of the current behaviour — when no `{` is present it returns the text unchanged so `json.loads` fails exactly as today (no regression, no weakening of fail-closed):

```python
import re

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _coerce_json_text(text: str) -> str:
    """Best-effort: strip <think> blocks / code fences, return the first balanced
    top-level {...}. Returns text unchanged when no object is found."""
    stripped = _FENCE_RE.sub("", _THINK_RE.sub("", text)).strip()
    start = stripped.find("{")
    if start == -1:
        return stripped
    depth = 0
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]
    return stripped
```

In `read()`: truncate before `spotlight()`:

```python
        safe_query = query.strip()[:512]
        nonce, marked = spotlight(raw_content[:_MAX_RAW_CHARS])
```

In the parse `try` block, coerce before `json.loads`:

```python
        try:
            parsed = json.loads(_coerce_json_text(resp.text))
            summary, claims, flagged_injection = _validate_extract_payload(parsed)
        except Exception as exc:
```

### Task 2 — Ollama-gated request knobs in `model_adapters.py`

Add a module-level constant and a pure detector near the top:

```python
_OLLAMA_NUM_CTX = 8192


def _is_ollama(base_url: str) -> bool:
    """True for the local Ollama dev endpoint (:11434); used to gate Ollama-only knobs."""
    return ":11434" in base_url
```

In `complete()`, after the `response_format` block (~line 79) and before the POST, add the gated extras. These fields are Ollama extensions; they are sent only when the endpoint is Ollama, so cloud / Codex (`responder_cloud`, DeepSeek) bodies are unchanged:

```python
        if _is_ollama(base_url):
            body["options"] = {"num_ctx": _OLLAMA_NUM_CTX}
            if response_schema is not None:
                body["format"] = response_schema  # Ollama native structured-output field
```

### Task 3 — tests in `test_untrusted.py`

Add `read()` coercion tests using the existing `FakeModelPort` pattern (a toolless fake whose `complete` returns a `ModelResponse` with a chosen `text`). Match the file's existing async runner.

- `test_read_coerces_think_wrapped_json`: model returns `"<think>reasoning…</think>\n```json\n{\"summary\":\"s\",\"claims\":[],\"flagged_injection\":false}\n```"` → assert `extract.usable is True`, `extract.parse_failed is False`, `extract.summary == "s"`.
- `test_read_coerces_prose_prefixed_json`: model returns `"Here is the result: {\"summary\":\"s\",\"claims\":[],\"flagged_injection\":false} thanks"` → assert `extract.parse_failed is False`.
- `test_read_no_json_still_parse_fails`: model returns `"sorry I cannot"` → assert `extract.parse_failed is True` (regression guard: coercion never masks a true non-JSON response).

### Task 4 — adapter gating test in `test_model_adapters.py`

New file. Unit-test the pure detector only (no live server):

```python
from artemis.adapters.model_adapters import _is_ollama


def test_is_ollama_true_for_local_dev_endpoint() -> None:
    assert _is_ollama("http://127.0.0.1:11434/v1") is True


def test_is_ollama_false_for_cloud_endpoints() -> None:
    assert _is_ollama("https://api.deepseek.com/v1") is False
    assert _is_ollama("http://127.0.0.1:8040/v1") is False
```

## Acceptance criteria

- Task 1: `uv run mypy src/artemis/untrusted/quarantine.py` clean; `_coerce_json_text("no braces")` returns `"no braces"` (no regression on non-JSON).
- Task 2: `uv run mypy src/artemis/adapters/model_adapters.py` clean; cloud/Codex bodies gain no `options`/`format` keys.
- Task 3: `uv run pytest -q tests/test_untrusted.py -k coerce` passes (think-wrapped and prose-prefixed JSON both parse; no-JSON still fails).
- Task 4: `uv run pytest -q tests/test_model_adapters.py` passes.

## Commands to run

```bash
uv run mypy
uv run pytest -q
```
