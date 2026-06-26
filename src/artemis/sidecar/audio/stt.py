from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod


class STTEngine(ABC):
    @abstractmethod
    async def transcribe(self, pcm_queue: asyncio.Queue[bytes | None]) -> str:
        """Consume PCM frames until sentinel None; return transcript."""


class FakeSTT(STTEngine):
    def __init__(self, transcript: str = "") -> None:
        self.transcript = transcript

    async def transcribe(self, pcm_queue: asyncio.Queue[bytes | None]) -> str:
        while await pcm_queue.get() is not None:
            pass
        return self.transcript


class MoonshineSTT(STTEngine):
    """GATED Moonshine v2 Small streaming CPU STT."""

    def __init__(self) -> None:
        if os.environ.get("ARTEMIS_AUDIO_HW") != "1":
            self._transcriber: object | None = None
            return
        from moonshine_voice import ModelArch, Transcriber  # type: ignore[import-not-found]

        self._transcriber = Transcriber(model=ModelArch.SMALL_STREAMING)

    async def transcribe(self, pcm_queue: asyncio.Queue[bytes | None]) -> str:
        if self._transcriber is None:
            while await pcm_queue.get() is not None:
                pass
            return ""
        raise NotImplementedError("real Moonshine streaming STT is GATED hardware work")


class FasterWhisperSTT(STTEngine):
    """GATED faster-whisper fallback STT."""

    def __init__(self) -> None:
        if os.environ.get("ARTEMIS_AUDIO_HW") != "1":
            self._model: object | None = None
            return
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        self._model = WhisperModel("distil-large-v3", compute_type="int8")

    async def transcribe(self, pcm_queue: asyncio.Queue[bytes | None]) -> str:
        if self._model is None:
            while await pcm_queue.get() is not None:
                pass
            return ""
        raise NotImplementedError("real faster-whisper STT is GATED hardware work")
