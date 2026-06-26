"""Speech-to-text adapters for the Artemis voice port.

``ParakeetWhisperSTT`` routes default and English requests to Parakeet and
non-English requests to Whisper. If Parakeet fails for an English request, the
adapter retries once with Whisper and returns that transcript. Captured audio
and transcripts are never written to disk or logs.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from time import perf_counter
from typing import Protocol, cast

import numpy as np
from numpy.typing import NDArray

from artemis.config import Settings
from artemis.voice import PCM_FORMAT

LOGGER = logging.getLogger(__name__)
SAMPLE_RATE = PCM_FORMAT[0]


class STTError(RuntimeError):
    """Raised when a speech-to-text backend cannot transcribe audio."""


class _STTBackend(Protocol):
    def transcribe(
        self,
        audio: NDArray[np.int16],
        *,
        sample_rate: int,
        language: str | None = None,
    ) -> str:
        """Return transcript text for 16 kHz mono Int16 PCM."""
        ...


def _model_dir(settings: Settings) -> Path:
    configured = os.environ.get("ARTEMIS_MODEL_DIR")
    if configured:
        return Path(configured)
    return settings.data_root / settings.slot / "models"


def _route_backend(language: str | None) -> str:
    return "parakeet" if language is None or language.startswith("en") else "whisper"


class ParakeetWhisperSTT:
    """Parakeet primary STT with Whisper multilingual fallback."""

    def __init__(
        self,
        settings: Settings,
        *,
        parakeet_model_id: str = "mlx-community/parakeet-tdt-0.6b",
        whisper_model_id: str = "mlx-community/whisper-large-v3-turbo",
    ) -> None:
        self._settings = settings
        self._model_dir = _model_dir(settings)
        self._parakeet_model_id = parakeet_model_id
        self._whisper_model_id = whisper_model_id
        self._parakeet: _STTBackend | None = None
        self._whisper: _STTBackend | None = None
        self._warmed = False

    def transcribe(self, audio: bytes, *, language: str | None = None) -> str:
        """Transcribe 16 kHz mono Int16 PCM, routing by language hint."""
        pcm = self._decode_pcm(audio)
        backend = _route_backend(language)
        started = perf_counter()

        if backend == "parakeet":
            try:
                transcript = self._parakeet_backend().transcribe(
                    pcm,
                    sample_rate=SAMPLE_RATE,
                    language=language,
                )
            except Exception:
                LOGGER.info(
                    "stt backend=parakeet status=degrade elapsed_ms=%.1f", self._elapsed(started)
                )
                try:
                    transcript = self._whisper_backend().transcribe(
                        pcm,
                        sample_rate=SAMPLE_RATE,
                        language=language,
                    )
                except Exception as fallback_exc:
                    raise STTError("Parakeet and Whisper STT failed") from fallback_exc
                LOGGER.info("stt backend=whisper status=ok elapsed_ms=%.1f", self._elapsed(started))
                return transcript
        else:
            try:
                transcript = self._whisper_backend().transcribe(
                    pcm,
                    sample_rate=SAMPLE_RATE,
                    language=language,
                )
            except Exception as exc:
                raise STTError("Whisper STT failed") from exc

        LOGGER.info("stt backend=%s status=ok elapsed_ms=%.1f", backend, self._elapsed(started))
        return transcript

    def warmup(self) -> None:
        """Load both backends and run one throwaway inference through each."""
        if self._warmed:
            return
        silence = np.zeros(1, dtype=np.int16)
        try:
            self._parakeet_backend().transcribe(silence, sample_rate=SAMPLE_RATE, language="en")
            self._whisper_backend().transcribe(silence, sample_rate=SAMPLE_RATE, language="zh")
        except Exception as exc:
            raise STTError("STT warmup failed") from exc
        self._warmed = True

    def _load_parakeet(self) -> _STTBackend:
        from parakeet_mlx import from_pretrained  # type: ignore[import-not-found]

        return cast(
            _STTBackend,
            from_pretrained(model_id=self._parakeet_model_id, cache_dir=str(self._model_dir)),
        )

    def _load_whisper(self) -> _STTBackend:
        from mlx_whisper import load_model  # type: ignore[import-not-found]

        return cast(
            _STTBackend,
            load_model(self._whisper_model_id, download_root=str(self._model_dir)),
        )

    def _parakeet_backend(self) -> _STTBackend:
        if self._parakeet is None:
            self._parakeet = self._load_parakeet()
        return self._parakeet

    def _whisper_backend(self) -> _STTBackend:
        if self._whisper is None:
            self._whisper = self._load_whisper()
        return self._whisper

    @staticmethod
    def _decode_pcm(audio: bytes) -> NDArray[np.int16]:
        return np.frombuffer(audio, dtype=np.int16).copy()

    @staticmethod
    def _elapsed(started: float) -> float:
        return (perf_counter() - started) * 1000


class FakeSTT:
    """Deterministic STT fake that records the backend routing choice."""

    def __init__(self, transcript: str = "fake transcript") -> None:
        self.transcript = transcript
        self.backends: list[str] = []

    def transcribe(self, audio: bytes, *, language: str | None = None) -> str:
        del audio
        self.backends.append(_route_backend(language))
        return self.transcript

    def warmup(self) -> None:
        """No-op warmup for compatibility with app startup."""


__all__ = ["FakeSTT", "ParakeetWhisperSTT", "STTError"]
