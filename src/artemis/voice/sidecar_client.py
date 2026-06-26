"""Audio sidecar IPC client and test fake.

The real client mirrors ``IPCServer`` rendezvous: AF_UNIX uses
``<slot>/run/audio.sock``; platforms without AF_UNIX read ``run/audio.port``
and connect to ``127.0.0.1``. The frame protocol is the M5-a 1-byte kind plus
4-byte big-endian length envelope.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from artemis.config import Settings, get_settings
from artemis.sidecar.audio.protocol import (
    AUDIO_FORMAT,
    FrameKind,
    JsonObject,
    decode_frame,
    decode_json,
    encode_frame,
    encode_json,
)

EventSubscriber = Callable[[JsonObject], Awaitable[None] | None]


class SidecarError(RuntimeError):
    """Raised for sidecar error events."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"sidecar error {code}: {message}")
        self.code = code
        self.message = message


class SidecarAudioFrontend:
    """``AudioFrontend`` implementation backed by the M5-a audio sidecar."""

    def __init__(self, run_dir: Path | None = None, *, settings: Settings | None = None) -> None:
        if run_dir is None:
            import artemis.paths as paths

            resolved_settings = settings if settings is not None else get_settings()
            run_dir = paths.slot_root(resolved_settings) / "run"
        self._run_dir = run_dir
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._events: asyncio.Queue[JsonObject] = asyncio.Queue()
        self._mic_pcm: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._subscriber: EventSubscriber | None = None

    def subscribe(self, subscriber: EventSubscriber | None) -> None:
        """Receive JSON events in addition to the internal event queue."""
        self._subscriber = subscriber

    async def connect(self) -> None:
        """Open the sidecar connection lazily."""
        if self._writer is not None:
            return
        af_unix = getattr(socket, "AF_UNIX", None)
        if af_unix is not None:
            unix_socket = socket.socket(af_unix, socket.SOCK_STREAM)
            unix_socket.setblocking(False)
            await asyncio.get_running_loop().sock_connect(
                unix_socket, str(self._run_dir / "audio.sock")
            )
            reader, writer = await asyncio.open_connection(sock=unix_socket)
        else:
            port = int((self._run_dir / "audio.port").read_text(encoding="ascii").strip())
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        self._reader = reader
        self._writer = writer
        self._reader_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        """Close the sidecar connection."""
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
        await self._mic_pcm.put(None)

    def capture(self) -> Iterator[bytes]:
        """Synchronously yield microphone PCM frames."""

        async def collect() -> list[bytes]:
            frames: list[bytes] = []
            async for frame in self.capture_async():
                frames.append(frame)
            return frames

        yield from asyncio.run(collect())

    async def capture_async(self) -> AsyncIterator[bytes]:
        """Yield microphone PCM frames from the buffered reader."""
        await self.connect()
        while True:
            frame = await self._mic_pcm.get()
            if frame is None:
                return
            yield frame

    def play(self, audio: Iterator[bytes]) -> None:
        """Synchronously play PCM frames."""

        async def source() -> AsyncIterator[bytes]:
            for chunk in audio:
                yield chunk

        asyncio.run(self.play_async(source(), asyncio.Event()))

    async def play_async(self, audio: AsyncIterator[bytes], cancel: asyncio.Event) -> None:
        """Send playback PCM until ``audio`` is exhausted or ``cancel`` is set."""
        await self.send_command(
            {
                "type": "play",
                "sampleRate": AUDIO_FORMAT["sampleRate"],
                "channels": AUDIO_FORMAT["channels"],
            }
        )
        async for chunk in audio:
            if cancel.is_set():
                return
            await self._write(encode_frame(FrameKind.SPK_PCM, chunk))

    async def send_command(self, command: JsonObject) -> None:
        """Send a sidecar command JSON frame."""
        await self._write(encode_json(command))

    async def next_event(self, timeout: float | None = None) -> JsonObject:
        """Return the next JSON event."""
        if timeout is None:
            return await self._events.get()
        return await asyncio.wait_for(self._events.get(), timeout)

    async def _write(self, frame: bytes) -> None:
        await self.connect()
        if self._writer is None:
            raise RuntimeError("sidecar connection is closed")
        self._writer.write(frame)
        await self._writer.drain()

    async def _read_loop(self) -> None:
        if self._reader is None:
            raise RuntimeError("sidecar connection is not open")
        buffer = bytearray()
        while True:
            chunk = await self._reader.read(65536)
            if not chunk:
                await self._mic_pcm.put(None)
                return
            buffer.extend(chunk)
            while True:
                decoded = decode_frame(memoryview(buffer))
                if decoded is None:
                    break
                kind, body, consumed = decoded
                del buffer[:consumed]
                await self._dispatch_frame(kind, body)

    async def _dispatch_frame(self, kind: FrameKind, body: bytes) -> None:
        if kind is FrameKind.MIC_PCM:
            await self._mic_pcm.put(body)
            return
        if kind is not FrameKind.JSON:
            return
        event = decode_json(body)
        if event.get("type") == "error":
            code = event.get("code")
            message = event.get("message")
            if isinstance(code, int) and isinstance(message, str):
                raise SidecarError(code, message)
        await self._events.put(event)
        if self._subscriber is not None:
            result = self._subscriber(event)
            if result is not None:
                await result


