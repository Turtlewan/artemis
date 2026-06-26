from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from artemis.sidecar.audio.aec import AECProcessor, NullAEC
from artemis.sidecar.audio.capture import AudioCapture, FakeCapture
from artemis.sidecar.audio.ipc_server import IPCServer
from artemis.sidecar.audio.orchestrator import AudioOrchestrator
from artemis.sidecar.audio.playback import AudioPlayback, FakePlayback
from artemis.sidecar.audio.vad import FakeVAD, SileroVAD, VADEvent
from artemis.sidecar.audio.wake import FakeWakeWord, OpenWakeWordDetector


async def serve() -> None:
    data_root = Path(os.environ.get("ARTEMIS_DATA_ROOT", ".artemis"))
    slot = os.environ.get("ARTEMIS_SLOT", "dev")
    audio_hw = os.environ.get("ARTEMIS_AUDIO_HW") == "1"
    headphones = os.environ.get("ARTEMIS_HEADPHONES") == "1"
    max_speech_s = float(os.environ.get("ARTEMIS_MAX_SPEECH_S", "30"))

    capture = AudioCapture() if audio_hw else FakeCapture([b"\x00\x00"] * 3)
    wake = OpenWakeWordDetector() if audio_hw else FakeWakeWord(trigger_after_n=1)
    vad = SileroVAD() if audio_hw else FakeVAD([VADEvent.SPEECH_START, VADEvent.SPEECH_END])
    playback = AudioPlayback() if audio_hw else FakePlayback()
    aec = NullAEC() if headphones or not audio_hw else AECProcessor()

    orchestrator_holder: dict[str, AudioOrchestrator] = {}

    async def handle_command(command: dict[str, object]) -> None:
        await orchestrator_holder["orchestrator"].handle_command(command)

    async def handle_speaker_pcm(data: bytes) -> None:
        await orchestrator_holder["orchestrator"].handle_speaker_pcm(data)

    ipc_server = IPCServer(
        data_root,
        slot,
        command_handler=handle_command,
        speaker_pcm_handler=handle_speaker_pcm,
    )
    orchestrator = AudioOrchestrator(
        capture=capture,
        wake=wake,
        vad=vad,
        playback=playback,
        ipc_server=ipc_server,
        aec=aec,
        max_speech_s=max_speech_s,
    )
    orchestrator_holder["orchestrator"] = orchestrator

    await ipc_server.start()
    await asyncio.gather(ipc_server.serve_forever(), orchestrator.run())


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m artemis.sidecar.audio")
    parser.add_argument("command", choices=["serve"])
    args = parser.parse_args()
    if args.command == "serve":
        asyncio.run(serve())


if __name__ == "__main__":
    main()
