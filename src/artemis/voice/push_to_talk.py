"""Push-to-talk capture for overlay Ask turns."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol, cast

from artemis.gateway import Gateway
from artemis.ports.types import Scope
from artemis.ports.voice import AudioFrontend, Stt
from artemis.sidecar.audio.protocol import JsonObject
from artemis.speakable import DisplaySeg, SpeakSeg


class _PushToTalkFrontend(AudioFrontend, Protocol):
    def capture_async(self) -> AsyncIterator[bytes]:
        """Yield captured microphone PCM."""
        ...

    async def send_command(self, command: JsonObject) -> None:
        """Send an audio-sidecar command."""
        ...

    async def next_event(self, timeout: float | None = None) -> JsonObject:
        """Return the next audio-sidecar event."""
        ...


class PushToTalkCapture:
    """Reuse M5-d capture+STT for one on-demand overlay utterance."""

    def __init__(self, frontend: AudioFrontend, stt: Stt) -> None:
        self._frontend = cast(_PushToTalkFrontend, frontend)
        self._stt = stt

    async def capture_transcript(self) -> str:
        """Capture PCM until endpoint and transcribe it without logging private data."""
        await self._frontend.send_command({"type": "startListening"})
        utterance_pcm = await self._capture_until_endpoint()
        return self._stt.transcribe(utterance_pcm)

    async def _capture_until_endpoint(self) -> bytes:
        chunks: list[bytes] = []
        capture = self._frontend.capture_async().__aiter__()
        event_task: asyncio.Task[JsonObject] = asyncio.create_task(self._frontend.next_event())
        pcm_task: asyncio.Future[bytes] = asyncio.ensure_future(capture.__anext__())
        while True:
            event_future = cast(asyncio.Future[object], event_task)
            pcm_future = cast(asyncio.Future[object], pcm_task)
            done, pending = await asyncio.wait(
                {event_future, pcm_future},
                return_when=asyncio.FIRST_COMPLETED,
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
                if event.get("type") == "speechEnd" and event.get("reason") == "endpoint":
                    for task in pending:
                        task.cancel()
                    return b"".join(chunks)
                event_task = asyncio.create_task(self._frontend.next_event())
            if need_next_pcm:
                pcm_task = asyncio.ensure_future(capture.__anext__())


async def overlay_voice_turn(
    gateway: Gateway,
    capture: PushToTalkCapture,
    *,
    scope: Scope,
    speak: bool = True,
) -> tuple[AsyncIterator[DisplaySeg], AsyncIterator[SpeakSeg]]:
    """Route one captured transcript into the unified Ask seam as query data."""
    transcript = await capture.capture_transcript()
    return await gateway.handle_ask_unified(transcript, scope_or_identity=scope, speak=speak)
