from __future__ import annotations

import os
from abc import ABC, abstractmethod


class WakeWordDetector(ABC):
    @abstractmethod
    def feed(self, pcm: bytes) -> bool:
        """Return True when the current PCM window contains the wake word."""


class FakeWakeWord(WakeWordDetector):
    def __init__(self, trigger_after_n: int | None = None) -> None:
        self._trigger_after_n = trigger_after_n
        self._feeds = 0
        self._triggered = False

    def trigger(self) -> None:
        self._triggered = True

    def feed(self, pcm: bytes) -> bool:
        self._feeds += 1
        if self._triggered:
            self._triggered = False
            return True
        return self._trigger_after_n is not None and self._feeds >= self._trigger_after_n


class OpenWakeWordDetector(WakeWordDetector):
    """GATED real openWakeWord detector; imports the model runtime only on hardware runs."""

    def __init__(self) -> None:
        if os.environ.get("ARTEMIS_AUDIO_HW") != "1":
            self._model: object | None = None
            return
        from openwakeword.model import Model  # type: ignore[import-not-found]

        self._model = Model()

    def feed(self, pcm: bytes) -> bool:
        if self._model is None:
            return False
        raise NotImplementedError("real openWakeWord PCM adaptation is GATED hardware work")
