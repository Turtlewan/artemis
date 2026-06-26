"""Voice-loop orchestrator for wake, endpoint, STT, Gateway streaming, and TTS."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import AsyncIterator, Iterator
from typing import Protocol, cast

from artemis.config import Settings, get_settings
from artemis.gateway import NEEDS_UNLOCK_PROMPT, Gateway, NeedsPhoneUnlock, compose_brain
from artemis.ports.voice import AudioFrontend, Stt, Tts
from artemis.sidecar.audio.protocol import JsonObject
from artemis.voice.latency import LatencyBudget, StageTimer
from artemis.voice.sidecar_client import SidecarAudioFrontend
from artemis.voice.stt import ParakeetWhisperSTT
from artemis.voice.tts import KokoroTTS

LOGGER = logging.getLogger(__name__)
_SENTENCE_RE = re.compile(r"^(.+?[.!?])(\s+|$)", re.DOTALL)
_SORRY = "Sorry, try again."


class VoiceFrontend(AudioFrontend, Protocol):
    """Runtime methods the orchestrator needs beyond the sync AudioFrontend port."""

    def capture_async(self) -> AsyncIterator[bytes]:
        """Yield captured microphone PCM."""
        ...

    async def play_async(self, audio: AsyncIterator[bytes], cancel: asyncio.Event) -> None:
        """Play PCM until exhausted or cancelled."""
        ...

    async def send_command(self, command: JsonObject) -> None:
        """Send an audio-sidecar command."""
        ...

    async def next_event(self, timeout: float | None = None) -> JsonObject:
        """Return the next audio-sidecar event."""
        ...


class VoiceLoop:
    """Thin custom cascade with instant ack, sentence TTS, and barge-in cancellation."""

    def __init__(
        self,
        frontend: VoiceFrontend,
        stt: Stt,
        tts: Tts,
        gateway: Gateway,
        settings: Settings,
        ack_pcm: bytes,
        budget: LatencyBudget,
    ) -> None:
        self.frontend = frontend
        self.stt = stt
        self.tts = tts
        self.gateway = gateway
        self.settings = settings
        self.ack_pcm = ack_pcm
        self.budget = budget
        self.last_timer: StageTimer | None = None
        self.idle = True

    async def run(self) -> None:
        """Run turns forever until cancelled."""
        while True:
            await self.run_once()

    async def run_once(self) -> None:
        """Run one wake-to-idle voice turn, degrading failures to a short prompt."""
        timer = StageTimer()
        self.last_timer = timer
        cancel = asyncio.Event()
        self.idle = False
        watcher: asyncio.Task[None] | None = None
        try:
            await self._wait_for_wake()
            await self.frontend.send_command({"type": "startListening"})
            utterance = await self._capture_until_endpoint(timer)
            transcript = self.stt.transcribe(utterance)
            timer.mark("stt_done")
            watcher = asyncio.create_task(self._watch_bargein(cancel))
            await self._play_pcm([self.ack_pcm], cancel)
            if cancel.is_set():
                return
            stream = self.gateway.handle_voice_stream(utterance, transcript)
            await self._stream_response(stream, timer, cancel)
        except NeedsPhoneUnlock:
            timer.mark("speaker_id_done")
            await self._play_text(NEEDS_UNLOCK_PROMPT, timer, cancel, mark_brain=False)
        except Exception:
            LOGGER.warning("voice_loop turn failed", exc_info=True)
            await self._play_text(_SORRY, timer, cancel, mark_brain=False)
        finally:
            if watcher is not None:
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
            self.idle = True
            if all(stage in timer.marks for stage in ("endpoint", "first_audio_out")):
                self.budget.log(timer)

    async def _wait_for_wake(self) -> None:
        while True:
            event = await self.frontend.next_event()
            LOGGER.debug("voice_event type=%s", event.get("type"))
            if event.get("type") == "wakeDetected":
                return

    async def _capture_until_endpoint(self, timer: StageTimer) -> bytes:
        chunks: list[bytes] = []
        capture = self.frontend.capture_async().__aiter__()
        event_task: asyncio.Task[JsonObject] = asyncio.create_task(self.frontend.next_event())
        pcm_task: asyncio.Future[bytes] = asyncio.ensure_future(capture.__anext__())
        while True:
            event_future = cast(asyncio.Future[object], event_task)
            pcm_future = cast(asyncio.Future[object], pcm_task)
            done, pending = await asyncio.wait(
                {event_future, pcm_future}, return_when=asyncio.FIRST_COMPLETED
            )
            need_next_pcm = False
            if pcm_future in done:
                try:
                    chunks.append(pcm_task.result())
                except StopAsyncIteration:
                    pass
                need_next_pcm = True
            if event_future in done:
                event = event_task.result()
                LOGGER.debug("voice_event type=%s", event.get("type"))
                if event.get("type") == "speechEnd" and event.get("reason") == "endpoint":
                    for task in pending:
                        task.cancel()
                    timer.mark("endpoint")
                    return b"".join(chunks)
                event_task = asyncio.create_task(self.frontend.next_event())
            if need_next_pcm:
                pcm_task = asyncio.ensure_future(capture.__anext__())

    async def _stream_response(
        self,
        stream: AsyncIterator[str],
        timer: StageTimer,
        cancel: asyncio.Event,
    ) -> None:
        buffer = ""
        first = True
        async for segment in stream:
            if cancel.is_set():
                return
            if first:
                timer.mark("speaker_id_done")
                timer.mark("brain_first_token")
                first = False
            buffer += segment
            sentences, buffer = _pop_sentences(buffer)
            for sentence in sentences:
                await self._play_sentence(sentence, timer, cancel)
                if cancel.is_set():
                    return
        if first:
            timer.mark("speaker_id_done")
            timer.mark("brain_first_token")
        tail = buffer.strip()
        if tail and not cancel.is_set():
            await self._play_sentence(tail, timer, cancel)

    async def _play_text(
        self,
        text: str,
        timer: StageTimer,
        cancel: asyncio.Event,
        *,
        mark_brain: bool,
    ) -> None:
        if mark_brain and "brain_first_token" not in timer.marks:
            timer.mark("brain_first_token")
        await self._play_sentence(text, timer, cancel)

    async def _play_sentence(self, sentence: str, timer: StageTimer, cancel: asyncio.Event) -> None:
        def chunks() -> Iterator[bytes]:
            yield from self.tts.synthesize(sentence)

        async def source() -> AsyncIterator[bytes]:
            for chunk in chunks():
                if "first_tts_pcm" not in timer.marks:
                    timer.mark("first_tts_pcm")
                yield chunk
                await asyncio.sleep(0)

        await self.frontend.play_async(source(), cancel)
        if "first_audio_out" not in timer.marks and not cancel.is_set():
            timer.mark("first_audio_out")

    async def _play_pcm(self, chunks: list[bytes], cancel: asyncio.Event) -> None:
        async def source() -> AsyncIterator[bytes]:
            for chunk in chunks:
                yield chunk
                await asyncio.sleep(0)

        await self.frontend.play_async(source(), cancel)

    async def _watch_bargein(self, cancel: asyncio.Event) -> None:
        while not cancel.is_set():
            event = await self.frontend.next_event()
            LOGGER.debug("voice_event type=%s", event.get("type"))
            if event.get("type") == "bargein":
                cancel.set()
                await self.frontend.send_command({"type": "stopPlayback"})
                await self.frontend.send_command({"type": "startListening"})
                return


def _pop_sentences(text: str, *, max_chars: int = 220) -> tuple[list[str], str]:
    sentences: list[str] = []
    remainder = text
    while True:
        match = _SENTENCE_RE.match(remainder)
        if match is None:
            break
        sentences.append(match.group(1).strip())
        remainder = remainder[match.end() :]
    if len(remainder) >= max_chars:
        sentences.append(remainder.strip())
        remainder = ""
    return sentences, remainder


def compose_voice_loop(settings: Settings | None = None) -> VoiceLoop:
    """Build a lazy voice loop without contacting the sidecar or loading models."""
    resolved_settings = settings if settings is not None else get_settings()
    frontend = SidecarAudioFrontend(settings=resolved_settings)
    stt = ParakeetWhisperSTT(resolved_settings)
    tts = KokoroTTS(resolved_settings)
    brain = compose_brain(resolved_settings)
    gateway = Gateway(brain, settings=resolved_settings)
    ack_pcm = b"\x00\x00\x00\x00"
    budget = LatencyBudget()
    return VoiceLoop(frontend, stt, tts, gateway, resolved_settings, ack_pcm, budget)
