"""Voice ports — audio I/O protocols.

All local-disk / no-network-I/O ports — sync (ASYNC PORT RULE).
Audio is represented as ``bytes`` (PCM frames).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from artemis.ports.types import PersonId


@runtime_checkable
class WakeWord(Protocol):
    """Wake-word detection."""

    def detect(self, frame: bytes) -> bool:
        """Return True if the wake word is detected in the frame."""
        ...


@runtime_checkable
class VAD(Protocol):
    """Voice activity detection."""

    def is_speech(self, frame: bytes) -> bool:
        """Return True if the frame contains speech."""
        ...


@runtime_checkable
class Stt(Protocol):
    """Speech-to-text."""

    def transcribe(self, audio: bytes, *, language: str | None = None) -> str:
        """Transcribe audio to text."""
        ...


@runtime_checkable
class Tts(Protocol):
    """Text-to-speech."""

    def synthesize(self, text: str) -> Iterator[bytes]:
        """Synthesise text to audio chunks (streamed sentence-by-sentence)."""
        ...


@runtime_checkable
class SpeakerID(Protocol):
    """Speaker identification (identity, not authentication)."""

    def identify(self, audio: bytes) -> PersonId | None:
        """Identify the speaker; returns None for unknown/guest."""
        ...


@runtime_checkable
class AudioFrontend(Protocol):
    """Audio capture and playback."""

    def capture(self) -> Iterator[bytes]:
        """Capture microphone audio as a stream of PCM frames."""
        ...

    def play(self, audio: Iterator[bytes]) -> None:
        """Play audio from a stream of PCM frames."""
        ...
