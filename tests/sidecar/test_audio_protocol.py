from __future__ import annotations

import struct

from artemis.sidecar.audio.protocol import (
    Bargein,
    ErrorEvent,
    FrameKind,
    GetStatus,
    JsonMessage,
    Play,
    PlaybackFinished,
    PlaybackStarted,
    SpeechEnd,
    SpeechStart,
    StartListening,
    StatusEvent,
    StopListening,
    StopPlayback,
    WakeDetected,
    decode_frame,
    decode_json,
    encode_frame,
    encode_json,
    message_to_dict,
)


def test_frame_round_trips_pcm_blob() -> None:
    body = b"\x00\x01\x02"
    frame = encode_frame(FrameKind.MIC_PCM, body)
    assert frame[0] == 0x02
    assert struct.unpack(">I", frame[1:5])[0] == len(body)
    assert decode_frame(memoryview(frame)) == (FrameKind.MIC_PCM, body, len(frame))


def test_json_messages_round_trip() -> None:
    messages: list[JsonMessage] = [
        WakeDetected(),
        SpeechStart(),
        SpeechEnd(reason="endpoint"),
        SpeechEnd(reason="maxDuration"),
        Bargein(),
        PlaybackStarted(),
        PlaybackFinished(),
        ErrorEvent(code=7, message="boom"),
        StatusEvent(state="idle"),
        StartListening(),
        StopListening(),
        Play(sampleRate=16000, channels=1),
        StopPlayback(),
        GetStatus(),
    ]

    for message in messages:
        frame = encode_json(message)
        assert frame[0] == 0x01
        decoded = decode_frame(memoryview(frame))
        assert decoded is not None
        kind, body, consumed = decoded
        assert kind is FrameKind.JSON
        assert consumed == len(frame)
        assert decode_json(body) == message_to_dict(message)
