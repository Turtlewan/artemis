"""Tests for desktop capability bless/revoke routes."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.capabilities.skill_md import write_skill_md
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
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
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


def _install_skill(tmp_path: Path, *, name: str = "Echo", version: int = 1) -> None:
    skill_dir = tmp_path / "capabilities" / "library" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    write_skill_md(
        skill_dir / "SKILL.md",
        name=name,
        description="Echoes text.",
        version=version,
        tags=[],
        uses=[],
        secrets=[],
        inputs=[],
        body="Use this skill to echo text.",
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(data_dir=tmp_path, model=FakeModel())
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev",
        person_id="owner",
    )
    return TestClient(app)


def test_bless_round_trip_uses_current_capability_version(tmp_path: Path) -> None:
    _install_skill(tmp_path, name="Echo", version=2)
    client = _client(tmp_path)

    bless_response = client.post("/app/bless/Echo")

    assert bless_response.status_code == 200
    assert bless_response.json() == {
        "name": "Echo",
        "current_version": 2,
        "blessed_version": 2,
        "blessed": True,
    }
    assert client.get("/app/bless").json() == {
        "capabilities": [
            {
                "name": "Echo",
                "current_version": 2,
                "blessed_version": 2,
                "blessed": True,
            }
        ]
    }

    delete_response = client.delete("/app/bless/Echo")

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert client.get("/app/bless").json() == {
        "capabilities": [
            {
                "name": "Echo",
                "current_version": 2,
                "blessed_version": None,
                "blessed": False,
            }
        ]
    }


def test_bless_unknown_capability_returns_404(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post("/app/bless/Missing")

    assert response.status_code == 404


def test_bless_routes_require_session(tmp_path: Path) -> None:
    _install_skill(tmp_path)
    client = TestClient(create_app(data_dir=tmp_path, model=FakeModel()))

    assert client.get("/app/bless").status_code == 401
    assert client.post("/app/bless/Echo").status_code == 401
    assert client.delete("/app/bless/Echo").status_code == 401


def test_version_bump_reads_as_unblessed(tmp_path: Path) -> None:
    _install_skill(tmp_path, name="Echo", version=1)
    client = _client(tmp_path)
    assert client.post("/app/bless/Echo").status_code == 200

    _install_skill(tmp_path, name="Echo", version=2)

    assert client.get("/app/bless").json() == {
        "capabilities": [
            {
                "name": "Echo",
                "current_version": 2,
                "blessed_version": 1,
                "blessed": False,
            }
        ]
    }
