from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import pytest

from artemis.brain import Brain
from artemis.gateway import Gateway
from artemis.identity.scope import OWNER_PRIVATE, Identity
from artemis.ports.types import PersonId, Scope
from artemis.speakable import POINTER_TEMPLATE, subject_phrase, to_speakable


def test_to_speakable_keeps_short_answer() -> None:
    assert to_speakable("It is noon.") == "It is noon."


def test_to_speakable_points_for_list_with_subject() -> None:
    answer = "- First\n- Second"
    assert to_speakable(answer, subject=subject_phrase("show my tasks")) == POINTER_TEMPLATE.format(
        subject="my tasks"
    )


def test_to_speakable_points_for_code_and_long_answer() -> None:
    assert to_speakable("```python\nprint('x')\n```", subject="code") == POINTER_TEMPLATE.format(
        subject="code"
    )
    assert to_speakable("One. Two. Three.", subject="summary") == POINTER_TEMPLATE.format(
        subject="summary"
    )


def test_to_speakable_strips_short_answer_markup() -> None:
    answer = "local: **Noon** from [clock](https://example.test) [^1] `now`"
    assert to_speakable(answer) == "Noon from clock now"


@pytest.mark.asyncio
async def test_handle_ask_unified_tees_one_stream_with_speak() -> None:
    fake = FakeBrain(["- first\n", "- second\n", "- third\n"])
    gateway = Gateway(cast(Brain, fake))

    display_iter, speak_iter = await gateway.handle_ask_unified(
        "show my tasks",
        scope_or_identity=OWNER_PRIVATE,
        speak=True,
    )

    assert [chunk async for chunk in display_iter] == ["- first\n", "- second\n", "- third\n"]
    assert [chunk async for chunk in speak_iter] == [POINTER_TEMPLATE.format(subject="my tasks")]
    assert fake.calls == [("show my tasks", OWNER_PRIVATE)]


@pytest.mark.asyncio
async def test_handle_ask_unified_speak_false_has_empty_speak_and_one_source_call() -> None:
    fake = FakeBrain(["It ", "is ", "noon."])
    gateway = Gateway(cast(Brain, fake))

    display_iter, speak_iter = await gateway.handle_ask_unified(
        "what time is it",
        scope_or_identity=Identity(PersonId("owner"), "owner"),
        speak=False,
    )

    assert [chunk async for chunk in speak_iter] == []
    assert [chunk async for chunk in display_iter] == ["It ", "is ", "noon."]
    assert fake.calls == [("what time is it", OWNER_PRIVATE)]


class FakeBrain:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self.calls: list[tuple[str, Scope]] = []

    async def pre_route(self, request_text: str, scope: Scope) -> str | None:
        return None

    async def respond_stream(self, request_text: str, scope: Scope) -> AsyncIterator[str]:
        self.calls.append((request_text, scope))
        for chunk in self._chunks:
            yield chunk
