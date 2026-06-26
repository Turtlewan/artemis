from __future__ import annotations

from artemis.sidecar.audio.capture import FakeCapture
from artemis.sidecar.audio.orchestrator import AudioOrchestrator
from artemis.sidecar.audio.playback import FakePlayback
from artemis.sidecar.audio.state_machine import AudioState
from artemis.sidecar.audio.vad import FakeVAD, VADEvent
from artemis.sidecar.audio.wake import FakeWakeWord


class RecordingIPC:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.flush_was_done: bool | None = None
        self.playback: FakePlayback | None = None

    async def send_event(self, msg: dict[str, object]) -> None:
        if msg["type"] == "bargein":
            assert self.playback is not None
            self.flush_was_done = self.playback.flush_called
        self.events.append(msg)


async def test_barge_in_flushes_before_event() -> None:
    playback = FakePlayback()
    ipc = RecordingIPC()
    ipc.playback = playback
    orchestrator = AudioOrchestrator(
        capture=FakeCapture(),
        wake=FakeWakeWord(),
        vad=FakeVAD([VADEvent.SPEECH_START]),
        playback=playback,
        ipc_server=ipc,  # type: ignore[arg-type]
    )
    orchestrator.state_machine.state = AudioState.PLAYING

    await orchestrator.process_capture_frame(b"\x00\x00")

    assert playback.flush_called
    assert ipc.flush_was_done is True
    assert ipc.events == [{"type": "bargein"}]
    assert orchestrator.state_machine.state is AudioState.CAPTURING


async def test_speech_start_while_idle_is_noop() -> None:
    playback = FakePlayback()
    ipc = RecordingIPC()
    orchestrator = AudioOrchestrator(
        capture=FakeCapture(),
        wake=FakeWakeWord(),
        vad=FakeVAD([VADEvent.SPEECH_START]),
        playback=playback,
        ipc_server=ipc,  # type: ignore[arg-type]
    )

    await orchestrator.process_capture_frame(b"\x00\x00")

    assert not playback.flush_called
    assert ipc.events == []
    assert orchestrator.state_machine.state is AudioState.IDLE
