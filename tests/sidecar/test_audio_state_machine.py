from __future__ import annotations

import asyncio

import pytest

from artemis.sidecar.audio.state_machine import AudioState, AudioStateMachine, InvalidTransition


def test_legal_transitions() -> None:
    sm = AudioStateMachine()
    assert sm.transition("wake") is AudioState.WAKE_DETECTED
    assert sm.transition("start_listening") is AudioState.CAPTURING
    assert sm.transition("speech_end", reason="endpoint") is AudioState.ENDPOINT
    assert sm.transition("awaiting") is AudioState.AWAITING_RESPONSE
    assert sm.transition("play") is AudioState.PLAYING
    assert sm.transition("barge_in") is AudioState.CAPTURING
    assert sm.transition("stop_listening") is AudioState.IDLE


def test_illegal_transition_raises() -> None:
    sm = AudioStateMachine()
    with pytest.raises(InvalidTransition):
        sm.transition("play")


async def test_max_duration_timer_fires_reason() -> None:
    sm = AudioStateMachine()
    reasons: list[str] = []
    sm.transition("wake")
    sm.transition("start_listening")
    sm.start_capture_timer(0.01, lambda reason: reasons.append(reason))

    await asyncio.sleep(0.05)

    assert sm.state is AudioState.ENDPOINT
    assert sm.last_speech_end_reason == "maxDuration"
    assert reasons == ["maxDuration"]
