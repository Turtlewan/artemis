---
status: ready
---

# fix-google-auth-scope-registration

**Identity:** Make `artemis-google-auth login` register connector OAuth scopes before computing `required_scopes()`, so the standalone CLI grants the gmail + calendar union instead of bailing with "no scopes".

## Files to change

- `C:\Users\User\artemis\src\artemis\modules\calendar\__init__.py` — modify
- `C:\Users\User\artemis\src\artemis\integrations\google\cli.py` — modify
- `C:\Users\User\artemis\tests\test_google_auth.py` — modify

## Exact changes

Chosen approach (justification, not for inline body): the registry is process-local and `clear_registry()` wipes import-time registrations, so relying on import side-effects is not testable. Give each connector an explicit, idempotent `register_*` function and call both from the CLI before reading scopes. Gmail already exposes `register_gmail_scope()`; calendar only registers inline at module top-level — wrap that in a function and call it from the CLI for parity.

### Task 1 — explicit calendar registration function in `calendar\__init__.py`

Replace the top-level `register_google_scopes("calendar", {...})` call (currently lines ~37-42) with a named function plus a top-level call to it (preserves import-time behaviour):

```python
def register_calendar_scopes() -> None:
    """Register the Calendar OAuth scope (idempotent)."""
    register_google_scopes(
        "calendar",
        {
            "https://www.googleapis.com/auth/calendar.readonly",
        },
    )


register_calendar_scopes()
```

Add `"register_calendar_scopes"` to `__all__`.

### Task 2 — trigger registration in `cli.py` before login

Add a private helper and call it inside the `login` branch before `required_scopes()` is read (current line ~59):

```python
def _register_connector_scopes() -> None:
    """Register every connector's Google scopes into the process-local registry."""
    from artemis.modules.calendar import register_calendar_scopes
    from artemis.modules.gmail.module import register_gmail_scope

    register_gmail_scope()
    register_calendar_scopes()
```

In the `login` branch, before the `scopes = tuple(...)` line:

```python
    if args.command == "login":
        _register_connector_scopes()
        scopes = tuple(args.scope or sorted(required_scopes()))
```

Imports stay local to the helper to avoid import cycles at module top-level.

### Task 3 — test the CLI registration path in `test_google_auth.py`

The module already has the autouse `clear_registry()` fixture. Add a test asserting that after the CLI registration path runs, `required_scopes()` includes the gmail readonly scope:

```python
def test_cli_registers_connector_scopes_for_login() -> None:
    from artemis.integrations.google.cli import _register_connector_scopes
    from artemis.modules.gmail.client import GMAIL_READONLY_SCOPE

    _register_connector_scopes()
    scopes = required_scopes()
    assert GMAIL_READONLY_SCOPE in scopes
    assert "https://www.googleapis.com/auth/calendar.readonly" in scopes
```

## Acceptance criteria

- Task 1: `uv run pytest -q tests/test_google_auth.py` still passes; `register_calendar_scopes` importable from `artemis.modules.calendar`.
- Task 2: `uv run mypy src/artemis/integrations/google/cli.py` clean.
- Task 3: `uv run pytest -q tests/test_google_auth.py -k cli_registers` passes (gmail.readonly present after CLI registration).

## Commands to run

```bash
uv run mypy
uv run pytest -q
```

## Doc follow-up (do NOT change here)

`calendar\__init__.py` registers `calendar.events` write scope? No — it currently registers `calendar.readonly`. However the activation runbook's "read-only" claim should be re-verified against the live composition root, since `make_calendar_manifest` wires write tools (create-from-extract). Flag for a docs pass; out of scope for this spec.