class FakeSidecar:
    """In-process sidecar fake with scripted events, PCM, and playback recording."""

    def __init__(
        self,
        script: Sequence[JsonObject | bytes] = (),
        *,
        bargein_after_pcm_chunks: int | None = None,
    ) -> None:
        self.commands: list[JsonObject] = []
        self.speaker_pcm: list[bytes] = []
        self.records: list[tuple[str, JsonObject | bytes]] = []
        self._events: asyncio.Queue[JsonObject] = asyncio.Queue()
        self._mic_pcm: asyncio.Queue[bytes] = asyncio.Queue()
        self._bargein_after_pcm_chunks = bargein_after_pcm_chunks
        for item in script:
            if isinstance(item, bytes):
                self._mic_pcm.put_nowait(item)
            else:
                self._events.put_nowait(item)

    def capture(self) -> Iterator[bytes]:
        """Synchronously drain scripted mic PCM."""
        while not self._mic_pcm.empty():
            yield self._mic_pcm.get_nowait()

    async def capture_async(self) -> AsyncIterator[bytes]:
        """Yield scripted mic PCM frames until the current queue is empty."""
        while not self._mic_pcm.empty():
            yield await self._mic_pcm.get()

    def play(self, audio: Iterator[bytes]) -> None:
        """Synchronously record speaker PCM."""
        for chunk in audio:
            self.speaker_pcm.append(chunk)
            self.records.append(("spk_pcm", chunk))

    async def play_async(self, audio: AsyncIterator[bytes], cancel: asyncio.Event) -> None:
        """Record speaker PCM and optionally inject a barge-in event."""
        await self.send_command(
            {
                "type": "play",
                "sampleRate": AUDIO_FORMAT["sampleRate"],
                "channels": AUDIO_FORMAT["channels"],
            }
        )
        async for chunk in audio:
            if cancel.is_set():
                return
            self.speaker_pcm.append(chunk)
            self.records.append(("spk_pcm", chunk))
            if (
                self._bargein_after_pcm_chunks is not None
                and len(self.speaker_pcm) >= self._bargein_after_pcm_chunks
            ):
                self._bargein_after_pcm_chunks = None
                await self.emit_event({"type": "bargein"})
            await asyncio.sleep(0)

    async def send_command(self, command: JsonObject) -> None:
        """Record a command."""
        self.commands.append(command)
        self.records.append(("command", dict(command)))

    async def next_event(self, timeout: float | None = None) -> JsonObject:
        """Return the next scripted or injected event."""
        if timeout is None:
            return await self._events.get()
        return await asyncio.wait_for(self._events.get(), timeout)

    async def emit_event(self, event: JsonObject) -> None:
        """Inject an event into the fake."""
        await self._events.put(event)

    async def emit_mic_pcm(self, pcm: bytes) -> None:
        """Inject a microphone PCM chunk into the fake."""
        await self._mic_pcm.put(pcm)

    @property
    def raw_records(self) -> list[tuple[str, Any]]:
        """Return recorded commands and speaker PCM chunks."""
        return list(self.records)
