from __future__ import annotations

import asyncio
from typing import Protocol

from artemis.sidecar.audio.aec import NullAEC
from artemis.sidecar.audio.ipc_server import IPCServer
from artemis.sidecar.audio.playback import FakePlayback
from artemis.sidecar.audio.protocol import (
    CHANNELS,
    SAMPLE_RATE,
    Bargein,
    JsonObject,
    PlaybackFinished,
    PlaybackStarted,
    SpeechEnd,
    SpeechStart,
    StatusEvent,
    WakeDetected,
    message_to_dict,
)
from artemis.sidecar.audio.state_machine import AudioState, AudioStateMachine, InvalidTransition
from artemis.sidecar.audio.vad import BargeInGate, VADDetector, VADEvent
from artemis.sidecar.audio.wake import WakeWordDetector


class CaptureLike(Protocol):
    queue: asyncio.Queue[bytes]


class PlaybackLike(Protocol):
    def enqueue_pcm(self, data: bytes) -> None: ...
    def flush(self) -> None: ...


class AECLike(Protocol):
    def process(self, mic_frame: bytes, ref_frame: bytes) -> bytes: ...


class AudioOrchestrator:
    def __init__(
        self,
        *,
        capture: CaptureLike,
        wake: WakeWordDetector,
        vad: VADDetector,
        playback: PlaybackLike,
        ipc_server: IPCServer,
        aec: AECLike | None = None,
        max_speech_s: float = 30.0,
    ) -> None:
        self.capture = capture
        self.wake = wake
        self.vad = vad
        self.playback = playback
        self.ipc_server = ipc_server
        self.aec = aec if aec is not None else NullAEC()
        self.max_speech_s = max_speech_s
        self.state_machine = AudioStateMachine()
        self.barge_in_gate = BargeInGate()
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            frame = await self.capture.queue.get()
            await self.process_capture_frame(frame)

    def stop(self) -> None:
        self._running = False

    async def handle_command(self, command: JsonObject) -> None:
        command_type = command.get("type")
        if command_type == "startListening":
            if self.state_machine.state is AudioState.WAKE_DETECTED:
                self.state_machine.transition("start_listening")
                self.state_machine.start_capture_timer(self.max_speech_s, self._on_max_duration)
        elif command_type == "stopListening":
            self.state_machine.transition("stop_listening")
        elif command_type == "play":
            sample_rate = command.get("sampleRate")
            channels = command.get("channels")
            if sample_rate != SAMPLE_RATE or channels != CHANNELS:
                return
            if self.state_machine.state is AudioState.ENDPOINT:
                self.state_machine.transition("awaiting")
            if self.state_machine.state is AudioState.AWAITING_RESPONSE:
                self.state_machine.transition("play")
                await self.ipc_server.send_event(message_to_dict(PlaybackStarted()))
        elif command_type == "stopPlayback":
            self.playback.flush()
            if self.state_machine.state is AudioState.PLAYING:
                self.state_machine.transition("stop_playback")
        elif command_type == "getStatus":
            await self.ipc_server.send_event(
                message_to_dict(StatusEvent(state=self.state_machine.state.name.lower()))
            )

    async def handle_speaker_pcm(self, data: bytes) -> None:
        if len(data) == 0:
            await self._finish_playback()
            return
        self.playback.enqueue_pcm(data)

    async def process_capture_frame(self, frame: bytes) -> None:
        clean_frame = self.aec.process(frame, b"")
        state = self.state_machine.state
        vad_event = self.vad.feed(clean_frame)

        if self.barge_in_gate.should_barge_in(vad_event, state is AudioState.PLAYING):
            self.playback.flush()
            await self.ipc_server.send_event(message_to_dict(Bargein()))
            self.state_machine.transition("barge_in")
            return

        if state is AudioState.IDLE:
            if self.wake.feed(clean_frame):
                self.state_machine.transition("wake")
                await self.ipc_server.send_event(message_to_dict(WakeDetected()))
            return

        if state is AudioState.CAPTURING:
            await self._handle_capture_vad(vad_event)

    async def _handle_capture_vad(self, vad_event: VADEvent) -> None:
        if vad_event is VADEvent.SPEECH_START:
            await self.ipc_server.send_event(message_to_dict(SpeechStart()))
        elif vad_event is VADEvent.SPEECH_END:
            self.state_machine.transition("speech_end", reason="endpoint")
            await self.ipc_server.send_event(message_to_dict(SpeechEnd(reason="endpoint")))

    async def _on_max_duration(self, reason: str) -> None:
        if reason == "maxDuration":
            await self.ipc_server.send_event(message_to_dict(SpeechEnd(reason="maxDuration")))

    async def _finish_playback(self) -> None:
        if self.state_machine.state is AudioState.PLAYING:
            try:
                self.state_machine.transition("playback_finished")
            except InvalidTransition:
                return
        await self.ipc_server.send_event(message_to_dict(PlaybackFinished()))


def make_fake_orchestrator(ipc_server: IPCServer) -> AudioOrchestrator:
    from artemis.sidecar.audio.capture import FakeCapture
    from artemis.sidecar.audio.vad import FakeVAD
    from artemis.sidecar.audio.wake import FakeWakeWord

    return AudioOrchestrator(
        capture=FakeCapture(),
        wake=FakeWakeWord(),
        vad=FakeVAD(),
        playback=FakePlayback(),
        ipc_server=ipc_server,
    )
