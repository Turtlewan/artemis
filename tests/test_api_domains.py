"""Tests for the typed-empty domain routes."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, model, response_schema, temperature, max_tokens
        return ModelResponse(
            text="hello there",
            model_id="qwen3:4b",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


def _client() -> TestClient:
    app = create_app(model=FakeModel())
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    return TestClient(app)


def test_calendar_empty() -> None:
    client = _client()
    resp = client.get("/app/calendar")
    assert resp.status_code == 200
    assert resp.json() == {"events": [], "tasksDueByDay": {}}


def test_email_empty() -> None:
    client = _client()
    resp = client.get("/app/email")
    assert resp.status_code == 200
    assert resp.json() == {"needsYou": [], "signal": []}


def test_finance_empty_has_null_advisories() -> None:
    client = _client()
    resp = client.get("/app/finance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["unusual"] is None
    assert body["duplicate"] is None
    assert body["ambiguous"] is None
    assert body["week_total"] == 0
    assert body["mtd_total"] == 0
    assert body["daily"] == []
    assert body["categories"] == []
    assert body["transactions"] == []
    assert body["bills"] == []


def test_tasks_projects_empty() -> None:
    client = _client()
    assert client.get("/app/tasks").json() == {
        "overdue": [],
        "today": [],
        "upcoming": [],
        "suggestions": [],
    }
    assert client.get("/app/projects").json() == {"projects": []}


def test_review_and_actions_pending_empty() -> None:
    client = _client()
    assert client.get("/app/review/pending").json() == []
    assert client.get("/app/review/auto-enabled").json() == []
    assert client.get("/app/actions/pending").json() == []


def test_review_approve_reject_echo_settled_items() -> None:
    client = _client()
    approved = client.post("/app/review/approve", json={"name": "recipe-a"})
    rejected = client.post("/app/review/reject", json={"name": "recipe-b"})
    assert approved.status_code == 200
    assert rejected.status_code == 200
    assert approved.json() == {
        "name": "recipe-a",
        "description": "",
        "status": "approved",
        "action_class": "",
        "safety": "",
        "explanation": "",
    }
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["name"] == "recipe-b"


def test_suggestion_reject_ok() -> None:
    client = _client()
    resp = client.post("/app/tasks/suggestion/reject", json={"suggestion_id": "sug-1"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_empty_mutations_404() -> None:
    client = _client()
    assert client.post("/app/actions/approve", json={"id": "act-1"}).status_code == 404
    assert client.post("/app/actions/reject", json={"id": "act-1"}).status_code == 404
    assert (
        client.post(
            "/app/tasks/suggestion/accept",
            json={"suggestion_id": "sug-1", "due_at": None, "project_id": None},
        ).status_code
        == 404
    )


def test_reads_require_session() -> None:
    client = TestClient(create_app(model=FakeModel()))
    assert client.get("/app/calendar").status_code == 401
