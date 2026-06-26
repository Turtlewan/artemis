from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pytest
from numpy.typing import NDArray

from artemis.config import Settings
from artemis.ports.voice import Stt, Tts
from artemis.voice import PCM_FORMAT, warmup_all
from artemis.voice.stt import FakeSTT, ParakeetWhisperSTT
from artemis.voice.tts import FakeTTS, KokoroTTS


class _RecorderSTT:
    def __init__(self, name: str, transcript: str, calls: list[str], *, fail: bool = False) -> None:
        self._name = name
        self._transcript = transcript
        self._calls = calls
        self._fail = fail

    def transcribe(
        self,
        audio: NDArray[np.int16],
        *,
        sample_rate: int,
        language: str | None = None,
    ) -> str:
        del audio, sample_rate, language
        self._calls.append(self._name)
        if self._fail:
            raise RuntimeError("backend failed")
        return self._transcript


class _RecorderSTTAdapter(ParakeetWhisperSTT):
    def __init__(self, calls: list[str], *, parakeet_fails: bool = False) -> None:
        super().__init__(Settings())
        self._calls = calls
        self._parakeet_fails = parakeet_fails

    def _load_parakeet(self) -> _RecorderSTT:
        return _RecorderSTT(
            "parakeet", "parakeet transcript", self._calls, fail=self._parakeet_fails
        )

    def _load_whisper(self) -> _RecorderSTT:
        return _RecorderSTT("whisper", "whisper transcript", self._calls)


class _StubKokoro:
    sample_rate = 24000

    def synthesize(self, text: str) -> Iterable[bytes]:
        del text
        yield np.array([0, 100, 0, -100], dtype=np.int16).tobytes()


class _StubKokoroTTS(KokoroTTS):
    def _load_kokoro(self) -> _StubKokoro:
        return _StubKokoro()


def test_port_conformance_type_checks() -> None:
    stt_port: Stt = ParakeetWhisperSTT(Settings())
    tts_port: Tts = KokoroTTS(Settings())
    stt: Stt = _RecorderSTTAdapter([])
    tts: Tts = _StubKokoroTTS(Settings())

    assert stt_port is not None
    assert tts_port is not None
    assert stt.transcribe(b"\x00\x00", language="en") == "parakeet transcript"
    assert list(tts.synthesize("Hello."))


def test_fake_stt_records_routing_without_models() -> None:
    stt = FakeSTT()

    assert stt.transcribe(b"", language=None) == "fake transcript"
    assert stt.transcribe(b"", language="en-US") == "fake transcript"
    assert stt.transcribe(b"", language="zh") == "fake transcript"

    assert stt.backends == ["parakeet", "parakeet", "whisper"]


def test_stt_routes_by_language_hint() -> None:
    calls: list[str] = []
    stt = _RecorderSTTAdapter(calls)
    pcm = np.zeros(4, dtype=np.int16).tobytes()

    assert stt.transcribe(pcm, language=None) == "parakeet transcript"
    assert stt.transcribe(pcm, language="en-US") == "parakeet transcript"
    assert stt.transcribe(pcm, language="zh") == "whisper transcript"

    assert calls == ["parakeet", "parakeet", "whisper"]


def test_stt_degrades_from_parakeet_to_whisper() -> None:
    calls: list[str] = []
    stt = _RecorderSTTAdapter(calls, parakeet_fails=True)

    assert stt.transcribe(b"\x00\x00", language="en-US") == "whisper transcript"
    assert calls == ["parakeet", "whisper"]


def test_tts_sentence_streaming_records_each_sentence() -> None:
    tts = FakeTTS()

    chunks = list(tts.synthesize_stream(["Hello.", "World."]))

    assert chunks == [b"\x00\x00\x01\x00", b"\x00\x00\x01\x00"]
    assert tts.texts == ["Hello.", "World."]


def test_pcm_format_and_tts_chunk_shape() -> None:
    assert PCM_FORMAT == (16000, 1, "int16")

    chunks = list(FakeTTS().synthesize("Hello."))
    assert chunks
    assert all(len(chunk) % 2 == 0 for chunk in chunks)


def test_kokoro_resamples_native_audio_to_pcm16() -> None:
    tts = _StubKokoroTTS(Settings())

    chunks = list(tts.synthesize("Hello."))

    assert chunks
    assert all(len(chunk) % 2 == 0 for chunk in chunks)


def test_warmup_all_accepts_fakes() -> None:
    warmup_all(FakeSTT(), FakeTTS())


@pytest.mark.parametrize("language", [None, "en", "en-US"])
def test_english_language_hints_use_parakeet(language: str | None) -> None:
    stt = FakeSTT()

    stt.transcribe(b"", language=language)

    assert stt.backends == ["parakeet"]
