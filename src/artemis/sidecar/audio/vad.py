from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Iterable
from enum import Enum, auto


class VADEvent(Enum):
    NONE = auto()
    SPEECH_START = auto()
    SPEECH_END = auto()


class VADDetector(ABC):
    @abstractmethod
    def feed(self, pcm: bytes) -> VADEvent:
        """Return the VAD event for the current PCM frame."""


class FakeVAD(VADDetector):
    def __init__(self, events: Iterable[VADEvent] = ()) -> None:
        self._events = list(events)

    def feed(self, pcm: bytes) -> VADEvent:
        if not self._events:
            return VADEvent.NONE
        return self._events.pop(0)

    def push(self, event: VADEvent) -> None:
        self._events.append(event)


class SileroVAD(VADDetector):
    """GATED Silero VAD v5 detector; imports torch/silero only on hardware runs."""

    def __init__(self) -> None:
        if os.environ.get("ARTEMIS_AUDIO_HW") != "1":
            self._model: object | None = None
            return
        import torch  # type: ignore[import-not-found]
        from silero_vad import load_silero_vad  # type: ignore[import-not-found]

        self._torch = torch
        self._model = load_silero_vad()

    def feed(self, pcm: bytes) -> VADEvent:
        if self._model is None:
            return VADEvent.NONE
        raise NotImplementedError("real Silero VAD PCM adaptation is GATED hardware work")


class BargeInGate:
    def should_barge_in(self, event: VADEvent, is_playing: bool) -> bool:
        return is_playing and event is VADEvent.SPEECH_START
