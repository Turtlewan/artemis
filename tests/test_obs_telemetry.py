from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlite3 import Connection

import pytest

from artemis.config import ModelRole, Settings
from artemis.curiosity.gaps import Gap, TelemetrySource, scan_gaps
from artemis.identity.key_provider import SecretKey
from artemis.obs import ObservabilitySink
from artemis.obs.telemetry import (
    CallTrace,
    CostModel,
    SqliteTelemetrySource,
    TelemetrySink,
    TelemetryStore,
    Tier,
    TracingModelPort,
    UsageRow,
    open_telemetry_db,
    tier_for,
)
from artemis.ports import Message, ModelPort, ModelResponse, Usage, Vector
from artemis.recipes import Recipe, RecipeStore
from artemis.recipes.model import ActionClass, RecipeClass, RecipeStatus

TEST_KEY = SecretKey(bytes.fromhex("0123456789abcdef" * 4))


class FakeEmbedder:
    dimension = 2

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[float(len(text)), 1.0] for text in texts]

    async def embed_query(self, text: str) -> Vector:
        return [float(len(text)), 1.0]


class FakeModelPort:
    def __init__(self, response: ModelResponse) -> None:
        self._response = response

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        return self._response

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        async def _stream() -> AsyncIterator[str]:
            yield self._response.text

        return _stream()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0] for _text in texts]


class RaisingStore(TelemetryStore):
    def __init__(self, conn: Connection) -> None:
        super().__init__(conn)

    def record_call(self, trace: CallTrace) -> None:
        raise RuntimeError("boom")


def test_store_migrates_records_summarises_and_prunes(tmp_path: Path) -> None:
    conn = open_telemetry_db(tmp_path / "t.db", TEST_KEY)
    store = TelemetryStore(conn)
    again = TelemetryStore(conn)
    assert again is not None
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1

    now = datetime(2026, 6, 24, tzinfo=UTC)
    store.record_route("calendar/time", 0.25, "escalate", at=now)
    assert store.topic_counts() == {"calendar/time": 1}
    store.record_call(
        CallTrace(
            role="teacher",
            model_id="claude",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            latency_ms=7,
            cost_micros=3,
            trace_id=None,
            at=now,
        )
    )
    assert store.usage_summary(since=datetime(1970, 1, 1, tzinfo=UTC)) == [
        UsageRow(role="teacher", calls=1, total_tokens=15, cost_micros=3)
    ]
    assert store.prune(older_than=now + timedelta(days=1)) == 2
    assert store.route_events() == []
    assert store.escalation_events() == []
    assert store.usage_summary(since=datetime(1970, 1, 1, tzinfo=UTC)) == []


def test_cost_model_classifies_roles_and_micros(caplog: pytest.LogCaptureFixture) -> None:
    settings = _settings()
    assert tier_for("teacher", settings) == Tier.SUBSCRIPTION
    assert tier_for("responder", settings) == Tier.LOCAL
    assert tier_for("deep", settings) == Tier.CLOUD
    assert tier_for("missing-role", settings) == Tier.LOCAL
    assert any(record.message == "unknown_role" for record in caplog.records)

    assert CostModel(settings).cost_micros("responder", 5000) == 0
    assert CostModel(settings, cloud_micros_per_1k=200).cost_micros("deep", 5000) == 1000


@pytest.mark.asyncio
async def test_tracer_records_usage_model_id_and_survives_failures(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _settings()
    store = TelemetryStore(open_telemetry_db(tmp_path / "trace.db", TEST_KEY))
    inner = FakeModelPort(
        ModelResponse(text="ok", usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=42))
    )
    traced = TracingModelPort(inner, store, CostModel(settings), settings)
    _check_model: ModelPort = traced

    resp = await traced.complete(role="teacher", messages=[Message("user", "hi")])
    assert resp.text == "ok"
    rows = store.usage_summary(since=datetime(1970, 1, 1, tzinfo=UTC))
    assert rows == [UsageRow(role="teacher", calls=1, total_tokens=42, cost_micros=0)]
    db_row = store._conn.execute(
        "SELECT model_id, total_tokens, latency_ms FROM call_traces"
    ).fetchone()
    assert db_row[0] == "claude-sonnet"
    assert db_row[1] == 42
    assert db_row[2] >= 0

    zero_store = TelemetryStore(open_telemetry_db(tmp_path / "zero.db", TEST_KEY))
    zero_traced = TracingModelPort(
        FakeModelPort(ModelResponse(text="zero", usage=Usage(0, 0, 0))),
        zero_store,
        CostModel(settings),
        settings,
    )
    assert (await zero_traced.complete(role="responder", messages=[])).text == "zero"
    assert any(record.message == "empty_usage" for record in caplog.records)

    raising = RaisingStore(open_telemetry_db(tmp_path / "raising.db", TEST_KEY))
    raising_traced = TracingModelPort(
        FakeModelPort(ModelResponse(text="survived", usage=Usage(1, 2, 3))),
        raising,
        CostModel(settings),
        settings,
    )
    assert (await raising_traced.complete(role="teacher", messages=[])).text == "survived"
    assert any(record.message == "record_call_failed" for record in caplog.records)


