from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pytest

from artemis.capabilities.fetch_sandbox import FetchResult, FetchSandbox
from artemis.data.fetcher import FetcherRunner
from artemis.data.ingest import IngestService
from artemis.data.store import DataStore
from artemis.types import (
    Message,
    ModelResponse,
    Skill,
    SkillDraft,
    SkillInputParam,
    StagedSkill,
    Usage,
)


class FakeCapabilityStore:
    def __init__(self, skill: Skill | None) -> None:
        self._skill = skill
        self.get_calls: list[str] = []

    async def stage(self, draft: SkillDraft) -> StagedSkill:
        raise NotImplementedError

    async def promote(self, staged_id: str) -> Skill:
        raise NotImplementedError

    async def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        tags: Sequence[str] | None = None,
    ) -> list[Skill]:
        del query, k, tags
        return []

    def get(self, name: str) -> Skill | None:
        self.get_calls.append(name)
        if self._skill is not None and self._skill.name == name:
            return self._skill
        return None


class FakeSecretStore:
    def __init__(self, values: dict[str, str | None]) -> None:
        self.values = dict(values)
        self.list_calls = 0
        self.get_calls: list[str] = []

    def get(self, name: str) -> str | None:
        self.get_calls.append(name)
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)

    def list_names(self) -> list[str]:
        self.list_calls += 1
        return sorted(self.values)


class SandboxCall:
    def __init__(
        self,
        *,
        capability_dir: Path,
        entrypoint: str,
        argv: list[str],
        egress_domains: list[str],
        secrets: dict[str, str] | None,
    ) -> None:
        self.capability_dir = capability_dir
        self.entrypoint = entrypoint
        self.argv = argv
        self.egress_domains = egress_domains
        self.secrets = secrets


class RecordingSandbox(FetchSandbox):
    def __init__(
        self,
        result: FetchResult | None = None,
        *,
        raises: Exception | None = None,
    ) -> None:
        self.result = result or FetchResult(output=_fetch_output(), exit_code=0, truncated=False)
        self.raises = raises
        self.calls: list[SandboxCall] = []

    async def run(
        self,
        capability_dir: Path,
        *,
        entrypoint: str,
        argv: list[str],
        egress_domains: list[str],
        timeout_s: float = 60.0,
        secrets: dict[str, str] | None = None,
        caps_profile: Literal["default", "render"] = "default",
        output_limit: int = 4000,
    ) -> FetchResult:
        del timeout_s, caps_profile, output_limit
        self.calls.append(
            SandboxCall(
                capability_dir=capability_dir,
                entrypoint=entrypoint,
                argv=argv,
                egress_domains=egress_domains,
                secrets=secrets,
            )
        )
        if self.raises is not None:
            raise self.raises
        return self.result


class FakeOAuthBroker:
    def __init__(
        self,
        *,
        token: str = "ya29.test-token",
        raises_for: set[str] | None = None,
    ) -> None:
        self.token = token
        self.raises_for = raises_for or set()
        self.calls: list[tuple[str, str]] = []

    async def mint_access_token(self, account: str, scope: str) -> str:
        self.calls.append((account, scope))
        if scope in self.raises_for:
            raise RuntimeError("private oauth failure detail")
        return self.token


class FakeReader:
    def __init__(self, *, sanitized: str = "clean", raises: Exception | None = None) -> None:
        self._sanitized = sanitized
        self._raises = raises
        self.calls: list[list[Message]] = []
        self.models: list[str | None] = []

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del response_schema, temperature, max_tokens
        self.calls.append(list(messages))
        self.models.append(model)
        if self._raises is not None:
            raise self._raises
        return ModelResponse(
            text=json.dumps({"sanitized": self._sanitized}),
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


def _skill(
    *,
    inputs: list[SkillInputParam] | None = None,
    egress_domains: list[str] | None = None,
    secrets: list[str] | None = None,
    oauth_scopes: list[str] | None = None,
    path: str = "C:/tmp/Echo",
) -> Skill:
    return Skill(
        name="Echo",
        description="Echoes text.",
        version=1,
        path=path,
        tags=[],
        uses=[],
        secrets=secrets or [],
        oauth_scopes=oauth_scopes or [],
        inputs=inputs or [],
        egress_domains=egress_domains or [],
    )


def _fetch_output(domain: str = "calendar") -> str:
    return json.dumps(
        {
            "domain": domain,
            "rows": [
                {
                    "kind": "event",
                    "key": "e1",
                    "payload": {"start": "2026-08-22T09:00"},
                    "text": "Standup 9am",
                },
            ],
        }
    )


@pytest.mark.asyncio
async def test_run_fetch_ingests_rows() -> None:
    store = DataStore()
    ingest = IngestService(store, reader=FakeReader(sanitized="Standup 9am on 2026-08-22"))
    sandbox = RecordingSandbox(FetchResult(output=_fetch_output(), exit_code=0, truncated=False))
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(_skill(egress_domains=["www.googleapis.com"])),
        secrets_store=FakeSecretStore({}),
        sandbox=sandbox,
        ingest=ingest,
    )

    result = await runner.run_fetch("Echo", {})

    assert result is not None and result.ingested == 1
    rec = store.get("calendar", "event", "e1")
    assert rec is not None and rec.sanitized_text == "Standup 9am on 2026-08-22"
    assert rec.source == "Echo"
    assert sandbox.calls[0].entrypoint == "tool.py"
    assert sandbox.calls[0].egress_domains == ["www.googleapis.com"]


