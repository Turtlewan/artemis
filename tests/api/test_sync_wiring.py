"""Tests for calendar sync scheduler wiring."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from artemis.api.app import _calendar_sync_job, create_app
from artemis.data.fetcher import FetcherRunner
from artemis.scheduler.scheduler import DurableScheduler
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


def test_calendar_sync_job_shape() -> None:
    job = _calendar_sync_job()
    assert job.id == "calendar-sync"
    assert job.cron == "*/15 * * * *"
    assert job.payload == {"kind": "fetch", "capability": "calendar-sync", "args": {}}


def test_create_app_no_sync_by_default(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel())
    assert getattr(app.state, "sync_scheduler", None) is None
    assert getattr(app.state, "fetcher_runner", None) is None


def test_create_app_enable_sync_wires_components(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel(), enable_sync=True)
    assert isinstance(app.state.fetcher_runner, FetcherRunner)
    assert isinstance(app.state.sync_scheduler, DurableScheduler)


def test_lifespan_registers_calendar_sync_job(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel(), enable_sync=True)
    with TestClient(app):
        active = app.state.sync_scheduler._ledger.active()
        assert any(row.id == "calendar-sync" for row in active)