def test_sink_source_projection_and_m7_gap_shape(tmp_path: Path) -> None:
    store = TelemetryStore(open_telemetry_db(tmp_path / "source.db", TEST_KEY))
    recipe_store = RecipeStore(FakeEmbedder(), tmp_path / "recipes")
    sink = TelemetrySink(store)
    source = SqliteTelemetrySource(store, recipe_store)
    _check_sink: ObservabilitySink = sink
    _check_src: TelemetrySource = source

    now = datetime(2026, 6, 24, tzinfo=UTC)
    sink.on_route_decision("email/reply", 0.2, "escalate", now=now)
    assert len(store.route_events()) == 1
    assert store.escalation_events() == []

    sink.on_escalation("email/reply", is_cloud_safe=True, now=now)
    assert source.escalations()[0].task_class_key == "email/reply"
    assert source.low_confidence_answers()[0].confidence == 0.2
    assert source.topic_counts() == {"email/reply": 1}

    for _index in range(2):
        sink.on_escalation("email/reply", is_cloud_safe=True, now=now)
    gaps = scan_gaps(source, now=now)
    cluster = _find_gap(gaps, kind="escalation-cluster", task_class_key="email/reply")
    assert cluster.evidence_count == 3


def test_empty_source_degrades_without_rows(tmp_path: Path) -> None:
    source = SqliteTelemetrySource(
        TelemetryStore(open_telemetry_db(tmp_path / "empty.db", TEST_KEY)),
        RecipeStore(FakeEmbedder(), tmp_path / "recipes"),
    )
    assert source.escalations() == []
    assert source.low_confidence_answers() == []
    assert source.topic_counts() == {}
    assert source.stale_items() == []


@pytest.mark.asyncio
async def test_recipe_staleness_parses_iso_and_skips_fresh(tmp_path: Path) -> None:
    now = datetime(2026, 6, 24, tzinfo=UTC)
    recipe_store = RecipeStore(FakeEmbedder(), tmp_path / "recipes")
    await recipe_store.write(
        _recipe("old_recipe", verified_at=(now - timedelta(days=200)).isoformat())
    )
    await recipe_store.write(
        _recipe("fresh_recipe", verified_at=(now - timedelta(days=2)).isoformat())
    )
    await recipe_store.write(_recipe("invalid_recipe", verified_at="not-a-date"))

    source = SqliteTelemetrySource(
        TelemetryStore(open_telemetry_db(tmp_path / "stale.db", TEST_KEY)),
        recipe_store,
        clock=lambda: now,
    )

    stale = source.stale_items()
    assert len(stale) == 1
    assert stale[0].item_id == "old_recipe"
    assert stale[0].kind == "recipe"


def _settings() -> Settings:
    return Settings.model_construct(
        slot="dev",
        data_root=Path("/tmp/artemis-test"),
        roles={
            "teacher": ModelRole(
                adapter="claude-cli",
                endpoint="local",
                model_id="claude-sonnet",
            ),
            "responder": ModelRole(
                adapter="openai",
                endpoint="http://127.0.0.1:8040/v1",
                model_id="qwen",
            ),
            "deep": ModelRole(
                adapter="openai",
                endpoint="https://api.deepseek.com/v1",
                model_id="deepseek-chat",
            ),
        },
    )


def _recipe(name: str, *, verified_at: str) -> Recipe:
    return Recipe(
        name=name,
        description=f"{name} description",
        version="1.0",
        recipe_class=RecipeClass.INSTRUCTIONS,
        action_class=ActionClass.READ_ONLY,
        task_class_key=name,
        inputs_schema={},
        outputs_schema={},
        instructions="Do the thing.",
        status=RecipeStatus.ENABLED,
        provenance={"verified_at": verified_at},
    )


def _find_gap(gaps: Sequence[Gap], *, kind: str, task_class_key: str) -> Gap:
    for gap in gaps:
        if gap.kind == kind and gap.task_class_key == task_class_key:
            return gap
    raise AssertionError(f"missing gap: {kind} {task_class_key}")
