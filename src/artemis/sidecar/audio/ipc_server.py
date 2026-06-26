from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from artemis.sidecar.audio.protocol import (
    FrameKind,
    JsonObject,
    StatusEvent,
    command_from_dict,
    decode_frame,
    decode_json,
    encode_frame,
    encode_json,
    message_to_dict,
)

# Windows dev sidecar omits peer-uid check: getpeereid is unavailable on Windows AF_UNIX,
# and no DEK crosses this socket. Add SO_PEERCRED/getpeereid when porting to production Unix.

CommandHandler = Callable[[JsonObject], Awaitable[None]]
SpeakerPcmHandler = Callable[[bytes], Awaitable[None]]
Endpoint = tuple[Literal["unix"], Path] | tuple[Literal["tcp"], str, int]


class IPCServer:
    def __init__(
        self,
        data_root: Path,
        slot: str,
        *,
        command_handler: CommandHandler | None = None,
        speaker_pcm_handler: SpeakerPcmHandler | None = None,
    ) -> None:
        self.socket_path = data_root / slot / "run" / "audio.sock"
        self.port_path = data_root / slot / "run" / "audio.port"
        self._command_handler = command_handler
        self._speaker_pcm_handler = speaker_pcm_handler
        self._server_socket: socket.socket | None = None
        self._endpoint: Endpoint | None = None
        self._accept_task: asyncio.Task[None] | None = None
        self._client_tasks: set[asyncio.Task[None]] = set()
        self._writer: asyncio.StreamWriter | None = None

    async def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        af_unix = getattr(socket, "AF_UNIX", None)
        if af_unix is not None:
            if self.port_path.exists():
                self.port_path.unlink()
            server_socket = socket.socket(af_unix, socket.SOCK_STREAM)
            server_socket.bind(str(self.socket_path))
            server_socket.listen()
            server_socket.setblocking(False)
            os.chmod(self.socket_path, 0o600)
            self._endpoint = ("unix", self.socket_path)
        else:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.bind(("127.0.0.1", 0))
            server_socket.listen()
            server_socket.setblocking(False)
            port = server_socket.getsockname()[1]
            tmp_path = self.port_path.with_name(f"{self.port_path.name}.tmp")
            tmp_path.write_text(str(port), encoding="ascii")
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, self.port_path)
            self._endpoint = ("tcp", "127.0.0.1", port)
        self._server_socket = server_socket
        self._accept_task = asyncio.create_task(self._accept_loop())

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
        if self._accept_task is not None:
            self._accept_task.cancel()
            try:
                await self._accept_task
            except asyncio.CancelledError:
                pass
            self._accept_task = None
        for task in list(self._client_tasks):
            task.cancel()
        if self._client_tasks:
            await asyncio.gather(*self._client_tasks, return_exceptions=True)
            self._client_tasks.clear()
        if self._server_socket is not None:
            self._server_socket.close()
            self._server_socket = None
        if self._endpoint is not None:
            if self._endpoint[0] == "unix" and self.socket_path.exists():
                self.socket_path.unlink()
            elif self._endpoint[0] == "tcp" and self.port_path.exists():
                self.port_path.unlink()
            self._endpoint = None

    def endpoint(self) -> Endpoint:
        if self._endpoint is None:
            raise RuntimeError("IPC server has not started")
        return self._endpoint

    async def serve_forever(self) -> None:
        if self._server_socket is None:
            await self.start()
        while True:
            await asyncio.sleep(3600)

    async def send_event(self, msg: JsonObject) -> None:
        await self._write(encode_json(msg))

    async def send_mic_pcm(self, data: bytes) -> None:
        await self._write(encode_frame(FrameKind.MIC_PCM, data))

    async def _write(self, frame: bytes) -> None:
        if self._writer is None:
            return
        self._writer.write(frame)
        await self._writer.drain()

    async def _accept_loop(self) -> None:
        if self._server_socket is None:
            raise RuntimeError("IPC server failed to start")
        loop = asyncio.get_running_loop()
        while True:
            client_socket, _ = await loop.sock_accept(self._server_socket)
            client_socket.setblocking(False)
            task = asyncio.create_task(self._handle_client_socket(client_socket))
            self._client_tasks.add(task)
            task.add_done_callback(self._client_tasks.discard)

    async def _handle_client_socket(self, client_socket: socket.socket) -> None:
        reader, writer = await asyncio.open_connection(sock=client_socket)
        await self._handle_client(reader, writer)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writer = writer
        buffer = bytearray()
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    decoded = decode_frame(memoryview(buffer))
                    if decoded is None:
                        break
                    kind, body, consumed = decoded
                    del buffer[:consumed]
                    await self._dispatch_frame(kind, body)
        finally:
            if self._writer is writer:
                self._writer = None
            writer.close()
            await writer.wait_closed()

    async def _dispatch_frame(self, kind: FrameKind, body: bytes) -> None:
        if kind is FrameKind.JSON:
            data = decode_json(body)
            command = command_from_dict(data)
            if self._command_handler is not None:
                await self._command_handler(message_to_dict(command))
            elif data.get("type") == "getStatus":
                await self.send_event(message_to_dict(StatusEvent(state="idle")))
        elif kind is FrameKind.SPK_PCM and self._speaker_pcm_handler is not None:
            await self._speaker_pcm_handler(body)
