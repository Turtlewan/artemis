# fetcher-runner — run a fetcher capability into the store (Wave 2b)

**Identity:** The scheduler dispatch sink that runs a fetcher capability in the isolate (same
resolve-secrets + mint-and-inject-OAuth path as invoke) and routes its stdout to `IngestService`
instead of the owner-facing quarantine. ADR-046 #1. Depends on `data-ingest` (shipped) +
`fetch_sandbox`/`invoke` helpers.

Reuses the importable helpers `missing_required_secrets` / `resolve_secret_values` /
`build_invoke_argv` and `oauth_broker.mint_access_token` — `invoke.py` is left untouched (the
~15-line OAuth mint/inject overlap is a deliberate duplication, not a refactor of the
security-reviewed invoke path; a later consolidation is a follow-up). Fail-soft everywhere (a
background sync must never crash the loop): any missing capability/secret/OAuth, sandbox error, or
non-zero exit returns `None` (logged), ingesting nothing. Dead-until-consumed: the scheduler loop +
job registration are Wave 2d; this spec adds the runner + tests only.

## Files to change
| Op | Path |
|----|------|
| create | `src/artemis/data/fetcher.py` |
| create | `tests/data/test_fetcher.py` |

## Exact changes

### Task 1 — `src/artemis/data/fetcher.py` (create)
Full module:

```python
"""Scheduled fetcher runner for the local data spine (ADR-046 #1).

Runs a fetcher capability in the isolate (the same resolve-secrets + mint-and-inject-OAuth path as
invoke), then routes its stdout to IngestService instead of the owner-facing quarantine. A fetcher
prints one JSON object {domain, rows} on stdout (artemis.data.ingest.FetcherOutput).

Fail-soft: a background sync must never crash the scheduler loop, so any failure to run returns
None (logged) and ingests nothing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from artemis.capabilities.fetch_sandbox import (
    FetchSandbox,
    missing_required_secrets,
    resolve_secret_values,
)
from artemis.data.ingest import IngestResult, IngestService
from artemis.ports.capabilities import CapabilityStore
from artemis.ports.secrets import SecretStorePort
from artemis.types import build_invoke_argv

_log = logging.getLogger(__name__)


class _OAuthMinter(Protocol):
    async def mint_access_token(self, account: str, scope: str) -> str: ...


class FetcherJob(BaseModel):
    """The scheduler payload for a fetcher run."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["fetch"] = "fetch"
    capability: str
    args: dict[str, Any] = Field(default_factory=dict)


class FetcherRunner:
    """Run a fetcher capability and ingest its rows into the local store."""

    def __init__(
        self,
        *,
        capability_store: CapabilityStore,
        secrets_store: SecretStorePort,
        sandbox: FetchSandbox,
        ingest: IngestService,
        oauth_broker: _OAuthMinter | None = None,
    ) -> None:
        self._store = capability_store
        self._secrets = secrets_store
        self._sandbox = sandbox
        self._ingest = ingest
        self._oauth = oauth_broker

    async def run_fetch(self, capability: str, args: dict[str, Any]) -> IngestResult | None:
        """Run a fetcher capability and ingest its output. None (logged) if it could not run
        (missing capability/secrets/OAuth, sandbox error, or non-zero exit)."""
        skill = self._store.get(capability)
        if skill is None:
            _log.warning("fetch_capability_not_found capability=%s", capability)
            return None
        if missing_required_secrets(skill.secrets, self._secrets):
            _log.warning("fetch_missing_secrets capability=%s", capability)
            return None
        try:
            resolved = resolve_secret_values(skill.secrets, self._secrets)
        except ValueError:
            _log.warning("fetch_secret_resolve_failed capability=%s", capability)
            return None
        if skill.oauth_scopes:
            if self._oauth is None:
                _log.warning("fetch_oauth_unavailable capability=%s", capability)
                return None
            try:
                token = ""
                for scope in skill.oauth_scopes:
                    token = await self._oauth.mint_access_token("default", scope)
            except Exception:
                _log.warning("fetch_oauth_mint_failed capability=%s", capability)
                return None
            resolved["GOOGLE_ACCESS_TOKEN"] = token
        argv = build_invoke_argv(skill.inputs, args)
        try:
            result = await self._sandbox.run(
                Path(skill.path),
                entrypoint="tool.py",
                argv=argv,
                egress_domains=skill.egress_domains,
                secrets=resolved,
            )
        except Exception:
            _log.warning("fetch_sandbox_failed capability=%s", capability)
            return None
        if result.exit_code != 0:
            _log.warning(
                "fetch_nonzero_exit capability=%s exit=%d", capability, result.exit_code
            )
            return None
        return await self._ingest.ingest_fetch_output(result.output, source=capability)

    async def dispatch(self, payload: dict[str, Any]) -> None:
        """Scheduler dispatch sink: interpret a {kind:'fetch', capability, args} job payload.

        A payload that is not a fetch job (or is malformed) is ignored — composing dispatchers
        route non-fetch jobs elsewhere (Wave 2d)."""
        try:
            job = FetcherJob.model_validate(payload)
        except ValidationError:
            _log.warning("fetch_dispatch_bad_payload")
            return
        await self.run_fetch(job.capability, job.args)
```

