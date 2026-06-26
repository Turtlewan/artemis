from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import cast

import pytest

from artemis.config import Settings
from artemis.gateway import GUEST_PERSON_ID, NEEDS_UNLOCK_PROMPT, Gateway, NeedsPhoneUnlock
from artemis.identity.scope import OWNER_PERSON_ID
from artemis.ports.types import Scope
from artemis.ports.voice import AudioFrontend
from artemis.sidecar.audio.protocol import JsonObject
from artemis.voice.latency import LatencyBudget, StageTimer
from artemis.voice.sidecar_client import FakeSidecar, SidecarAudioFrontend
from artemis.voice.voice_loop import VoiceLoop

ACK = b"ack"
MIC = b"mic"


class FakeSTT:
    def __init__(self, transcript: str = "what time is it") -> None:
        self.transcript = transcript

    def transcribe(self, audio: bytes, *, language: str | None = None) -> str:
        del audio, language
        return self.transcript


class FakeTTS:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.before_synthesize: list[list[tuple[str, object]]] = []

    def synthesize(self, text: str) -> Iterator[bytes]:
        self.before_synthesize.append([])
        self.texts.append(text)
        yield f"pcm:{text}".encode()


class FakeGateway:
    def __init__(self, chunks: list[str], *, needs_unlock: bool = False) -> None:
        self.chunks = chunks
        self.needs_unlock = needs_unlock
        self.calls: list[tuple[bytes, str]] = []

    async def handle_voice_stream(self, audio: bytes, transcript: str) -> AsyncIterator[str]:
        self.calls.append((audio, transcript))
        if self.needs_unlock:
            raise NeedsPhoneUnlock
        for chunk in self.chunks:
            yield chunk


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path)


def _script() -> Sequence[JsonObject | bytes]:
    return [{"type": "wakeDetected"}, MIC, {"type": "speechEnd", "reason": "endpoint"}]


def _command_types(sidecar: FakeSidecar) -> list[object]:
    return [
        record[1]["type"]
        for record in sidecar.records
        if record[0] == "command" and isinstance(record[1], dict)
    ]


def _loop(
    tmp_path: Path,
    sidecar: FakeSidecar,
    gateway: FakeGateway,
    *,
    tts: FakeTTS | None = None,
) -> tuple[VoiceLoop, FakeTTS]:
    resolved_tts = tts if tts is not None else FakeTTS()
    loop = VoiceLoop(
        sidecar,
        FakeSTT(),
        resolved_tts,
        cast(Gateway, gateway),
        _settings(tmp_path),
        ACK,
        LatencyBudget(),
    )
    return loop, resolved_tts


def test_audio_frontend_conformance(tmp_path: Path) -> None:
    frontend: AudioFrontend = SidecarAudioFrontend(tmp_path / "dev" / "run")
    assert frontend is not None


@pytest.mark.asyncio
async def test_happy_cascade_records_start_ack_tts_and_idle(tmp_path: Path) -> None:
    sidecar = FakeSidecar(_script())
    gateway = FakeGateway(["It is noon."])
    loop, _ = _loop(tmp_path, sidecar, gateway)

    await loop.run_once()

    command_types = _command_types(sidecar)
    pcm = [record[1] for record in sidecar.records if record[0] == "spk_pcm"]
    assert command_types[0] == "startListening"
    assert ACK in pcm
    assert b"pcm:It is noon." in pcm
    assert loop.idle


@pytest.mark.asyncio
async def test_instant_ack_before_brain_tts_pcm(tmp_path: Path) -> None:
    sidecar = FakeSidecar(_script())
    gateway = FakeGateway(["It is noon."])
    loop, _ = _loop(tmp_path, sidecar, gateway)

    await loop.run_once()

    pcm = [record[1] for record in sidecar.records if record[0] == "spk_pcm"]
    assert pcm.index(ACK) < pcm.index(b"pcm:It is noon.")


@pytest.mark.asyncio
async def test_sentence_streaming_synthesizes_each_sentence_in_order(tmp_path: Path) -> None:
    sidecar = FakeSidecar(_script())
    gateway = FakeGateway(["First sentence. Second sentence."])
    loop, tts = _loop(tmp_path, sidecar, gateway)

    await loop.run_once()

    assert tts.texts == ["First sentence.", "Second sentence."]
    pcm = [record[1] for record in sidecar.records if record[0] == "spk_pcm"]
    assert pcm.index(b"pcm:First sentence.") < pcm.index(b"pcm:Second sentence.")


@pytest.mark.asyncio
async def test_bargein_stops_playback_and_rearms(tmp_path: Path) -> None:
    sidecar = FakeSidecar(_script(), bargein_after_pcm_chunks=2)
    gateway = FakeGateway(["First sentence. Second sentence."])
    loop, _ = _loop(tmp_path, sidecar, gateway)

    await loop.run_once()

    command_types = _command_types(sidecar)
    pcm = [record[1] for record in sidecar.records if record[0] == "spk_pcm"]
    assert "stopPlayback" in command_types
    assert command_types[-1] == "startListening"
    assert b"pcm:Second sentence." not in pcm


@pytest.mark.asyncio
async def test_needs_phone_unlock_prompt_serves_no_sensitive_answer(tmp_path: Path) -> None:
    sidecar = FakeSidecar(_script())
    gateway = FakeGateway(["sensitive answer"], needs_unlock=True)
    loop, tts = _loop(tmp_path, sidecar, gateway)

    await loop.run_once()

    assert gateway.calls == [(MIC, "what time is it")]
    assert tts.texts == [NEEDS_UNLOCK_PROMPT]
    assert "NEEDS_PHONE_UNLOCK" not in tts.texts[0]
    pcm = [record[1] for record in sidecar.records if record[0] == "spk_pcm"]
    assert b"pcm:sensitive answer" not in pcm


@pytest.mark.asyncio
async def test_owner_tier0_and_unknown_guest_streams_proceed(tmp_path: Path) -> None:
    owner_sidecar = FakeSidecar(_script())
    owner_gateway = FakeGateway(["owner tier0."])
    owner_loop, _ = _loop(tmp_path, owner_sidecar, owner_gateway)

    await owner_loop.run_once()

    guest_scope: Scope = f"guest-{GUEST_PERSON_ID}"
    unknown_gateway = FakeGateway([f"served:{guest_scope}."])
    unknown_loop, _ = _loop(tmp_path, FakeSidecar(_script()), unknown_gateway)

    await unknown_loop.run_once()

    assert owner_gateway.calls == [(MIC, "what time is it")]
    assert unknown_gateway.calls == [(MIC, "what time is it")]
    assert OWNER_PERSON_ID != GUEST_PERSON_ID


def test_latency_timers_under_and_over_budget() -> None:
    ticks = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.7])
    timer = StageTimer(lambda: next(ticks))
    for stage in (
        "endpoint",
        "stt_done",
        "speaker_id_done",
        "brain_first_token",
        "first_tts_pcm",
        "first_audio_out",
    ):
        timer.mark(stage)

    budget = LatencyBudget(first_audio_budget_ms=800)
    assert timer.delta("endpoint", "stt_done") == pytest.approx(100)
    assert timer.endpoint_to_first_audio() == pytest.approx(700)
    assert budget.check(timer)

    over_ticks = iter([0.0, 0.9])
    over = StageTimer(lambda: next(over_ticks))
    over.mark("endpoint")
    over.mark("first_audio_out")
    assert not budget.check(over)
