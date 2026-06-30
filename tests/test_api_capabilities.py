"""Tests for capability-build routes."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.capabilities.sandbox import VerifyResult
from artemis.types import Message, ModelResponse, SkillDraft, Usage


NETWORK_TOOL = "import imaplib\n\n\ndef fetch() -> None:\n    pass\n"


class FakeModel:
    def __init__(self, draft: SkillDraft) -> None:
        self._draft = draft

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        return ModelResponse(
            text="",
            model_id=model or "fake",
            structured=self._draft.model_dump(),
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class FakeSandbox:
    def __init__(self, result: VerifyResult) -> None:
        self._result = result
        self.ran = False

    async def run_tests(self, skill_dir: Path) -> VerifyResult:
        self.ran = True
        return self._result


def _draft(
    *,
    tests: str | None = "def test_skill() -> None:\n    assert True\n",
    tool_script: str | None = None,
    uses: list[str] | None = None,
    secrets: list[str] | None = None,
) -> SkillDraft:
    return SkillDraft(
        name="Echo",
        description="Echoes text.",
        body="Use this skill to echo text.",
        tool_script=tool_script,
        uses=uses or [],
        secrets=secrets or [],
        tests=tests,
    )


def _client(tmp_path: Path, draft: SkillDraft, sandbox: FakeSandbox | None = None) -> TestClient:
    app = create_app(
        data_dir=tmp_path,
        model=FakeModel(draft),
        sandbox=sandbox or FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    return TestClient(app)


def _result_json(stream_text: str) -> dict[str, object]:
    lines = stream_text.splitlines()
    for index, line in enumerate(lines):
        if line == "event: result":
            data_line = lines[index + 1]
            assert data_line.startswith("data: ")
            value = json.loads(data_line.removeprefix("data: "))
            assert isinstance(value, dict)
            return value
    raise AssertionError("missing result event")


def test_propose_clean_goal_returns_plan_card(tmp_path: Path) -> None:
    client = _client(tmp_path, _draft())

    resp = client.post("/app/capabilities/propose", json={"goal": "make an echo skill"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["blocked"] is False
    assert body["build_id"]
    assert body["name"] == "Echo"
    assert body["summary"] == "Use this skill to echo text."


def test_list_capabilities_returns_empty_list(tmp_path: Path) -> None:
    client = _client(tmp_path, _draft())

    resp = client.get("/app/capabilities")

    assert resp.status_code == 200
    assert resp.json() == {"capabilities": []}


def test_list_capabilities_returns_promoted_capabilities(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        _draft(uses=["clipboard"], secrets=["ECHO_TOKEN"]),
    )
    build_id = client.post("/app/capabilities/propose", json={"goal": "make an echo skill"}).json()[
        "build_id"
    ]
    build_resp = client.post(f"/app/capabilities/{build_id}/build")
    assert _result_json(build_resp.text)["passed"] is True
    promote_resp = client.post("/app/capabilities/promote", json={"build_id": build_id})
    assert promote_resp.status_code == 200

    resp = client.get("/app/capabilities")

    assert resp.status_code == 200
    assert resp.json() == {
        "capabilities": [
            {
                "name": "Echo",
                "description": "Echoes text.",
                "version": 1,
                "uses": ["clipboard"],
                "secrets": ["ECHO_TOKEN"],
            }
        ]
    }


def test_propose_network_draft_returns_blocked_plan(tmp_path: Path) -> None:
    client = _client(tmp_path, _draft(tool_script=NETWORK_TOOL))

    resp = client.post("/app/capabilities/propose", json={"goal": "read my email"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["blocked"] is True
    assert "imaplib" in body["block_reason"]


def test_build_clean_build_id_streams_passed_result(tmp_path: Path) -> None:
    client = _client(tmp_path, _draft())
    build_id = client.post("/app/capabilities/propose", json={"goal": "make an echo skill"}).json()[
        "build_id"
    ]

    resp = client.post(f"/app/capabilities/{build_id}/build")

    assert resp.status_code == 200
    assert "event: status" in resp.text
    assert "event: result" in resp.text
    assert "data: [DONE]" in resp.text
    assert _result_json(resp.text)["passed"] is True


def test_build_blocked_build_id_streams_blocked_result(tmp_path: Path) -> None:
    sandbox = FakeSandbox(VerifyResult(passed=True, output="ok"))
    client = _client(tmp_path, _draft(tool_script=NETWORK_TOOL), sandbox)
    build_id = client.post("/app/capabilities/propose", json={"goal": "read my email"}).json()[
        "build_id"
    ]

    resp = client.post(f"/app/capabilities/{build_id}/build")

    assert resp.status_code == 200
    assert _result_json(resp.text)["blocked"] is True
    assert sandbox.ran is False


def test_promote_after_passed_build_installs_skill(tmp_path: Path) -> None:
    client = _client(tmp_path, _draft())
    build_id = client.post("/app/capabilities/propose", json={"goal": "make an echo skill"}).json()[
        "build_id"
    ]
    build_resp = client.post(f"/app/capabilities/{build_id}/build")
    assert _result_json(build_resp.text)["passed"] is True

    resp = client.post("/app/capabilities/promote", json={"build_id": build_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Echo"
    assert body["version"] == 1
    assert (Path(body["path"]) / "SKILL.md").exists()


def test_promote_unknown_or_unbuilt_build_id_returns_409(tmp_path: Path) -> None:
    client = _client(tmp_path, _draft())

    assert client.post("/app/capabilities/promote", json={"build_id": "unknown"}).status_code == 409

    build_id = client.post("/app/capabilities/propose", json={"goal": "make an echo skill"}).json()[
        "build_id"
    ]
    assert client.post("/app/capabilities/promote", json={"build_id": build_id}).status_code == 409


def test_capability_routes_require_session(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            data_dir=tmp_path,
            model=FakeModel(_draft()),
            sandbox=FakeSandbox(VerifyResult(passed=True, output="ok")),
        )
    )

    assert client.post("/app/capabilities/propose", json={"goal": "hi"}).status_code == 401
    assert client.get("/app/capabilities").status_code == 401
    assert client.post("/app/capabilities/unknown/build").status_code == 401
    assert client.post("/app/capabilities/promote", json={"build_id": "unknown"}).status_code == 401
