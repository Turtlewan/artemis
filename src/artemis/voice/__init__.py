"""Voice adapter helpers.

``PCM_FORMAT`` is the frozen M5-a sidecar audio contract: 16 kHz, mono,
signed 16-bit little-endian PCM.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from artemis.ports.voice import Stt, Tts

PCM_FORMAT = (16000, 1, "int16")


@runtime_checkable
class _Warmable(Protocol):
    def warmup(self) -> None:
        """Load and prime resident model state."""
        ...


def warmup_all(stt: Stt, tts: Tts) -> None:
    """Warm both voice adapters when they expose an idempotent ``warmup`` method."""
    if isinstance(stt, _Warmable):
        stt.warmup()
    if isinstance(tts, _Warmable):
        tts.warmup()


__all__ = ["PCM_FORMAT", "warmup_all"]
