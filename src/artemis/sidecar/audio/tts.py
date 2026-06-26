from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable


class TTSEngine(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yield 16 kHz/mono/Int16-LE PCM chunks."""
        if False:
            yield b""


class FakeTTS(TTSEngine):
    def __init__(self, chunks: Iterable[bytes] = (b"\x00\x00",)) -> None:
        self._chunks = list(chunks)

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class KokoroTTS(TTSEngine):
    """GATED Kokoro-82M PyTorch CUDA TTS; 24 kHz output is resampled to 16 kHz."""

    def __init__(self) -> None:
        if os.environ.get("ARTEMIS_AUDIO_HW") != "1":
            self._pipeline: object | None = None
            return
        import scipy.signal  # type: ignore[import-not-found,import-untyped,unused-ignore]
        import torch  # type: ignore[import-not-found]
        from kokoro import KPipeline  # type: ignore[import-not-found]

        self._torch = torch
        self._resample_poly = scipy.signal.resample_poly
        self._pipeline = KPipeline(lang_code="a")

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        if self._pipeline is None:
            return
        raise NotImplementedError("real Kokoro synthesis/resampling is GATED hardware work")
        if False:
            yield b""


class PiperTTS(TTSEngine):
    """GATED Piper CPU fallback TTS; native 16 kHz model output expected."""

    def __init__(self) -> None:
        if os.environ.get("ARTEMIS_AUDIO_HW") != "1":
            self._voice: object | None = None
            return
        import piper  # type: ignore[import-not-found]

        self._piper = piper

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        if self._voice is None:
            return
        raise NotImplementedError("real Piper synthesis is GATED hardware work")
        if False:
            yield b""
