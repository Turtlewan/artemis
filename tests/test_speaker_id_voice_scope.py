from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from artemis.brain import Brain, BrainResponse
from artemis.config import Settings
from artemis.gateway import GUEST_PERSON_ID, Gateway
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import GENERAL, OWNER_PERSON_ID, OWNER_PRIVATE, Identity, scopes_for
from artemis.identity.tier import tier_for
from artemis.manifest import DataScope, ModuleManifest
from artemis.ports.types import PersonId, Scope, Vector
from artemis.ports.voice import SpeakerID
from artemis.voice.speaker_id import EcapaSpeakerID, FakeSpeakerID, VoiceprintStore, enrol_owner


class _FakeRegistry:
    def __init__(self, data_scope: DataScope) -> None:
        self._manifests = {
            "fake": ModuleManifest(
                name="fake",
                version="0.1.0",
                description="fake module",
                data_scope=data_scope,
            )
        }

    def manifests(self) -> dict[str, ModuleManifest]:
        return dict(self._manifests)


class _FakeBrain:
    def __init__(
        self, data_scope: DataScope, *, pre_route_result: str | None = "fake.tool"
    ) -> None:
        self._registry = _FakeRegistry(data_scope)
        self._pre_route_result = pre_route_result
        self.pre_route_calls: list[tuple[str, Scope]] = []
        self.respond_calls: list[tuple[str, Scope]] = []

    async def pre_route(self, request_text: str, scope: Scope) -> str | None:
        self.pre_route_calls.append((request_text, scope))
        return self._pre_route_result

    async def respond(
        self,
        request_text: str,
        scope: Scope,
        released_ref_ids: frozenset[str] = frozenset(),
    ) -> BrainResponse:
        self.respond_calls.append((request_text, scope))
        return BrainResponse(text=f"served:{scope}", path="local")


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path)


def _key_provider(*, owner_unlocked: bool) -> FakeKeyProvider:
    return FakeKeyProvider({GENERAL: b"g" * 32}, owner_unlocked=owner_unlocked)


def test_speaker_id_conformance_and_fake_script(tmp_path: Path) -> None:
    store = VoiceprintStore(_settings(tmp_path), _key_provider(owner_unlocked=False))
    speaker: SpeakerID = EcapaSpeakerID(store)
    assert isinstance(speaker, EcapaSpeakerID)

    guest = PersonId("alice")
    fake = FakeSpeakerID({b"owner": OWNER_PERSON_ID, b"guest": guest, b"unknown": None})
    assert fake.identify(b"owner") == OWNER_PERSON_ID
    assert fake.identify(b"guest") == guest
    assert fake.identify(b"unknown") is None


def test_tier_for_data_scope_cases() -> None:
    assert tier_for(DataScope.OWNER_PRIVATE) == "tier1"
    assert tier_for(DataScope.SHARED) == "tier0"
    assert tier_for(None) == "tier0"


def test_voiceprint_store_round_trip_encrypted(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = VoiceprintStore(settings, _key_provider(owner_unlocked=False))
    embedding: Vector = (0.125, -0.5, 0.75)

    store.enrol(OWNER_PERSON_ID, embedding)

    assert store.has_any()
    assert store.all_voiceprints() == {OWNER_PERSON_ID: embedding}
    stored = next((tmp_path / "dev" / OWNER_PRIVATE / "voiceprints").glob("*.vp")).read_bytes()
    assert b"0.125" not in stored
    assert b"owner" not in stored


@pytest.mark.asyncio
async def test_voice_owner_tier1_locked_needs_phone_unlock() -> None:
    brain = _FakeBrain(DataScope.OWNER_PRIVATE)
    gateway = Gateway(
        cast(Brain, brain),
        key_provider=_key_provider(owner_unlocked=False),
        speaker_id=FakeSpeakerID({b"voice": OWNER_PERSON_ID}),
    )

    response = await gateway.handle_voice(b"voice", "show my journal")

    assert response.text == "NEEDS_PHONE_UNLOCK"
    assert response.path == "needs-unlock"
    assert brain.pre_route_calls == [("show my journal", OWNER_PRIVATE)]
    assert brain.respond_calls == []


@pytest.mark.asyncio
async def test_voice_owner_tier0_locked_proceeds_with_owner_scope() -> None:
    brain = _FakeBrain(DataScope.SHARED)
    gateway = Gateway(
        cast(Brain, brain),
        key_provider=_key_provider(owner_unlocked=False),
        speaker_id=FakeSpeakerID({b"voice": OWNER_PERSON_ID}),
    )

    response = await gateway.handle_voice(b"voice", "what time is it")

    assert response.text == f"served:{OWNER_PRIVATE}"
    assert brain.respond_calls == [("what time is it", OWNER_PRIVATE)]


@pytest.mark.asyncio
async def test_voice_owner_tier1_unlocked_proceeds() -> None:
    brain = _FakeBrain(DataScope.OWNER_PRIVATE)
    gateway = Gateway(
        cast(Brain, brain),
        key_provider=_key_provider(owner_unlocked=True),
        speaker_id=FakeSpeakerID({b"voice": OWNER_PERSON_ID}),
    )

    response = await gateway.handle_voice(b"voice", "show my journal")

    assert response.text == f"served:{OWNER_PRIVATE}"
    assert brain.respond_calls == [("show my journal", OWNER_PRIVATE)]


@pytest.mark.asyncio
async def test_voice_unknown_routes_to_guest_scope_without_owner_scope() -> None:
    brain = _FakeBrain(DataScope.OWNER_PRIVATE)
    gateway = Gateway(
        cast(Brain, brain),
        key_provider=_key_provider(owner_unlocked=False),
        speaker_id=FakeSpeakerID({b"voice": None}),
    )

    response = await gateway.handle_voice(b"voice", "hello")

    guest_identity = Identity(GUEST_PERSON_ID, "guest")
    guest_scope = f"guest-{GUEST_PERSON_ID}"
    assert response.text == f"served:{guest_scope}"
    assert brain.respond_calls == [("hello", guest_scope)]
    assert OWNER_PRIVATE not in scopes_for(guest_identity)


@pytest.mark.asyncio
async def test_handle_text_semantics_are_unchanged() -> None:
    unlocked_brain = _FakeBrain(DataScope.SHARED)
    unlocked_gateway = Gateway(
        cast(Brain, unlocked_brain),
        key_provider=_key_provider(owner_unlocked=True),
        speaker_id=FakeSpeakerID(),
    )
    unlocked_response = await unlocked_gateway.handle_text("hello")

    assert unlocked_response.text == f"served:{OWNER_PRIVATE}"
    assert unlocked_brain.respond_calls == [("hello", OWNER_PRIVATE)]

    locked_brain = _FakeBrain(DataScope.SHARED)
    locked_gateway = Gateway(
        cast(Brain, locked_brain),
        key_provider=_key_provider(owner_unlocked=False),
        speaker_id=FakeSpeakerID(),
    )
    locked_response = await locked_gateway.handle_text("hello")

    assert locked_response.text == "LOCKED"
    assert locked_response.path == "locked"
    assert locked_brain.respond_calls == []


def test_enrol_owner_records_owner_clips() -> None:
    speaker = FakeSpeakerID()

    enrol_owner([b"one", b"two"], speaker)

    assert speaker.enrolments == [(OWNER_PERSON_ID, b"one"), (OWNER_PERSON_ID, b"two")]
