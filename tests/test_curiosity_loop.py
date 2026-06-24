from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from artemis.curiosity import (
    ConfidenceEvent,
    CuriosityLoop,
    EscalationEvent,
    ResearchResult,
    Source,
    StagedItem,
    StagingStore,
    StaleItem,
    StubResearcher,
    TokenLedger,
    grounding_gate,
    pick_top_gap,
    scan_gaps,
)
from artemis.curiosity.gaps import TelemetrySource
from artemis.curiosity.research import Reachability
from artemis.ports import Message, ModelResponse, Usage, Vector
from artemis.recipes.model import RecipeStatus
from artemis.recipes.store import RecipeStore

NOW = datetime(2026, 6, 24, tzinfo=UTC)


@dataclass
class FakeTelemetry(TelemetrySource):
    escalation_events: Sequence[EscalationEvent]
    confidence_events: Sequence[ConfidenceEvent]
    topics: Mapping[str, int]
    stale: Sequence[StaleItem]

    def escalations(self) -> Sequence[EscalationEvent]:
        return self.escalation_events

    def low_confidence_answers(self) -> Sequence[ConfidenceEvent]:
        return self.confidence_events

    def topic_counts(self) -> Mapping[str, int]:
        return self.topics

    def stale_items(self) -> Sequence[StaleItem]:
        return self.stale


class FakeReachability(Reachability):
    def __init__(self, reachable: set[str]) -> None:
        self._reachable = reachable

    def is_reachable(self, url: str) -> bool:
        return url in self._reachable


class FakeModelPort:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append(role)
        return ModelResponse(text="query", usage=Usage(1, 1, 2))

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        self.calls.append(role)
        return [[1.0, 0.0] for _ in texts]


class FakeEmbedder:
    dimension = 2

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> Vector:
        return [1.0, 0.0]


def test_gap_scan_and_curriculum_pick() -> None:
    telemetry = _telemetry()

    gaps = scan_gaps(telemetry, now=NOW)
    escalation_gap = next(
        gap for gap in gaps if gap.kind == "escalation-cluster" and gap.task_class_key == "calendar"
    )

    assert escalation_gap.evidence_count == 3
    assert pick_top_gap(gaps) == escalation_gap


def test_grounding_gate_passes_two_distinct_reachable_domains() -> None:
    result = _result(
        [
            "https://alpha.com/one",
            "https://beta.org/two",
        ]
    )

    assert grounding_gate(result, FakeReachability({source.url for source in result.sources}))


def _result(
    urls: Sequence[str],
    *,
    self_generated: bool = False,
    token_usage: int = 5,
) -> ResearchResult:
    return ResearchResult(
        query="query",
        content="Use this grounded procedure.",
        sources=[Source(url=url, domain=url, snippet="snippet") for url in urls],
        self_generated=self_generated,
        token_usage=token_usage,
    )


@pytest.mark.parametrize(
    ("result", "reachable", "expected"),
    [
        (
            _result(["https://alpha.com/one", "https://beta.org/two"], self_generated=True),
            {"https://alpha.com/one", "https://beta.org/two"},
            False,
        ),
        (
            _result(["https://one.alpha.com/one", "https://two.alpha.com/two"]),
            {"https://one.alpha.com/one", "https://two.alpha.com/two"},
            False,
        ),
        (
            _result(["https://news.x.com/one", "https://sport.x.com/two"]),
            {"https://news.x.com/one", "https://sport.x.com/two"},
            False,
        ),
        (
            _result(
                [
                    "https://alpha.com/one",
                    "https://beta.org/two",
                    "https://gamma.net/three",
                ]
            ),
            {"https://alpha.com/one", "https://beta.org/two"},
            True,
        ),
        (
            _result(["https://alpha.com/one", "https://beta.org/two"]),
            {"https://alpha.com/one"},
            False,
        ),
    ],
)
def test_grounding_gate_cases(
    result: ResearchResult,
    reachable: set[str],
    expected: bool,
) -> None:
    assert grounding_gate(result, FakeReachability(reachable)) is expected


@pytest.mark.asyncio
async def test_caps_hard_stop_has_zero_researcher_and_model_calls(tmp_path: Path) -> None:
    researcher = StubResearcher()
    model = FakeModelPort()
    loop = _loop(tmp_path, researcher=researcher, model=model, per_cycle_cap=0)

    status = await loop.curiosity_tick(is_idle=lambda: True, now=NOW)

    assert status == "CURIOSITY_SKIP"
    assert researcher.calls == []
    assert model.calls == []


@pytest.mark.asyncio
async def test_idle_gate_skip_has_zero_work(tmp_path: Path) -> None:
    researcher = StubResearcher()
    model = FakeModelPort()
    loop = _loop(tmp_path, researcher=researcher, model=model)

    status = await loop.curiosity_tick(is_idle=lambda: False, now=NOW)

    assert status == "CURIOSITY_SKIP"
    assert researcher.calls == []
    assert model.calls == []


