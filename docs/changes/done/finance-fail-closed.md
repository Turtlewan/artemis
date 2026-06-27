---
status: ready
weight: light
cross_model_review: false
---

# finance-fail-closed

Remove the Finance store's plaintext `except ImportError` fallback so it fails closed like every other owner-private SQLCipher store (ADR-033 encryption-at-rest; m2-win-a review item ①).

## Files to change

- `src/artemis/modules/finance/store.py` (modify)
- `tests/test_finance_core.py` (modify — add one fail-closed test)

## Exact changes

### 1. `src/artemis/modules/finance/store.py`

Hoist the `sqlcipher_open` import to module scope (matching `modules/productivity/store.py`) and drop the plaintext fallback in `_connect`.

Add to the top-level imports (alongside the existing `from artemis.config import Settings` block):

```python
from artemis.data.sqlcipher import sqlcipher_open
```

Replace the body of `_connect` between `db_path.parent.mkdir(...)` and `conn.execute("PRAGMA foreign_keys = ON")`:

```python
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from artemis.data.sqlcipher import sqlcipher_open

            conn = sqlcipher_open(db_path, key_hex)
        except ImportError:
            conn = sqlite3.connect(db_path)  # FALLBACK: no encryption -- CI/dev only
        conn.execute("PRAGMA foreign_keys = ON")
```

with:

```python
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher_open(db_path, key_hex)
        conn.execute("PRAGMA foreign_keys = ON")
```

Keep the `import sqlite3` at the top — it is still used by the `sqlite3.Connection` type annotations on `self._conn`, `_connect`, and `_get_conn`.

### 2. `tests/test_finance_core.py`

Add a test asserting that an absent SQLCipher binding fails closed (propagates `SqlCipherError`) and never silently falls back to plaintext. Monkeypatch the store's `sqlcipher_open` reference so the test is deterministic regardless of whether the real wheel is installed:

```python
def test_finance_store_fails_closed_without_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from artemis.data.sqlcipher import SqlCipherError

    def _no_binding(*_args: object, **_kwargs: object) -> object:
        raise SqlCipherError("sqlcipher3 binding not installed")

    monkeypatch.setattr(
        "artemis.modules.finance.store.sqlcipher_open", _no_binding
    )
    store = FinanceStore(Settings(data_root=tmp_path), FakeKeyProvider(owner_unlocked=True))
    with pytest.raises(SqlCipherError):
        store.list_accounts()
```

## Acceptance criteria

1. `rg "sqlite3.connect" src/artemis/modules/finance/store.py` returns no matches (plaintext fallback removed).
2. `uv run pytest -q tests/test_finance_core.py` — the new `test_finance_store_fails_closed_without_binding` passes and the existing round-trip/scope-lock tests stay green.
3. `uv run mypy` clean and full `uv run pytest -q` green (no regression).

## Commands to run

```bash
uv run ruff check src/artemis/modules/finance/store.py tests/test_finance_core.py
uv run mypy
uv run pytest -q
```
