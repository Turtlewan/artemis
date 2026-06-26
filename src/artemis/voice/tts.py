"""Text-to-speech adapters for the Artemis voice port.

``KokoroTTS`` keeps Kokoro resident for the process lifetime. Each
``synthesize`` call handles one sentence or segment and yields 16 kHz mono
Int16 PCM chunks; ``synthesize_stream`` chains those calls sentence-by-sentence.
Generated speech is never written to disk or logs.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from time import perf_counter
from typing import Protocol, cast

import numpy as np
from numpy.typing import NDArray

from artemis.config import Settings
from artemis.voice import PCM_FORMAT

LOGGER = logging.getLogger(__name__)
SAMPLE_RATE = PCM_FORMAT[0]

type _AudioArray = NDArray[np.float32] | NDArray[np.int16]
type _NativeChunk = bytes | _AudioArray | tuple[int, bytes] | tuple[int, _AudioArray]


class TTSError(RuntimeError):
    """Raised when a text-to-speech backend cannot synthesize speech."""


class _TTSBackend(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> Iterable[_NativeChunk]:
        """Yield native model audio chunks for ``text``."""
        ...


def _model_dir(settings: Settings) -> Path:
    configured = os.environ.get("ARTEMIS_MODEL_DIR")
    if configured:
        return Path(configured)
    return settings.data_root / settings.slot / "models"


class KokoroTTS:
    """Warm resident Kokoro TTS adapter producing the M5-a PCM format."""

    def __init__(
        self,
        settings: Settings,
        *,
        model_id: str = "mlx-community/Kokoro-82M",
        voice: str = "af_heart",
    ) -> None:
        self._settings = settings
        self._model_dir = _model_dir(settings)
        self._model_id = model_id
        self._voice = voice
        self._kokoro: _TTSBackend | None = None
        self._warmed = False

    def synthesize(self, text: str) -> Iterator[bytes]:
        """Yield 16 kHz mono Int16 PCM chunks for a single sentence or segment."""
        started = perf_counter()
        try:
            for native in self._kokoro_backend().synthesize(text):
                chunk = self._to_pcm_chunk(native, self._kokoro_backend().sample_rate)
                if chunk:
                    yield chunk
        except Exception as exc:
            raise TTSError("Kokoro TTS synthesis failed") from exc
        finally:
            LOGGER.info("tts backend=kokoro elapsed_ms=%.1f", (perf_counter() - started) * 1000)

    def synthesize_stream(self, sentences: Iterable[str]) -> Iterator[bytes]:
        """Chain one ``synthesize`` call per sentence to preserve streaming boundaries."""
        for sentence in sentences:
            yield from self.synthesize(sentence)

    def warmup(self) -> None:
        """Load Kokoro and run one throwaway synthesis. Safe to call repeatedly."""
        if self._warmed:
            return
        try:
            for _ in self.synthesize("Hello."):
                break
        except Exception as exc:
            raise TTSError("Kokoro TTS warmup failed") from exc
        self._warmed = True

    def _load_kokoro(self) -> _TTSBackend:
        from mlx_audio.tts import KokoroPipeline  # type: ignore[import-not-found]

        return cast(
            _TTSBackend,
            KokoroPipeline(
                model_id=self._model_id, voice=self._voice, cache_dir=str(self._model_dir)
            ),
        )

    def _kokoro_backend(self) -> _TTSBackend:
        if self._kokoro is None:
            self._kokoro = self._load_kokoro()
        return self._kokoro

    def _to_pcm_chunk(self, chunk: _NativeChunk, default_rate: int) -> bytes:
        sample_rate = default_rate
        native: bytes | _AudioArray
        if isinstance(chunk, tuple):
            sample_rate = chunk[0]
            native = chunk[1]
        else:
            native = chunk

        if isinstance(native, bytes):
            samples = np.frombuffer(native, dtype=np.int16).astype(np.float32)
        else:
            samples = native.astype(np.float32, copy=False)
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            if native.dtype != np.dtype(np.int16):
                samples = np.clip(samples, -1.0, 1.0) * np.float32(32767.0)

        if sample_rate != SAMPLE_RATE:
            samples = _resample_linear(samples, sample_rate, SAMPLE_RATE)

        pcm = np.clip(samples, -32768, 32767).astype(np.int16)
        return pcm.tobytes()


def _resample_linear(
    samples: NDArray[np.float32],
    source_rate: int,
    target_rate: int,
) -> NDArray[np.float32]:
    if samples.size == 0 or source_rate == target_rate:
        return samples
    target_size = max(1, round(samples.size * target_rate / source_rate))
    source_positions = np.linspace(0, samples.size - 1, num=samples.size, dtype=np.float32)
    target_positions = np.linspace(0, samples.size - 1, num=target_size, dtype=np.float32)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)


class FakeTTS:
    """Deterministic TTS fake that records sentence-level synthesis calls."""

    def __init__(self, pcm_chunk: bytes = b"\x00\x00\x01\x00") -> None:
        self.pcm_chunk = pcm_chunk
        self.texts: list[str] = []

    def synthesize(self, text: str) -> Iterator[bytes]:
        self.texts.append(text)
        yield self.pcm_chunk

    def synthesize_stream(self, sentences: Iterable[str]) -> Iterator[bytes]:
        for sentence in sentences:
            yield from self.synthesize(sentence)

    def warmup(self) -> None:
        """No-op warmup for compatibility with app startup."""


__all__ = ["FakeTTS", "KokoroTTS", "TTSError"]