### Task 2 — `tests/data/test_fetcher.py` (create)
Re-declare compact fakes in-module (do NOT import from `tests/capabilities/`). Mirror
`tests/capabilities/test_invoke.py`'s `RecordingSandbox` (subclass `FetchSandbox`, record calls,
optional `raises`), `FakeCapabilityStore.get`, `FakeSecretStore`, `FakeOAuthBroker`, and its
`_skill(...)` builder (all `Skill` fields: name/description/version/path/tags/uses/secrets/
oauth_scopes/inputs/egress_domains). The ingest half is a REAL `IngestService(DataStore(),
reader=FakeReader())` (FakeReader as in `tests/data/test_ingest.py`, returning a fixed `sanitized`)
so tests assert real rows land in the store. Cover:

```python
def _fetch_output(domain="calendar"):
    return json.dumps({"domain": domain, "rows": [
        {"kind": "event", "key": "e1", "payload": {"start": "2026-08-22T09:00"}, "text": "Standup 9am"},
    ]})

# 1. plain fetcher (no secrets/oauth) runs -> ingests; sandbox called with egress + tool.py
async def test_run_fetch_ingests_rows():
    store = DataStore()
    ingest = IngestService(store, reader=FakeReader(sanitized="Standup 9am on 2026-08-22"))
    sandbox = RecordingSandbox(FetchResult(output=_fetch_output(), exit_code=0, truncated=False))
    runner = FetcherRunner(capability_store=FakeCapabilityStore(_skill(egress_domains=["www.googleapis.com"])),
                           secrets_store=FakeSecretStore({}), sandbox=sandbox, ingest=ingest)
    result = await runner.run_fetch("Echo", {})
    assert result is not None and result.ingested == 1
    rec = store.get("calendar", "event", "e1")
    assert rec is not None and rec.sanitized_text == "Standup 9am on 2026-08-22"
    assert rec.source == "Echo"
    assert sandbox.calls[0].entrypoint == "tool.py"
    assert sandbox.calls[0].egress_domains == ["www.googleapis.com"]

# 2. oauth fetcher mints + injects GOOGLE_ACCESS_TOKEN into sandbox secrets
async def test_run_fetch_injects_oauth_token():
    store = DataStore()
    ingest = IngestService(store, reader=FakeReader())
    sandbox = RecordingSandbox(FetchResult(output=_fetch_output(), exit_code=0, truncated=False))
    broker = FakeOAuthBroker(token="ya29.tok")
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(_skill(oauth_scopes=["https://www.googleapis.com/auth/calendar.readonly"])),
        secrets_store=FakeSecretStore({}), sandbox=sandbox, ingest=ingest, oauth_broker=broker)
    await runner.run_fetch("Echo", {})
    assert broker.calls == [("default", "https://www.googleapis.com/auth/calendar.readonly")]
    assert sandbox.calls[0].secrets is not None
    assert sandbox.calls[0].secrets.get("GOOGLE_ACCESS_TOKEN") == "ya29.tok"

# 3-8: fail-soft None paths (assert None + nothing ingested):
#   - missing capability (FakeCapabilityStore(None))
#   - missing required secret (skill secrets=["API_KEY"], FakeSecretStore({"API_KEY": None}))
#   - oauth scope declared but oauth_broker=None
#   - oauth mint raises (FakeOAuthBroker(raises_for={scope}))
#   - sandbox raises (RecordingSandbox(raises=RuntimeError()))
#   - non-zero exit (FetchResult(output=..., exit_code=1, truncated=False))
# 9. dispatch routes a valid {kind:'fetch', capability, args} payload; a bad payload is a no-op (no raise)
async def test_dispatch_bad_payload_is_noop():
    runner = FetcherRunner(capability_store=FakeCapabilityStore(None), secrets_store=FakeSecretStore({}),
                           sandbox=RecordingSandbox(), ingest=IngestService(DataStore(), reader=FakeReader()))
    await runner.dispatch({"not": "a fetch job"})  # must not raise
```

## Acceptance criteria
1. `run_fetch` on a plain fetcher runs the sandbox (`entrypoint="tool.py"`, `egress_domains` from the skill) and ingests the emitted rows into the store; `source` = the capability name. → `test_run_fetch_ingests_rows`
2. An OAuth fetcher mints a token per declared scope and injects it as `GOOGLE_ACCESS_TOKEN` into the sandbox `secrets` (never into args/logs). → `test_run_fetch_injects_oauth_token`
3. Each fail-soft path returns `None` and ingests nothing: missing capability; missing required secret; OAuth declared but no broker; mint raises; sandbox raises; non-zero exit. → six tests
4. `dispatch` runs a valid fetch payload and is a no-op on a malformed payload (never raises). → `test_dispatch_*`
5. Whole-project `uv run mypy src/` clean (strict), `uv run ruff check` clean, full suite green.

## Commands to run
```
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -q tests/data/
uv run pytest -q
```
