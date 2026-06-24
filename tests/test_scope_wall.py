from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from artemis import paths
from artemis.brain import Brain, BrainResponse
from artemis.config import Settings
from artemis.data.scoped_store import (
    CrossScopeError,
    ScopedStore,
    assert_same_scope,
    provision_scope,
)
from artemis.gateway import Gateway
from artemis.identity.key_provider import FakeKeyProvider, ScopeLockedError, SecretKey
from artemis.identity.scope import (
    GENERAL,
    OWNER_PERSON_ID,
    OWNER_PRIVATE,
    Identity,
    guest_scope,
    scopes_for,
)
from artemis.ports.types import PersonId, Scope


class RecordingKeyProvider(FakeKeyProvider):
    def __init__(self, provisioned: set[Scope]) -> None:
        super().__init__(owner_unlocked=True)
        self._provisioned = provisioned

    def dek_for_scope(self, scope: Scope) -> SecretKey:
        if scope not in self._provisioned:
            raise ScopeLockedError(f"Scope is locked: {scope}")
        return SecretKey(_key_for(scope))


class FakeBrain:
    def __init__(self, expected_scope: Scope | None = None) -> None:
        self.expected_scope = expected_scope
        self.seen_scope: Scope | None = None

    async def respond(self, request_text: str, scope: Scope) -> BrainResponse:
        self.seen_scope = scope
        if self.expected_scope is not None:
            assert scope == self.expected_scope
        return BrainResponse(
            text=f"ok:{request_text}", path="local", tool_used=None, escalated=False
        )

    async def pre_route(self, request_text: str, scope: Scope) -> str | None:
        self.seen_scope = scope
        return f"route:{request_text}"


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path)


def _key_for(scope: Scope) -> bytes:
    seed = scope.encode("utf-8")
    repeated = seed * ((32 // len(seed)) + 1)
    return repeated[:32]


def test_scope_model_owner_and_guest_wall() -> None:
    owner = Identity(OWNER_PERSON_ID, "owner")
    guest = Identity(PersonId("bob"), "guest")

    assert scopes_for(owner) == (OWNER_PRIVATE, GENERAL)
    assert scopes_for(guest) == ("guest-bob",)
    assert not set(scopes_for(guest)).intersection(scopes_for(owner))
    assert guest_scope(PersonId("bob")) == "guest-bob"


def test_secret_key_redacts_and_renders_hex() -> None:
    key = SecretKey(bytes.fromhex("deadbeef" * 8))

    assert "deadbeef" not in repr(key)
    assert str(key) == "SecretKey(<redacted>)"
    assert len(key.as_hex()) == 64


def test_provisioning_isolation_and_vector_handles(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provisioned: set[Scope] = set()
    key_provider = RecordingKeyProvider(provisioned)
    calls: list[Scope] = []

    def broker_provision(scope: Scope) -> None:
        calls.append(scope)
        provisioned.add(scope)

    provision_scope(OWNER_PRIVATE, settings, key_provider, broker_provision)
    provision_scope("guest-bob", settings, key_provider, broker_provision)

    owner_store = ScopedStore(OWNER_PRIVATE, settings, key_provider)
    guest_store = ScopedStore("guest-bob", settings, key_provider)
    owner_db_path = owner_store.db_path()
    guest_db_path = guest_store.db_path()

    assert calls == [OWNER_PRIVATE, "guest-bob"]
    assert owner_db_path.is_relative_to(paths.scope_dir(settings, OWNER_PRIVATE))
    assert guest_db_path.is_relative_to(paths.scope_dir(settings, "guest-bob"))
    assert not owner_db_path.is_relative_to(paths.vault_dir(settings, OWNER_PRIVATE))
    # ADR-007 (M3-a Task 1): the LanceDB doc-corpus vault is owner-only — a guest
    # scope has no vault_dir at all (raises), and its vectors live in sqlite-vec.
    with pytest.raises(ValueError):
        paths.vault_dir(settings, "guest-bob")
    assert owner_db_path != guest_db_path

    owner_vector = owner_store.vector_index_handle()
    guest_vector = guest_store.vector_index_handle()
    assert owner_vector != guest_vector
    assert owner_vector.kind == "lancedb"
    assert owner_vector.path == paths.vault_dir(settings, OWNER_PRIVATE)
    assert guest_vector.kind == "sqlite-vec"
    assert guest_vector.path == guest_db_path


def test_wall_enforcement_and_locked_scope(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    key_provider = FakeKeyProvider({OWNER_PRIVATE: _key_for(OWNER_PRIVATE)}, owner_unlocked=True)
    store = ScopedStore(OWNER_PRIVATE, settings, key_provider)
    handle = store.open_connection()

    with pytest.raises(CrossScopeError):
        assert_same_scope(handle.scope, "guest-bob")

    locked_store = ScopedStore("guest-bob", settings, key_provider)
    with pytest.raises(ScopeLockedError):
        key_provider.dek_for_scope("guest-bob")
    with pytest.raises(ScopeLockedError):
        locked_store.open_connection()


@pytest.mark.asyncio
async def test_gateway_locked_response() -> None:
    gateway = Gateway(
        cast(Brain, FakeBrain()),
        FakeKeyProvider({OWNER_PRIVATE: _key_for(OWNER_PRIVATE)}, owner_unlocked=False),
    )

    result = await gateway.handle_text("hi")

    assert result.text == "LOCKED"
    assert result.path == "locked"


@pytest.mark.asyncio
async def test_gateway_owner_scope_attached() -> None:
    fake_brain = FakeBrain(expected_scope=OWNER_PRIVATE)
    gateway = Gateway(
        cast(Brain, fake_brain),
        FakeKeyProvider({OWNER_PRIVATE: _key_for(OWNER_PRIVATE)}, owner_unlocked=True),
    )

    result = await gateway.handle_text("hi")

    assert result.text == "ok:hi"
    assert fake_brain.seen_scope == OWNER_PRIVATE
