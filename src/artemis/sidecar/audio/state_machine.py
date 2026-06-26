from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import Enum, auto

from artemis.sidecar.audio.protocol import SpeechEndReason


class AudioState(Enum):
    IDLE = auto()
    WAKE_DETECTED = auto()
    CAPTURING = auto()
    ENDPOINT = auto()
    AWAITING_RESPONSE = auto()
    PLAYING = auto()


class InvalidTransition(RuntimeError):  # noqa: N818
    def __init__(self, state: AudioState, event: str) -> None:
        super().__init__(f"invalid audio transition from {state.name} on {event!r}")


MaxDurationCallback = Callable[[SpeechEndReason], Awaitable[None] | None]


class AudioStateMachine:
    _TRANSITIONS: dict[tuple[AudioState, str], AudioState] = {
        (AudioState.IDLE, "wake"): AudioState.WAKE_DETECTED,
        (AudioState.WAKE_DETECTED, "start_listening"): AudioState.CAPTURING,
        (AudioState.CAPTURING, "speech_end"): AudioState.ENDPOINT,
        (AudioState.ENDPOINT, "awaiting"): AudioState.AWAITING_RESPONSE,
        (AudioState.AWAITING_RESPONSE, "play"): AudioState.PLAYING,
        (AudioState.PLAYING, "barge_in"): AudioState.CAPTURING,
        (AudioState.PLAYING, "playback_finished"): AudioState.IDLE,
        (AudioState.PLAYING, "stop_playback"): AudioState.IDLE,
    }

    def __init__(self) -> None:
        self.state = AudioState.IDLE
        self.last_speech_end_reason: SpeechEndReason | None = None
        self._timer_task: asyncio.Task[None] | None = None

    def transition(self, event: str, *, reason: SpeechEndReason | None = None) -> AudioState:
        if event == "stop_listening":
            self.cancel_capture_timer()
            self.state = AudioState.IDLE
            return self.state

        next_state = self._TRANSITIONS.get((self.state, event))
        if next_state is None:
            raise InvalidTransition(self.state, event)
        if event == "speech_end":
            if reason is None:
                raise ValueError("speech_end transition requires a reason")
            self.last_speech_end_reason = reason
            self.cancel_capture_timer()
        self.state = next_state
        return self.state

    def start_capture_timer(
        self, timeout_s: float, on_max_duration: MaxDurationCallback | None = None
    ) -> None:
        self.cancel_capture_timer()
        self._timer_task = asyncio.create_task(self._run_capture_timer(timeout_s, on_max_duration))

    def cancel_capture_timer(self) -> None:
        if self._timer_task is not None and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = None

    async def _run_capture_timer(
        self, timeout_s: float, on_max_duration: MaxDurationCallback | None
    ) -> None:
        try:
            await asyncio.sleep(timeout_s)
            if self.state != AudioState.CAPTURING:
                return
            self.transition("speech_end", reason="maxDuration")
            if on_max_duration is not None:
                result = on_max_duration("maxDuration")
                if result is not None:
                    await result
        except asyncio.CancelledError:
            return
