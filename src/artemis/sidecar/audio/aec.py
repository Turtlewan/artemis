from __future__ import annotations

import os


class AECProcessor:
    """LiveKit RTC APM wrapper.

    Real APM runs only when ARTEMIS_AUDIO_HW=1 and ARTEMIS_HEADPHONES != "1".
    Reverse-stream clocking must feed loopback and mic frames at matching sample
    timestamps; that production-quality open-mic path remains hardware-gated.
    """

    def __init__(self) -> None:
        self._apm: object | None = None
        if os.environ.get("ARTEMIS_AUDIO_HW") != "1" or os.environ.get("ARTEMIS_HEADPHONES") == "1":
            return
        import pyaudiowpatch  # type: ignore[import-not-found]  # noqa: F401
        from livekit import rtc  # type: ignore[import-not-found]

        self._rtc = rtc

    def process(self, mic_frame: bytes, ref_frame: bytes) -> bytes:
        if self._apm is None:
            return mic_frame
        raise NotImplementedError(
            "real LiveKit APM reverse-stream processing is GATED hardware work"
        )


class NullAEC:
    def process(self, mic_frame: bytes, ref_frame: bytes) -> bytes:
        return mic_frame
