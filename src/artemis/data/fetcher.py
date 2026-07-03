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
            _log.warning("fetch_nonzero_exit capability=%s exit=%d", capability, result.exit_code)
            return None
        return await self._ingest.ingest_fetch_output(result.output, source=capability)

    async def dispatch(self, payload: dict[str, Any]) -> None:
        """Scheduler dispatch sink: interpret a {kind:'fetch', capability, args} job payload.

        A payload that is not a fetch job (or is malformed) is ignored -- composing dispatchers
        route non-fetch jobs elsewhere (Wave 2d)."""
        try:
            job = FetcherJob.model_validate(payload)
        except ValidationError:
            _log.warning("fetch_dispatch_bad_payload")
            return
        await self.run_fetch(job.capability, job.args)
