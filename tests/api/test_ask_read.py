"""Tests for local data read wiring in ask routes."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from artemis.api import ask_routes
from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.capabilities.select import SelectionResult
from artemis.data.read import ReadService
from artemis.data.store import DataStore, Record
from artemis.intent import Intent, IntentRouter, Route
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    def __init__(self, text: str = "plain answer", model_id: str = "qwen3:4b") -> None:
        self._text = text
        self._model_id = model_id

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
            text=self._text,
            model_id=self._model_id,
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class FixedIntentRouter(IntentRouter):
    def __init__(self, route: Route) -> None:
        self._route = route

    async def classify(self, text: str) -> Intent:
        return Intent(route=self._route, confidence=1.0, reason=f"forced for {text}")


class FixedSelector:
    def __init__(self, selection: SelectionResult) -> None:
        self._selection = selection
        self.calls: list[str] = []

    async def select(self, request: str) -> SelectionResult:
        self.calls.append(request)
        return self._selection


class FakePhraser:
    def __init__(
        self, *, answer: str = "You have Standup at 9am.", raises: Exception | None = None
    ) -> None:
        self._answer = answer
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
            text=json.dumps({"answer": self._answer}),
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def _app_with_read(tmp_path: Path, *, phraser: FakePhraser, seed: Record | None) -> FastAPI:
    app = create_app(data_dir=tmp_path, model=FakeModel("router answer", "gpt-5.5"))
    app.dependency_overrides[require_session] = lambda: Principal(device_id="d", person_id="owner")

    async def read_service() -> ReadService:
        app.state.data_store = DataStore(str(tmp_path / "spine.db"))
        if seed is not None:
            app.state.data_store.upsert(seed)
        return ReadService(app.state.data_store, phraser=phraser)

    app.dependency_overrides[ask_routes._read_service] = read_service
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(_no_match())
    return app


def _no_match() -> SelectionResult:
    return SelectionResult(
        matched=False,
        capability=None,
        args={},
        confidence=0.0,
        missing_required=[],
    )


def test_create_app_wires_data_store(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel())

    assert isinstance(app.state.data_store, DataStore)


def test_calendar_ask_answers_from_local_read(tmp_path: Path) -> None:
    seed = Record(
        domain="calendar",
        kind="event",
        key="e1",
        payload={},
        sanitized_text="Standup 9am",
        source="calendar-sync",
        fetched_at=100.0,
    )
    app = _app_with_read(
        tmp_path, phraser=FakePhraser(answer="You have Standup at 9am."), seed=seed
    )
    client = TestClient(app)

    resp = client.post("/app/ask", json={"text": "what's on my calendar today"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "local_read"
    assert body["text"] == "You have Standup at 9am."


def test_non_synced_ask_falls_through(tmp_path: Path) -> None:
    app = _app_with_read(tmp_path, phraser=FakePhraser(), seed=None)
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter("plain_ask")
    client = TestClient(app)

    resp = client.post("/app/ask", json={"text": "what is the capital of France"})

    assert resp.status_code == 200
    assert resp.json()["path"] != "local_read"


def test_empty_store_calendar_ask_falls_through(tmp_path: Path) -> None:
    app = _app_with_read(tmp_path, phraser=FakePhraser(), seed=None)
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter("plain_ask")
    client = TestClient(app)

    resp = client.post("/app/ask", json={"text": "what's on my calendar"})

    assert resp.status_code == 200
    assert resp.json()["path"] != "local_read"