@pytest.mark.asyncio
async def test_run_fetch_injects_oauth_token() -> None:
    store = DataStore()
    ingest = IngestService(store, reader=FakeReader())
    sandbox = RecordingSandbox(FetchResult(output=_fetch_output(), exit_code=0, truncated=False))
    broker = FakeOAuthBroker(token="ya29.tok")
    scope = "https://www.googleapis.com/auth/calendar.readonly"
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(_skill(oauth_scopes=[scope])),
        secrets_store=FakeSecretStore({}),
        sandbox=sandbox,
        ingest=ingest,
        oauth_broker=broker,
    )

    await runner.run_fetch("Echo", {})

    assert broker.calls == [("default", scope)]
    assert sandbox.calls[0].secrets is not None
    assert sandbox.calls[0].secrets.get("GOOGLE_ACCESS_TOKEN") == "ya29.tok"


@pytest.mark.asyncio
async def test_run_fetch_missing_capability_returns_none_and_ingests_nothing() -> None:
    store = DataStore()
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(None),
        secrets_store=FakeSecretStore({}),
        sandbox=RecordingSandbox(),
        ingest=IngestService(store, reader=FakeReader()),
    )

    result = await runner.run_fetch("Echo", {})

    assert result is None
    assert store.get("calendar", "event", "e1") is None


@pytest.mark.asyncio
async def test_run_fetch_missing_required_secret_returns_none_and_ingests_nothing() -> None:
    store = DataStore()
    sandbox = RecordingSandbox()
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(_skill(secrets=["API_KEY"])),
        secrets_store=FakeSecretStore({"API_KEY": None}),
        sandbox=sandbox,
        ingest=IngestService(store, reader=FakeReader()),
    )

    result = await runner.run_fetch("Echo", {})

    assert result is None
    assert sandbox.calls == []
    assert store.get("calendar", "event", "e1") is None


@pytest.mark.asyncio
async def test_run_fetch_oauth_without_broker_returns_none_and_ingests_nothing() -> None:
    store = DataStore()
    sandbox = RecordingSandbox()
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(_skill(oauth_scopes=["scope-a"])),
        secrets_store=FakeSecretStore({}),
        sandbox=sandbox,
        ingest=IngestService(store, reader=FakeReader()),
    )

    result = await runner.run_fetch("Echo", {})

    assert result is None
    assert sandbox.calls == []
    assert store.get("calendar", "event", "e1") is None


@pytest.mark.asyncio
async def test_run_fetch_oauth_mint_raises_returns_none_and_ingests_nothing() -> None:
    store = DataStore()
    sandbox = RecordingSandbox()
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(_skill(oauth_scopes=["scope-a"])),
        secrets_store=FakeSecretStore({}),
        sandbox=sandbox,
        ingest=IngestService(store, reader=FakeReader()),
        oauth_broker=FakeOAuthBroker(raises_for={"scope-a"}),
    )

    result = await runner.run_fetch("Echo", {})

    assert result is None
    assert sandbox.calls == []
    assert store.get("calendar", "event", "e1") is None


@pytest.mark.asyncio
async def test_run_fetch_sandbox_raises_returns_none_and_ingests_nothing() -> None:
    store = DataStore()
    sandbox = RecordingSandbox(raises=RuntimeError("boom"))
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(_skill()),
        secrets_store=FakeSecretStore({}),
        sandbox=sandbox,
        ingest=IngestService(store, reader=FakeReader()),
    )

    result = await runner.run_fetch("Echo", {})

    assert result is None
    assert store.get("calendar", "event", "e1") is None


@pytest.mark.asyncio
async def test_run_fetch_nonzero_exit_returns_none_and_ingests_nothing() -> None:
    store = DataStore()
    sandbox = RecordingSandbox(FetchResult(output=_fetch_output(), exit_code=1, truncated=False))
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(_skill()),
        secrets_store=FakeSecretStore({}),
        sandbox=sandbox,
        ingest=IngestService(store, reader=FakeReader()),
    )

    result = await runner.run_fetch("Echo", {})

    assert result is None
    assert store.get("calendar", "event", "e1") is None


@pytest.mark.asyncio
async def test_dispatch_fetch_payload_runs_fetch() -> None:
    store = DataStore()
    ingest = IngestService(store, reader=FakeReader(sanitized="Standup 9am"))
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(_skill()),
        secrets_store=FakeSecretStore({}),
        sandbox=RecordingSandbox(FetchResult(output=_fetch_output(), exit_code=0, truncated=False)),
        ingest=ingest,
    )

    await runner.dispatch({"kind": "fetch", "capability": "Echo", "args": {}})

    rec = store.get("calendar", "event", "e1")
    assert rec is not None and rec.sanitized_text == "Standup 9am"


@pytest.mark.asyncio
async def test_dispatch_bad_payload_is_noop() -> None:
    runner = FetcherRunner(
        capability_store=FakeCapabilityStore(None),
        secrets_store=FakeSecretStore({}),
        sandbox=RecordingSandbox(),
        ingest=IngestService(DataStore(), reader=FakeReader()),
    )

    await runner.dispatch({"not": "a fetch job"})
