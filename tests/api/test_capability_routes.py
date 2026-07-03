"""Capability metadata DTO tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.capabilities.sandbox import VerifyResult
from artemis.types import Message, ModelResponse, SkillDraft, Usage


class FakeModel:
    def __init__(self, draft: SkillDraft) -> None:
        self._draft = draft

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        _ = messages, response_schema, temperature, max_tokens
        return ModelResponse(
            text="",
            model_id=model or "fake",
            structured=self._draft.model_dump(),
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class FakeSandbox:
    async def run_tests(self, skill_dir: Path) -> VerifyResult:
        _ = skill_dir
        return VerifyResult(passed=True, output="ok")


def _draft() -> SkillDraft:
    return SkillDraft(
        name="Calendar Sync",
        description="Syncs calendars.",
        body="Use this skill.",
        tool_script=None,
        goal="Keep calendars aligned.",
        uses=["calendar"],
        secrets=["CALENDAR_TOKEN"],
        oauth_scopes=["calendar.read"],
        tests="def test_skill() -> None:\n    assert True\n",
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(data_dir=tmp_path, model=FakeModel(_draft()), sandbox=FakeSandbox())
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev",
        person_id="owner",
    )
    return TestClient(app)


def _result_json(stream_text: str) -> dict[str, object]:
    lines = stream_text.splitlines()
    for index, line in enumerate(lines):
        if line == "event: result":
            value = json.loads(lines[index + 1].removeprefix("data: "))
            assert isinstance(value, dict)
            return value
    raise AssertionError("missing result event")


def test_capability_summary_and_installed_card_carry_metadata(tmp_path: Path) -> None:
    client = _client(tmp_path)
    build_id = client.post("/app/capabilities/propose", json={"goal": "sync calendar"}).json()[
        "build_id"
    ]
    build_resp = client.post(f"/app/capabilities/{build_id}/build")
    assert _result_json(build_resp.text)["passed"] is True

    promote_resp = client.post("/app/capabilities/promote", json={"build_id": build_id})
    assert promote_resp.status_code == 200
    installed = promote_resp.json()
    assert installed["auth_status"] == "unverified"
    assert isinstance(installed["built_at"], str)
    assert installed["built_at"]

    list_resp = client.get("/app/capabilities")
    assert list_resp.status_code == 200
    summary = list_resp.json()["capabilities"][0]
    assert summary["auth_status"] == "unverified"
    assert summary["oauth_scopes"] == ["calendar.read"]
    assert summary["goal"] == "Keep calendars aligned."
    assert summary["built_at"] == installed["built_at"]
