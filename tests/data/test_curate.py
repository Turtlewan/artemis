import json
from collections.abc import Sequence
from typing import Any

from artemis.data.curate import CURATE_VERBS, CurateExtractor, has_curate_verb
from artemis.data.store import DataStore, Record
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    def __init__(
        self, *, reply: dict[str, str] | None = None, raises: Exception | None = None
    ) -> None:
        self._reply = reply or {"op": "none", "domain": "", "content": "", "referent": ""}
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
        self.calls.append(list(messages))
        self.models.append(model)
        if self._raises is not None:
            raise self._raises
        return ModelResponse(
            text=json.dumps(self._reply),
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


SAVE_REPLY = {
    "op": "save",
    "domain": "tasks",
    "content": "renew passport by Friday",
    "referent": "",
}


def _seed(store: DataStore, **over: object) -> None:
    base: dict[str, Any] = {
        "domain": "tasks",
        "kind": "note",
        "key": "n1",
        "payload": {},
        "sanitized_text": "renew passport by Friday",
        "source": "owner",
        "fetched_at": 100.0,
        "owner_fields": {},
    }
    base.update(over)
    store.upsert(Record(**base))


def test_prefilter_word_boundary() -> None:
    assert has_curate_verb("add a task: renew passport")
    assert not has_curate_verb("what's my address")
    assert not has_curate_verb("check my notebook")
    assert not has_curate_verb("what's on my calendar")
    assert CURATE_VERBS == ("save", "note", "remember", "add", "forget", "log", "track")


async def test_extract_no_verb_skips_model_call() -> None:
    model = FakeModel()
    decision = await CurateExtractor(model).extract("what's the weather", existing_domains=[])
    assert decision.op == "none"
    assert model.calls == []


async def test_extract_save() -> None:
    model = FakeModel(reply=SAVE_REPLY)
    decision = await CurateExtractor(model).extract(
        "add a task: renew passport by Friday", existing_domains=["calendar"]
    )
    assert decision.op == "save"
    assert decision.domain == "tasks"
    assert decision.content == "renew passport by Friday"
    assert decision.referent == ""
    assert model.models == ["haiku"]


async def test_prompt_carries_live_domains_and_reuse_rule() -> None:
    model = FakeModel(reply=SAVE_REPLY)
    await CurateExtractor(model).extract(
        "add a task: renew passport by Friday", existing_domains=["calendar", "tasks"]
    )
    system_content = model.calls[0][0].content
    user_content = model.calls[0][1].content
    assert "calendar, tasks" in user_content
    assert "add a task: renew passport by Friday" in user_content
    assert "REUSE" in system_content
    assert "VERBATIM" in system_content

    empty_model = FakeModel(reply=SAVE_REPLY)
    await CurateExtractor(empty_model).extract(
        "add a task: renew passport by Friday", existing_domains=[]
    )
    assert "(none yet)" in empty_model.calls[0][1].content


async def test_extract_model_failure_degrades_to_none() -> None:
    decision = await CurateExtractor(FakeModel(raises=RuntimeError("down"))).extract(
        "add a task", existing_domains=[]
    )
    assert decision.op == "none"


async def test_domain_label_normalized() -> None:
    decision = await CurateExtractor(
        FakeModel(
            reply={
                "op": "save",
                "domain": "  Tasks ",
                "content": "renew passport by Friday",
                "referent": "",
            }
        )
    ).extract("add a task: renew passport by Friday", existing_domains=[])
    assert decision.domain == "tasks"


def test_store_domains_live_list() -> None:
    store = DataStore()
    assert store.domains() == []
    _seed(store, domain="tasks", key="n1")
    _seed(store, domain="tasks", key="n2")
    _seed(store, domain="calendar", key="e1")
    assert store.domains() == ["calendar", "tasks"]


async def test_empty_domain_save_degrades_to_none() -> None:
    decision = await CurateExtractor(
        FakeModel(reply={"op": "save", "domain": "", "content": "x", "referent": ""})
    ).extract("save x", existing_domains=[])
    assert decision.op == "none"
