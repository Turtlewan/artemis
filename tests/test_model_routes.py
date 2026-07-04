"""Tests for model-role API routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.model.roles import PROVIDERS


def _app(tmp_path: Path) -> FastAPI:
    app = create_app(data_dir=str(tmp_path))
    app.dependency_overrides[require_session] = lambda: Principal(device_id="d", person_id="owner")
    return app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(_app(tmp_path))


def _roles_by_name(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["role"]: row for row in body["roles"]}


def test_get_models_lists_roles_constraints_and_eligibility(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/app/models")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["roles"]) == 10
    assert body["providers"] == list(PROVIDERS)
    assert body["dropped_overrides"] == []
    for row in body["roles"]:
        assert "provider" in row
        assert "model" in row
        assert "constraints" in row
        assert "eligible_providers" in row
        assert row["editable_fields"] == ["provider", "model"]
    roles = _roles_by_name(body)
    assert roles["reader"]["eligible_providers"] == ["claude_code", "ollama"]
    assert roles["reader"]["constraints"] == {"no_tools": True, "temperature": None}
    assert roles["extractor"]["constraints"]["temperature"] == 0.0
    assert "router" in roles["synth"]["eligible_providers"]


def test_put_edits_binding_without_restart(tmp_path: Path) -> None:
    client = _client(tmp_path)

    put = client.put(
        "/app/models/loop_driver", json={"provider": "anthropic_api", "model": "claude-sonnet"}
    )

    assert put.status_code == 200
    assert put.json()["provider"] == "anthropic_api"
    roles = _roles_by_name(client.get("/app/models").json())
    assert roles["loop_driver"]["provider"] == "anthropic_api"


def test_put_rejects_invariant_and_dto_violations_without_persisting(tmp_path: Path) -> None:
    client = _client(tmp_path)
    bad_requests = [
        ("/app/models/reader", {"provider": "codex", "model": "gpt-5.5"}),
        ("/app/models/judge", {"provider": "claude_code", "model": "haiku"}),
        ("/app/models/nope", {"provider": "codex", "model": "x"}),
        ("/app/models/reader", {"provider": "router", "model": ""}),
        ("/app/models/selector", {"provider": "claude_code", "model": ""}),
        ("/app/models/selector", {"provider": "claude_code", "model": "a b/../c"}),
    ]

    for path, payload in bad_requests:
        resp = client.put(path, json=payload)
        assert resp.status_code == 422
        assert resp.json()["detail"]

    roles = _roles_by_name(client.get("/app/models").json())
    assert roles["loop_driver"]["provider"] == "claude_code"
    assert roles["judge"]["provider"] == "claude_code"
    assert roles["judge"]["model"] == "sonnet"
    assert roles["reader"]["provider"] == "claude_code"
    assert roles["selector"]["provider"] == "claude_code"


def test_usage_returns_per_role_aggregates(tmp_path: Path) -> None:
    app = _app(tmp_path)
    client = TestClient(app)

    assert client.get("/app/models/usage").json()["roles"] == []

    app.state.model_meter.record(
        "selector",
        "claude_code",
        "haiku",
        prompt_tokens=2,
        completion_tokens=4,
        latency_ms=7,
        cache_read_tokens=1,
        cache_creation_tokens=6,
    )

    assert client.get("/app/models/usage").json()["roles"] == [
        {
            "role": "selector",
            "calls": 1,
            "prompt_tokens": 2,
            "completion_tokens": 4,
            "cache_read_tokens": 1,
            "cache_creation_tokens": 6,
            "avg_latency_ms": 7.0,
        }
    ]


def test_dropped_override_surfaces_static_reason(tmp_path: Path) -> None:
    (tmp_path / "model_roles.json").write_text(
        json.dumps({"reader": {"provider": "codex", "model": "gpt-5.5"}}),
        encoding="utf-8",
    )

    body = _client(tmp_path).get("/app/models").json()

    roles = _roles_by_name(body)
    assert roles["reader"]["provider"] == "claude_code"
    assert roles["reader"]["model"] == "haiku"
    assert body["dropped_overrides"] == [{"role": "reader", "reason": "no_tools_ineligible"}]


def test_tampered_file_content_is_never_echoed(tmp_path: Path) -> None:
    (tmp_path / "model_roles.json").write_text(
        json.dumps(
            {
                "<img src=x onerror=alert(1)>": {
                    "provider": "evil<script>",
                    "model": "x",
                },
                "phraser": {"provider": "claude_code", "model": "   "},
            }
        ),
        encoding="utf-8",
    )

    resp = _client(tmp_path).get("/app/models")

    assert resp.status_code == 200
    assert "<img" not in resp.text
    assert "<script" not in resp.text
    assert "evil" not in resp.text
    body = resp.json()
    assert body["dropped_overrides"] == [{"role": "phraser", "reason": "malformed_entry"}]
    roles = _roles_by_name(body)
    assert roles["phraser"]["provider"] == "claude_code"
    assert roles["phraser"]["model"] == "haiku"


def test_models_requires_session(tmp_path: Path) -> None:
    app = create_app(data_dir=str(tmp_path))

    assert TestClient(app).get("/app/models").status_code == 401
