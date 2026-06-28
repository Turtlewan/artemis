from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator

import pytest

from artemis.speakable import SpeakSeg
from artemis.voice.sidecar_client import FakeSidecar
from artemis.voice.voice_loop import compose_speak_sink, speak_overlay_answer


async def _speak(*segments: SpeakSeg) -> AsyncIterator[SpeakSeg]:
    for segment in segments:
        yield segment
        await asyncio.sleep(0)


class FakeTTS:
    def __init__(self, sidecar: FakeSidecar, *, fail: bool = False) -> None:
        self.sidecar = sidecar
        self.fail = fail
        self.texts: list[str] = []
        self.pcm_before_synthesize: list[list[bytes]] = []

    def synthesize(self, text: str) -> Iterator[bytes]:
        if self.fail:
            raise RuntimeError("tts failed")
        self.pcm_before_synthesize.append(list(self.sidecar.speaker_pcm))
        self.texts.append(text)
        yield f"pcm:{text}".encode()


@pytest.mark.asyncio
async def test_speak_iter_synthesizes_and_plays_each_sentence_in_order() -> None:
    sidecar = FakeSidecar()
    tts = FakeTTS(sidecar)
    cancel = asyncio.Event()

    await speak_overlay_answer(
        _speak("First sentence. Second sentence."),
        frontend=sidecar,
        tts=tts,
        cancel=cancel,
        is_owner_unlocked=lambda: True,
    )

    assert tts.texts == ["First sentence.", "Second sentence."]
    assert sidecar.speaker_pcm.index(b"pcm:First sentence.") < sidecar.speaker_pcm.index(
        b"pcm:Second sentence."
    )
    assert b"pcm:First sentence." in tts.pcm_before_synthesize[1]


@pytest.mark.asyncio
async def test_bargein_cancels_mid_playback_and_ends_turn() -> None:
    sidecar = FakeSidecar(bargein_after_pcm_chunks=2)
    tts = FakeTTS(sidecar)
    cancel = asyncio.Event()

    await speak_overlay_answer(
        _speak("First sentence. Second sentence."),
        frontend=sidecar,
        tts=tts,
        cancel=cancel,
        is_owner_unlocked=lambda: True,
    )

    command_types = [command["type"] for command in sidecar.commands]
    assert cancel.is_set()
    assert "stopPlayback" in command_types
    assert command_types[-1] == "startListening"
    assert tts.texts == ["First sentence."]
    assert b"pcm:Second sentence." not in sidecar.speaker_pcm


@pytest.mark.asyncio
async def test_pointer_only_speak_iter_plays_once() -> None:
    sidecar = FakeSidecar()
    tts = FakeTTS(sidecar)
    sink = compose_speak_sink(sidecar, tts, is_owner_unlocked=lambda: True)

    await sink(_speak("Your results are on screen."))

    assert tts.texts == ["Your results are on screen."]
    assert sidecar.speaker_pcm.count(b"pcm:Your results are on screen.") == 1


@pytest.mark.asyncio
async def test_tts_error_degrades_without_raising_or_logging_spoken_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sidecar = FakeSidecar()
    tts = FakeTTS(sidecar, fail=True)

    with caplog.at_level(logging.WARNING, logger="artemis.voice.voice_loop"):
        await speak_overlay_answer(
            _speak("Sensitive spoken text."),
            frontend=sidecar,
            tts=tts,
            cancel=asyncio.Event(),
            is_owner_unlocked=lambda: True,
        )

    assert "Sensitive spoken text" not in caplog.text


@pytest.mark.asyncio
async def test_speak_path_stops_when_owner_vault_locks_mid_iteration() -> None:
    sidecar = FakeSidecar()
    tts = FakeTTS(sidecar)
    checks = 0

    def unlocked_once() -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    await speak_overlay_answer(
        _speak("First sentence. Second sentence."),
        frontend=sidecar,
        tts=tts,
        cancel=asyncio.Event(),
        is_owner_unlocked=unlocked_once,
    )

    assert tts.texts == ["First sentence."]
    assert b"pcm:Second sentence." not in sidecar.speaker_pcm
