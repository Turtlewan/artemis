from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path

import pytest

from artemis.sidecar.audio.capture import FakeCapture
from artemis.sidecar.audio.ipc_server import Endpoint, IPCServer
from artemis.sidecar.audio.orchestrator import AudioOrchestrator
from artemis.sidecar.audio.playback import FakePlayback
from artemis.sidecar.audio.protocol import (
    CHANNELS,
    SAMPLE_RATE,
    FrameKind,
    GetStatus,
    Play,
    StartListening,
    decode_frame,
    decode_json,
    encode_frame,
    encode_json,
)
from artemis.sidecar.audio.state_machine import AudioState
from artemis.sidecar.audio.vad import FakeVAD, VADEvent
from artemis.sidecar.audio.wake import FakeWakeWord


async def _read_json(reader: asyncio.StreamReader) -> dict[str, object]:
    header = await reader.readexactly(5)
    kind = FrameKind(header[0])
    length = int.from_bytes(header[1:5], "big")
    body = await reader.readexactly(length)
    assert kind is FrameKind.JSON
    return decode_json(body)


async def _open_unix_connection(path: Path) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    af_unix = getattr(socket, "AF_UNIX", None)
    if af_unix is None:
        raise RuntimeError("AF_UNIX sockets are unavailable in this Python build")
    client_socket = socket.socket(af_unix, socket.SOCK_STREAM)
    client_socket.connect(str(path))
    client_socket.setblocking(False)
    return await asyncio.open_connection(sock=client_socket)


async def _open_ipc_connection(
    endpoint: Endpoint,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    if endpoint[0] == "unix":
        return await _open_unix_connection(endpoint[1])
    return await asyncio.open_connection(endpoint[1], endpoint[2])


async def test_e2e_fake_socket_flow(tmp_path: Path) -> None:
    capture = FakeCapture()
    wake = FakeWakeWord(trigger_after_n=1)
    vad = FakeVAD([VADEvent.NONE, VADEvent.SPEECH_START, VADEvent.SPEECH_END])
    playback = FakePlayback()
    holder: dict[str, AudioOrchestrator] = {}

    async def handle_command(command: dict[str, object]) -> None:
        await holder["orchestrator"].handle_command(command)

    async def handle_speaker_pcm(data: bytes) -> None:
        await holder["orchestrator"].handle_speaker_pcm(data)

    ipc = IPCServer(
        tmp_path,
        "dev",
        command_handler=handle_command,
        speaker_pcm_handler=handle_speaker_pcm,
    )
    orchestrator = AudioOrchestrator(
        capture=capture,
        wake=wake,
        vad=vad,
        playback=playback,
        ipc_server=ipc,
        max_speech_s=30,
    )
    holder["orchestrator"] = orchestrator
    await ipc.start()
    run_task = asyncio.create_task(orchestrator.run())
    endpoint = ipc.endpoint()
    reader, writer = await _open_ipc_connection(endpoint)
    try:
        if endpoint[0] == "unix":
            mode = ipc.socket_path.stat().st_mode & 0o777
            assert mode == 0o600
        else:
            assert ipc.port_path.read_text(encoding="ascii") == str(endpoint[2])

        writer.write(encode_json(GetStatus()))
        await writer.drain()
        assert await _read_json(reader) == {"state": "idle", "type": "status"}

        await capture.inject(b"\x00\x00")
        assert await _read_json(reader) == {"type": "wakeDetected"}

        writer.write(encode_json(StartListening()))
        await writer.drain()
        writer.write(encode_json(GetStatus()))
        await writer.drain()
        assert await _read_json(reader) == {"state": "capturing", "type": "status"}
        await capture.inject(b"\x00\x00")
        assert await _read_json(reader) == {"type": "speechStart"}
        await capture.inject(b"\x00\x00")
        assert await _read_json(reader) == {"reason": "endpoint", "type": "speechEnd"}

        writer.write(encode_json(Play(sampleRate=SAMPLE_RATE, channels=CHANNELS)))
        await writer.drain()
        assert await _read_json(reader) == {"type": "playbackStarted"}

        writer.write(encode_frame(FrameKind.SPK_PCM, b"\x01\x02"))
        writer.write(encode_frame(FrameKind.SPK_PCM, b""))
        await writer.drain()
        assert await _read_json(reader) == {"type": "playbackFinished"}
        assert playback.enqueued == [b"\x01\x02"]

        orchestrator.state_machine.state = AudioState.PLAYING
        vad.push(VADEvent.SPEECH_START)
        await capture.inject(b"\x00\x00")
        assert await _read_json(reader) == {"type": "bargein"}
        assert playback.flush_called
    finally:
        writer.close()
        await writer.wait_closed()
        orchestrator.stop()
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task
        await ipc.close()


@pytest.mark.skipif(
    os.environ.get("ARTEMIS_AUDIO_HW") != "1", reason="requires real audio hardware"
)
def test_real_audio_hardware_gated() -> None:
    assert os.environ["ARTEMIS_AUDIO_HW"] == "1"


def test_decode_frame_waits_for_complete_body() -> None:
    frame = encode_frame(FrameKind.MIC_PCM, b"1234")
    assert decode_frame(memoryview(frame[:-1])) is None
