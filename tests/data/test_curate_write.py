import json
from collections.abc import Sequence

from artemis.data.curate import (
    _AMBIGUOUS,
    _NOT_FOUND,
    _SAVE_WHERE,
    CurateDecision,
    CurateExtractor,
    ReadResults,
    apply_curate,
    resolve_referent,
    stash_results,
    stashed_rows,
)
from artemis.data.read import ReadService
from artemis.data.store import DataStore, Record
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    def __init__(self, *, reply: dict[str, str]) -> None:
        self._reply = reply
        self.calls: list[list[Message]] = []

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append(list(messages))
        return ModelResponse(
            text=json.dumps(self._reply),
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


class FakePhraser:
    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, response_schema, temperature, max_tokens
        return ModelResponse(
            text=json.dumps({"answer": "You have Standup at 9am."}),
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def _row(**over: object) -> Record:
    base = dict(
        domain="calendar",
        kind="event",
        key="e1",
        payload={"secret": "PAYLOAD_ONLY"},
        sanitized_text="Dentist at 3pm",
        source="today-calendar",
        fetched_at=100.0,
        owner_fields={},
    )
    base.update(over)
    return Record(**base)  # type: ignore[arg-type]


def _seed(store: DataStore, **over: object) -> None:
    base = dict(
        domain="calendar",
        kind="event",
        key="e1",
        payload={"secret_marker": "PAYLOAD_ONLY"},
        sanitized_text="Standup at 9am on 2026-08-22",
        source="today-calendar",
        fetched_at=100.0,
        owner_fields={},
    )
    base.update(over)
    store.upsert(Record(**base))  # type: ignore[arg-type]


def test_save_verbatim_bypasses_quarantine() -> None:
    store = DataStore()
    outcome = apply_curate(
        CurateDecision(op="save", domain="tasks", content="renew passport by Friday"),
        store=store,
        last_rows=(),
        now=lambda: 1.0,
    )

    rows = store.query(domain="tasks")
    assert outcome.ok
    assert outcome.reply == "Saved to tasks."
    assert len(rows) == 1
    assert rows[0].sanitized_text == "renew passport by Friday"
    assert rows[0].payload == {}
    assert rows[0].source == "curate"
    assert rows[0].kind == "note"


def test_save_domain_normalized_at_write_boundary() -> None:
    store = DataStore()
    outcome = apply_curate(
        CurateDecision.model_construct(op="save", domain="  Tasks ", content="x", referent=""),
        store=store,
        last_rows=(),
    )

    rows = store.query(domain="tasks")
    assert outcome.ok
    assert outcome.reply == "Saved to tasks."
    assert rows[0].domain == "tasks"


def test_save_empty_content_no_write() -> None:
    store = DataStore()
    outcome = apply_curate(
        CurateDecision(op="save", domain="tasks", content=""), store=store, last_rows=()
    )

    assert not outcome.ok
    assert outcome.reply == _NOT_FOUND
    assert store.query(domain="tasks") == []


def test_forget_by_content_deletes_match() -> None:
    store = DataStore()
    store.upsert(
        _row(
            domain="tasks",
            kind="note",
            key="k1",
            sanitized_text="buy milk",
            payload={},
            source="curate",
        )
    )

    outcome = apply_curate(
        CurateDecision(op="forget", domain="tasks", content="milk"), store=store, last_rows=()
    )

    assert outcome.ok
    assert outcome.reply == "Forgotten."
    assert store.query(domain="tasks") == []


def test_forget_no_match_no_write() -> None:
    store = DataStore()
    outcome = apply_curate(
        CurateDecision(op="forget", domain="tasks", content="nope"), store=store, last_rows=()
    )

    assert not outcome.ok
    assert outcome.reply == _NOT_FOUND


def test_resolve_ordinal() -> None:
    rows = [_row(key="a"), _row(key="b"), _row(key="c")]

    assert resolve_referent("the second one", rows).key == "b"  # type: ignore[union-attr]
    assert resolve_referent("the first", rows).key == "a"  # type: ignore[union-attr]
    assert resolve_referent("the 3rd one", rows).key == "c"  # type: ignore[union-attr]
    assert resolve_referent("the fifth one", rows) is None


def test_resolve_fuzzy_unambiguous() -> None:
    rows = [
        _row(key="d", sanitized_text="Dentist at 3pm"),
        _row(key="g", sanitized_text="Gym session"),
    ]

    assert resolve_referent("the dentist one", rows).key == "d"  # type: ignore[union-attr]
    assert resolve_referent("the yoga one", rows) is None
    assert (
        resolve_referent(
            "the meeting one",
            [_row(sanitized_text="Team meeting"), _row(sanitized_text="1:1 meeting")],
        )
        is None
    )


def test_resolve_bare_pointer_single_row() -> None:
    assert resolve_referent("that", [_row(key="only")]).key == "only"  # type: ignore[union-attr]
    assert resolve_referent("that", [_row(key="a"), _row(key="b")]) is None


def test_save_referent_copies_sanitized_not_payload() -> None:
    store = DataStore()
    last_rows = (_row(sanitized_text="Dentist at 3pm", payload={"secret": "PAYLOAD_ONLY"}),)

    outcome = apply_curate(
        CurateDecision(op="save", domain="tasks", referent="the dentist one"),
        store=store,
        last_rows=last_rows,
        now=lambda: 1.0,
    )

    rows = store.query(domain="tasks")
    assert outcome.ok
    assert rows[0].sanitized_text == "Dentist at 3pm"
    assert rows[0].payload == {}


def test_save_referent_unresolved_no_write() -> None:
    store = DataStore()
    last_rows = (_row(sanitized_text="Dentist at 3pm"),)

    outcome = apply_curate(
        CurateDecision(op="save", domain="tasks", referent="the plumber one"),
        store=store,
        last_rows=last_rows,
    )

    assert not outcome.ok
    assert outcome.reply == _NOT_FOUND
    assert store.query(domain="tasks") == []


def test_forget_referent_deletes_exact_row() -> None:
    store = DataStore()
    store.upsert(
        _row(
            domain="tasks",
            kind="note",
            key="k1",
            sanitized_text="buy milk",
            payload={},
            source="curate",
        )
    )
    row = store.get("tasks", "note", "k1")
    assert row is not None

    outcome = apply_curate(
        CurateDecision(op="forget", domain="tasks", referent="that"),
        store=store,
        last_rows=(row,),
    )

    assert outcome.ok
    assert store.get("tasks", "note", "k1") is None


def test_stash_strips_payload() -> None:
    state: dict[str, ReadResults] = {}

    stash_results(state, "dev", (_row(payload={"secret": "PAYLOAD_ONLY"}),))
    rows = stashed_rows(state, "dev")

    assert len(rows) == 1
    assert rows[0].payload == {}
    assert rows[0].sanitized_text == "Dentist at 3pm"
    assert stashed_rows(state, "other") == ()


async def test_read_exposes_rows() -> None:
    store = DataStore()
    _seed(store)
    svc = ReadService(store, phraser=FakePhraser(), now=lambda: 100.0)

    result = await svc.read("what's on my calendar")

    assert result is not None
    assert len(result.rows) == 1
    assert result.rows[0].sanitized_text == "Standup at 9am on 2026-08-22"


def test_forget_ambiguous_content_refuses() -> None:
    store = DataStore()
    store.upsert(
        _row(
            domain="tasks",
            kind="note",
            key="k1",
            sanitized_text="buy milk",
            payload={},
            source="curate",
        )
    )
    store.upsert(
        _row(
            domain="tasks",
            kind="note",
            key="k2",
            sanitized_text="milk the feedback",
            payload={},
            source="curate",
        )
    )

    outcome = apply_curate(
        CurateDecision(op="forget", domain="tasks", content="milk"), store=store, last_rows=()
    )

    assert not outcome.ok
    assert outcome.reply == _AMBIGUOUS
    assert len(store.query(domain="tasks")) == 2


def test_save_into_synced_domain_refused() -> None:
    store = DataStore()
    store.upsert(_row(domain="calendar", key="e1", source="calendar-sync"))

    outcome = apply_curate(
        CurateDecision(op="save", domain="calendar", content="fake event"),
        store=store,
        last_rows=(),
    )

    assert not outcome.ok
    assert outcome.reply == "calendar is synced read-only -- try 'add a task' instead."
    assert len(store.query(domain="calendar")) == 1


def test_forget_referent_synced_row_refused() -> None:
    store = DataStore()
    store.upsert(_row(domain="calendar", key="e1", source="calendar-sync"))
    row = store.get("calendar", "event", "e1")
    assert row is not None

    outcome = apply_curate(
        CurateDecision(op="forget", domain="calendar", referent="that"),
        store=store,
        last_rows=(row,),
    )

    assert not outcome.ok
    assert "synced read-only" in outcome.reply
    assert store.get("calendar", "event", "e1") is not None


def test_upsert_normalizes_domain_chokepoint() -> None:
    store = DataStore()
    store.upsert(_row(domain="  Tasks ", kind="note", key="k1", source="curate"))

    assert len(store.query(domain="tasks")) == 1
    assert store.domains() == ["tasks"]


async def test_extract_referent_save_empty_domain_passes_through() -> None:
    model = FakeModel(
        reply={"op": "save", "domain": "", "content": "", "referent": "the second one"}
    )

    decision = await CurateExtractor(model).extract(
        "save the second one", existing_domains=["tasks"]
    )

    assert decision.op == "save"
    assert decision.referent == "the second one"


async def test_extract_forget_empty_domain_passes_through() -> None:
    model = FakeModel(
        reply={"op": "forget", "domain": "", "content": "the plumber thing", "referent": ""}
    )

    decision = await CurateExtractor(model).extract(
        "forget what i said about the plumber", existing_domains=["tasks"]
    )

    assert decision.op == "forget"


async def test_extract_plain_save_empty_domain_still_degrades() -> None:
    model = FakeModel(reply={"op": "save", "domain": "", "content": "x", "referent": ""})

    decision = await CurateExtractor(model).extract("save x", existing_domains=[])

    assert decision.op == "none"


def test_forget_unscoped_cross_domain_exactly_one() -> None:
    store = DataStore()
    store.upsert(
        _row(
            domain="tasks",
            kind="note",
            key="k1",
            sanitized_text="buy milk",
            payload={},
            source="curate",
        )
    )
    store.upsert(
        _row(
            domain="notes",
            kind="note",
            key="n1",
            sanitized_text="call the plumber",
            payload={},
            source="curate",
        )
    )

    outcome = apply_curate(
        CurateDecision(op="forget", domain="", content="plumber"), store=store, last_rows=()
    )

    assert outcome.ok
    assert outcome.reply == "Forgotten."
    assert store.query(domain="notes") == []
    assert len(store.query(domain="tasks")) == 1


def test_forget_unscoped_ambiguous_across_domains_refuses() -> None:
    store = DataStore()
    store.upsert(
        _row(
            domain="tasks",
            kind="note",
            key="k1",
            sanitized_text="buy milk",
            payload={},
            source="curate",
        )
    )
    store.upsert(
        _row(
            domain="notes",
            kind="note",
            key="n1",
            sanitized_text="milk the feedback",
            payload={},
            source="curate",
        )
    )

    outcome = apply_curate(
        CurateDecision(op="forget", domain="", content="milk"), store=store, last_rows=()
    )

    assert not outcome.ok
    assert outcome.reply == _AMBIGUOUS
    assert len(store.query(domain="tasks")) == 1
    assert len(store.query(domain="notes")) == 1


def test_referent_save_no_target_refused() -> None:
    store = DataStore()

    outcome = apply_curate(
        CurateDecision(op="save", domain="", content="", referent="the second one"),
        store=store,
        last_rows=(_row(), _row(key="e2")),
    )

    assert not outcome.ok
    assert outcome.reply == _SAVE_WHERE
    assert store.domains() == []
