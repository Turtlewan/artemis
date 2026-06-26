from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Literal, cast

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
AUDIO_FORMAT = {"sampleRate": SAMPLE_RATE, "channels": CHANNELS, "sampleWidth": SAMPLE_WIDTH}


class FrameKind(IntEnum):
    JSON = 0x01
    MIC_PCM = 0x02
    SPK_PCM = 0x03


type SpeechEndReason = Literal["endpoint", "maxDuration"]


@dataclass(frozen=True)
class WakeDetected:
    type: Literal["wakeDetected"] = field(default="wakeDetected", init=False)


@dataclass(frozen=True)
class SpeechStart:
    type: Literal["speechStart"] = field(default="speechStart", init=False)


@dataclass(frozen=True)
class SpeechEnd:
    reason: SpeechEndReason
    type: Literal["speechEnd"] = field(default="speechEnd", init=False)


@dataclass(frozen=True)
class Bargein:
    type: Literal["bargein"] = field(default="bargein", init=False)


@dataclass(frozen=True)
class PlaybackStarted:
    type: Literal["playbackStarted"] = field(default="playbackStarted", init=False)


@dataclass(frozen=True)
class PlaybackFinished:
    type: Literal["playbackFinished"] = field(default="playbackFinished", init=False)


@dataclass(frozen=True)
class ErrorEvent:
    code: int
    message: str
    type: Literal["error"] = field(default="error", init=False)


@dataclass(frozen=True)
class StatusEvent:
    state: str
    type: Literal["status"] = field(default="status", init=False)


@dataclass(frozen=True)
class StartListening:
    type: Literal["startListening"] = field(default="startListening", init=False)


@dataclass(frozen=True)
class StopListening:
    type: Literal["stopListening"] = field(default="stopListening", init=False)


@dataclass(frozen=True)
class Play:
    sampleRate: int  # noqa: N815
    channels: int
    type: Literal["play"] = field(default="play", init=False)


@dataclass(frozen=True)
class StopPlayback:
    type: Literal["stopPlayback"] = field(default="stopPlayback", init=False)


@dataclass(frozen=True)
class GetStatus:
    type: Literal["getStatus"] = field(default="getStatus", init=False)


type EventMessage = (
    WakeDetected
    | SpeechStart
    | SpeechEnd
    | Bargein
    | PlaybackStarted
    | PlaybackFinished
    | ErrorEvent
    | StatusEvent
)
type CommandMessage = StartListening | StopListening | Play | StopPlayback | GetStatus
type JsonMessage = EventMessage | CommandMessage
type JsonObject = dict[str, object]


def message_to_dict(message: JsonMessage) -> JsonObject:
    return asdict(message)


def encode_frame(kind: FrameKind, body: bytes) -> bytes:
    return bytes([kind]) + struct.pack(">I", len(body)) + body


def encode_json(msg: JsonObject | JsonMessage) -> bytes:
    payload = message_to_dict(msg) if not isinstance(msg, dict) else msg
    return encode_frame(FrameKind.JSON, json.dumps(payload, separators=(",", ":")).encode())


def decode_frame(buf: memoryview) -> tuple[FrameKind, bytes, int] | None:
    if len(buf) < 5:
        return None
    kind = FrameKind(buf[0])
    length = struct.unpack_from(">I", buf, 1)[0]
    if len(buf) < 5 + length:
        return None
    return kind, bytes(buf[5 : 5 + length]), 5 + length


def decode_json(body: bytes) -> JsonObject:
    loaded = json.loads(body.decode())
    if not isinstance(loaded, dict):
        raise ValueError("JSON frame body must be an object")
    return cast(JsonObject, loaded)


def command_from_dict(data: JsonObject) -> CommandMessage:
    message_type = data.get("type")
    if message_type == "startListening":
        return StartListening()
    if message_type == "stopListening":
        return StopListening()
    if message_type == "play":
        sample_rate = data.get("sampleRate")
        channels = data.get("channels")
        if not isinstance(sample_rate, int) or not isinstance(channels, int):
            raise ValueError("play command requires integer sampleRate and channels")
        return Play(sampleRate=sample_rate, channels=channels)
    if message_type == "stopPlayback":
        return StopPlayback()
    if message_type == "getStatus":
        return GetStatus()
    raise ValueError(f"unknown command type: {message_type!r}")
