"""Latency instrumentation for the voice cascade."""

from __future__ import annotations

import logging
from collections.abc import Callable
from time import monotonic

LOGGER = logging.getLogger(__name__)

VOICE_STAGES = (
    "endpoint",
    "stt_done",
    "speaker_id_done",
    "brain_first_token",
    "first_tts_pcm",
    "first_audio_out",
)


class StageTimer:
    """Named monotonic timestamps for one voice turn."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self.marks: dict[str, float] = {}

    def mark(self, stage: str) -> None:
        """Record the current monotonic timestamp for ``stage``."""
        self.marks[stage] = self._clock()

    def delta(self, a: str, b: str) -> float:
        """Return elapsed milliseconds from stage ``a`` to stage ``b``."""
        return (self.marks[b] - self.marks[a]) * 1000.0

    def endpoint_to_first_audio(self) -> float:
        """Return endpoint-to-first-audio latency in milliseconds."""
        return self.delta("endpoint", "first_audio_out")


class LatencyBudget:
    """Checks and logs the endpoint-to-first-audio voice budget."""

    def __init__(self, first_audio_budget_ms: float = 800.0) -> None:
        self.first_audio_budget_ms = first_audio_budget_ms

    def check(self, timer: StageTimer) -> bool:
        """Return true when first audio was emitted within budget."""
        return timer.endpoint_to_first_audio() <= self.first_audio_budget_ms

    def log(self, timer: StageTimer) -> None:
        """Log per-stage timing without logging audio or transcripts."""
        if not all(stage in timer.marks for stage in VOICE_STAGES):
            missing = [stage for stage in VOICE_STAGES if stage not in timer.marks]
            LOGGER.info("voice_latency status=incomplete missing=%s", ",".join(missing))
            return
        endpoint_to_first_audio = timer.endpoint_to_first_audio()
        level = (
            logging.WARNING
            if endpoint_to_first_audio > self.first_audio_budget_ms
            else logging.INFO
        )
        LOGGER.log(
            level,
            (
                "voice_latency endpoint_to_first_audio_ms=%.1f "
                "endpoint_to_stt_ms=%.1f stt_to_speaker_ms=%.1f "
                "speaker_to_brain_ms=%.1f brain_to_tts_ms=%.1f tts_to_audio_ms=%.1f "
                "budget_ms=%.1f"
            ),
            endpoint_to_first_audio,
            timer.delta("endpoint", "stt_done"),
            timer.delta("stt_done", "speaker_id_done"),
            timer.delta("speaker_id_done", "brain_first_token"),
            timer.delta("brain_first_token", "first_tts_pcm"),
            timer.delta("first_tts_pcm", "first_audio_out"),
            self.first_audio_budget_ms,
        )