@pytest.mark.asyncio
async def test_end_to_end_stages_without_live_recipe_write(tmp_path: Path) -> None:
    loop = _loop(tmp_path)

    status = await loop.curiosity_tick(is_idle=lambda: True, now=NOW)

    assert status == "CURIOSITY_STAGED"
    assert len(loop.staged_for_digest()) == 1
    assert _recipe_store(tmp_path).list(status=RecipeStatus.ENABLED) == []


@pytest.mark.asyncio
async def test_ungrounded_result_is_discarded(tmp_path: Path) -> None:
    result = _result(["https://alpha.com/one"], token_usage=5)
    loop = _loop(tmp_path, researcher=StubResearcher(result))

    status = await loop.curiosity_tick(is_idle=lambda: True, now=NOW)

    assert status == "CURIOSITY_UNGROUNDED"
    assert loop.staged_for_digest() == []


@pytest.mark.asyncio
async def test_owner_gated_commit_writes_candidate_and_removes_staged(tmp_path: Path) -> None:
    store = _recipe_store(tmp_path)
    loop = _loop(tmp_path, recipe_store=store)
    assert await loop.curiosity_tick(is_idle=lambda: True, now=NOW) == "CURIOSITY_STAGED"
    item = loop.staged_for_digest()[0]

    await loop.commit_staged(item.item_id)

    candidates = store.list(status=RecipeStatus.CANDIDATE)
    assert [recipe.name for recipe in candidates] == ["curiosity_calendar"]
    assert loop.staged_for_digest() == []


@pytest.mark.asyncio
async def test_discard_staged_removes_without_writing(tmp_path: Path) -> None:
    store = _recipe_store(tmp_path)
    loop = _loop(tmp_path, recipe_store=store)
    assert await loop.curiosity_tick(is_idle=lambda: True, now=NOW) == "CURIOSITY_STAGED"
    item = loop.staged_for_digest()[0]

    loop.discard_staged(item.item_id)

    assert loop.staged_for_digest() == []
    assert store.list(status=RecipeStatus.CANDIDATE) == []


@pytest.mark.asyncio
async def test_chunk_commit_not_yet_wired(tmp_path: Path) -> None:
    staging = StagingStore(tmp_path / "staging.json")
    staging.stage(
        StagedItem(
            item_id="chunk-1",
            kind="chunk",
            summary="chunk",
            payload={"text": "chunk"},
            gap="calendar",
            sources=[],
        )
    )
    loop = _loop(tmp_path, staging=staging)

    with pytest.raises(NotImplementedError):
        await loop.commit_staged("chunk-1")


def test_ledger_and_staging_round_trip(tmp_path: Path) -> None:
    ledger = TokenLedger(tmp_path / "ledger.json", per_cycle_cap=0, weekly_cap=100)
    assert not ledger.can_spend(NOW)

    staging = StagingStore(tmp_path / "staging.json")
    item = StagedItem("item-1", "recipe", "summary", {"name": "x"}, "gap", ["https://a.test"])
    staging.stage(item)
    assert staging.list() == [item]


def _loop(
    tmp_path: Path,
    *,
    researcher: StubResearcher | None = None,
    model: FakeModelPort | None = None,
    recipe_store: RecipeStore | None = None,
    staging: StagingStore | None = None,
    per_cycle_cap: int = 100,
) -> CuriosityLoop:
    return CuriosityLoop(
        telemetry=_telemetry(),
        researcher=researcher if researcher is not None else StubResearcher(_passing_result()),
        reachability=FakeReachability(
            {
                "https://alpha.com/one",
                "https://beta.org/two",
            }
        ),
        model=model if model is not None else FakeModelPort(),
        recipe_store=recipe_store if recipe_store is not None else _recipe_store(tmp_path),
        ledger=TokenLedger(tmp_path / "ledger.json", per_cycle_cap=per_cycle_cap, weekly_cap=100),
        staging=staging if staging is not None else StagingStore(tmp_path / "staging.json"),
    )


def _telemetry() -> FakeTelemetry:
    return FakeTelemetry(
        escalation_events=[
            EscalationEvent("calendar", NOW - timedelta(hours=1)),
            EscalationEvent("calendar", NOW - timedelta(hours=2)),
            EscalationEvent("calendar", NOW - timedelta(hours=3)),
        ],
        confidence_events=[ConfidenceEvent("mail", 0.4, NOW - timedelta(days=1))],
        topics={"weather": 1},
        stale=[StaleItem("old_recipe", "recipe", NOW - timedelta(days=120))],
    )


def _passing_result() -> ResearchResult:
    return _result(["https://alpha.com/one", "https://beta.org/two"])


def _recipe_store(tmp_path: Path) -> RecipeStore:
    return RecipeStore(FakeEmbedder(), tmp_path / "recipes")
