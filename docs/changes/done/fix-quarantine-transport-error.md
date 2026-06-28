---
status: ready
---

# fix-quarantine-transport-error

**Identity:** Make `QuarantinedReader.read()` degrade a single message to a fail-closed blank Extract when the quarantine model call raises a transport/HTTP/timeout error, instead of crashing the whole batch.

## Files to change

- `C:\Users\User\artemis\src\artemis\untrusted\quarantine.py` — modify
- `C:\Users\User\artemis\tests\test_untrusted.py` — modify

## Exact changes

### Task 1 — wrap the model call in `quarantine.py`

Add `httpx` import alongside the existing stdlib imports (top of file, after `import logging`):

```python
import httpx
```

Replace the unguarded `await self._model.complete(...)` block (currently lines ~132-141) so the model call and the `tokens_used` read are inside a `try`/`except httpx.HTTPError`. On a transport error, log a distinct warning and return the same fail-closed blank Extract the JSON-parse path already returns (`parse_failed=True`, blanked summary/claims, `tokens_used=0`). Keep the existing JSON-parse `try`/`except` exactly as-is below it.

```python
        try:
            resp = await self._model.complete(
                role=self._role,
                messages=[
                    Message(role="system", content=system),
                    Message(role="user", content=marked),
                ],
                response_schema=EXTRACTION_SCHEMA,
                max_tokens=max_tokens,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "Quarantined extract transport failed (%s); degrading to blank extract",
                type(exc).__name__,
            )
            return Extract(
                source_url=source_url,
                source_domain=source_domain,
                summary="",
                claims=(),
                flagged_injection=False,
                parse_failed=True,
                tokens_used=0,
            )
        tokens_used = getattr(resp.usage, "total_tokens", 0) if resp.usage else 0
```

Rationale (one line, not for inline body): `httpx.HTTPError` is the base of `HTTPStatusError`/`TimeoutException`/`ConnectError` raised via `model_adapters.py:85` `raise_for_status()`; catching the base preserves the existing fail-closed posture (`parse_failed=True`) without a new dataclass field.

### Task 2 — add a unit test in `test_untrusted.py`

Add a fake model port whose `complete` raises an `httpx.HTTPError` (e.g. `httpx.HTTPStatusError` or `httpx.ConnectError`) with the same toolless signature as `FakeModelPort`, then assert `read()` returns a degraded Extract rather than raising:

```python
async def test_read_degrades_on_model_transport_error() -> None:
    class RaisingModelPort:
        async def complete(
            self,
            *,
            role: str,
            messages: Sequence[Message],
            response_schema: dict[str, object] | None = None,
            temperature: float = 0.7,
            max_tokens: int | None = None,
        ) -> ModelResponse:
            raise httpx.ConnectError("ollama down")

    reader = QuarantinedReader(RaisingModelPort(), role="quarantine")
    extract = await reader.read(
        raw_content="hello",
        source_url="https://x.test/p",
        source_domain="x.test",
        query="q",
    )
    assert extract.parse_failed is True
    assert extract.usable is False
    assert extract.summary == ""
    assert extract.tokens_used == 0
```

Add `import httpx` to the test module imports. Mark the test with the same async runner the file already uses (e.g. `@pytest.mark.asyncio` or `anyio`/`asyncio.run` — match the existing async tests in `test_untrusted.py`).

## Acceptance criteria

- Task 1: `uv run mypy src/artemis/untrusted/quarantine.py` is clean; a model `httpx.HTTPError` no longer propagates out of `read()`.
- Task 2: `uv run pytest -q tests/test_untrusted.py -k transport_error` passes (degraded Extract, no raise).

## Commands to run

```bash
uv run mypy
uv run pytest -q
```
