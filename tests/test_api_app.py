from __future__ import annotations

import base64
import hmac
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from artemis.api_app import (
    AskRequest,
    CalendarRead,
    DefaultDomainReadSource,
    PairingCodeStore,
    RateLimiter,
    app_router,
    require_unlocked,
)
from artemis.app_layout_store import CardPlacement, LayoutDTO, LayoutStore
from artemis.brain import BrainResponse
from artemis.identity.app_auth import (
    API_SESSION_CONTEXT,
    AppAuth,
    ChallengeStore,
    DeviceRegistry,
    Principal,
    SessionStore,
)
from artemis.identity.broker_client import BrokerError
from artemis.ports.types import Scope
from artemis.recipes.review import RecipeReview


class FakeBroker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.paired: list[tuple[str, str]] = []

    def pair(self, device_id: str, public_key_b64: str) -> None:
        if self.fail:
            raise BrokerError("offline", "broker unavailable")
        self.paired.append((device_id, public_key_b64))


class FakeKeyProvider:
    def __init__(self) -> None:
        self.unlocked = False
        self.pending: dict[Scope, bytes] = {}

    def begin_unlock(self, scope: Scope) -> bytes:
        nonce = f"unlock:{scope}".encode()
        self.pending[scope] = nonce
        return nonce

    def complete_unlock(self, scope: Scope, nonce: bytes, proof: dict[str, object]) -> None:
        if not hmac.compare_digest(self.pending.get(scope, b""), nonce):
            raise BrokerError("stale-nonce", "stale or unknown unlock nonce")
        if proof.get("counter") != 10:
            raise BrokerError("bad-proof", "unlock failed")
        self.unlocked = True
        self.pending.pop(scope, None)

    def is_owner_unlocked(self) -> bool:
        return self.unlocked

    def lock_all(self) -> None:
        self.unlocked = False


class FakeReviewSurface:
    def __init__(self) -> None:
        self.approved: list[str] = []
        self.rejected: list[str] = []
        self._pending = RecipeReview(
            name="pay-bill",
            description="Pay the utility bill",
            status="pending",
            action_class="takes_action",
            safety="gated",
            explanation="Needs approval.",
        )

    def auto_enabled(self) -> list[RecipeReview]:
        return [
            RecipeReview(
                name="check-time",
                description="Check the time",
                status="enabled",
                action_class="no_data",
                safety="auto-enable",
                explanation="Safe.",
            )
        ]

    def pending_for_review(self) -> list[RecipeReview]:
        return [self._pending]

    async def approve(self, name: str) -> RecipeReview:
        self.approved.append(name)
        return RecipeReview(
            name=name,
            description="Pay the utility bill",
            status="enabled",
            action_class="takes_action",
            safety="gated",
            explanation="Approved.",
        )

    async def reject(self, name: str) -> RecipeReview:
        self.rejected.append(name)
        return RecipeReview(
            name=name,
            description="Pay the utility bill",
            status="retired",
            action_class="takes_action",
            safety="gated",
            explanation="Rejected.",
        )


@dataclass
class FakePendingAction:
    id: str
    summary: str
    status: str = "pending"
    module: str = "calendar"
    tool: str = "send_invite"
    args: dict[str, object] | None = None
    action_class: str = "takes-action"
    created_at: datetime = datetime(2026, 6, 27, 1, 0, tzinfo=UTC)
    expires_at: datetime = datetime(2026, 6, 27, 2, 0, tzinfo=UTC)
    result: dict[str, object] | None = None


class FakeActionStagingService:
    def __init__(self) -> None:
        self._pending: dict[str, FakePendingAction] = {
            "act-1": FakePendingAction(
                id="act-1",
                summary="Send invite to bob@example.com for 3pm Thu",
                args={"email": "bob@example.com"},
            ),
        }

    def list_pending(self) -> list[FakePendingAction]:
        return [action for action in self._pending.values() if action.status == "pending"]

    async def approve(self, id: str) -> FakePendingAction:
        action = self._pending[id]
        if action.status != "pending":
            raise ValueError("already settled")
        action.status = "approved"
        action.result = {"ok": True}
        return action

    def reject(self, id: str) -> FakePendingAction:
        action = self._pending[id]
        if action.status != "pending":
            raise ValueError("already settled")
        action.status = "rejected"
        return action


class FakeGateway:
    async def handle_text_scoped(self, request_text: str, scope: Scope) -> BrainResponse:
        return BrainResponse(text=f"{scope}:{request_text}", path="local", tool_used=None)

    async def handle_text_stream_scoped(
        self,
        request_text: str,
        scope: Scope,
    ) -> AsyncIterator[str]:
        yield f"{scope}:"
        yield request_text


class Phone:
    def __init__(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())

    @property
    def public_key_b64(self) -> str:
        public_bytes = self.private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        return base64.b64encode(public_bytes).decode("ascii")

    def sign_pairing(self, code: str, device_id: str) -> str:
        code_bytes = code.encode("utf-8")
        message = len(code_bytes).to_bytes(2, "big") + code_bytes + device_id.encode("utf-8")
        return _b64(self.private_key.sign(message, ec.ECDSA(hashes.SHA256())))

    def sign_session(self, nonce: bytes, counter: int) -> str:
        message = nonce + API_SESSION_CONTEXT + counter.to_bytes(8, "big")
        return _b64(self.private_key.sign(message, ec.ECDSA(hashes.SHA256())))


def test_pairing_verifies_before_consuming_and_rolls_back(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    phone = Phone()
    code = fixture.pairing_codes.mint()

    bad_sig = fixture.client.post(
        "/app/pair",
        json={
            "device_id": "phone",
            "public_key_b64": phone.public_key_b64,
            "pairing_code": code,
            "code_signature_b64": phone.sign_pairing("wrong", "phone"),
        },
    )
    assert bad_sig.status_code == 401
    assert fixture.pairing_codes.consume(code) is True

    code = fixture.pairing_codes.mint()
    assert fixture.pairing_codes.stored_hash is not None
    assert fixture.pairing_codes.stored_hash != code
    wrong_code = fixture.client.post(
        "/app/pair",
        json={
            "device_id": "phone",
            "public_key_b64": phone.public_key_b64,
            "pairing_code": "nope",
            "code_signature_b64": phone.sign_pairing("nope", "phone"),
        },
    )
    assert wrong_code.status_code == 401

    paired = _pair(fixture, phone, "phone")
    assert paired.status_code == 200
    assert fixture.registry.get("phone") is not None
    assert fixture.broker.paired == [("phone", phone.public_key_b64)]

    failing = _fixture(tmp_path / "failing", broker=FakeBroker(fail=True))
    failed = _pair(failing, Phone(), "phone")
    assert failed.status_code == 503
    assert failing.registry.get("phone") is None


def test_pairing_succeeds_without_broker_on_windows_host(tmp_path: Path) -> None:
    # ADR-033 Windows host has no Secure Enclave broker (app.state.broker_client is None);
    # pairing must still verify, consume the code, and register the device — not 500 on a
    # missing broker. Regression for the live CLIENT-auth Task 7 bring-up (2026-06-28).
    fixture = _fixture(tmp_path)
    fixture.app.state.broker_client = None
    phone = Phone()
    paired = _pair(fixture, phone, "phone")
    assert paired.status_code == 200
    assert fixture.registry.get("phone") is not None


def test_admin_pair_code_is_loopback_only(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    response = fixture.client.post("/app/admin/pair-code")
    assert response.status_code == 200
    assert isinstance(_json_obj(response)["code"], str)

    app = _app(tmp_path / "remote")
    remote = TestClient(app, client=("100.64.0.1", 1234))
    assert remote.post("/app/admin/pair-code").status_code == 403


def test_session_rate_limit_replay_guards_and_lock_logout_flow(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    phone = Phone()
    assert _pair(fixture, phone, "phone").status_code == 200

    token = _session_token(fixture, phone, "phone", 1)
    headers = _headers(token)
    replay = fixture.client.post(
        "/app/session/complete",
        json={
            "device_id": "phone",
            "nonce_b64": _b64(b"missing"),
            "counter": 2,
            "signature_b64": phone.sign_session(b"missing", 2),
        },
    )
    assert replay.status_code == 401

    assert fixture.client.get("/app/review/pending").status_code == 401
    assert fixture.client.post("/guarded", json={"text": "x"}).status_code == 401
    assert fixture.client.get("/app/review/pending", headers=headers).status_code == 423

    layout = fixture.client.get("/app/layout", headers=headers)
    assert layout.status_code == 200
    assert len(cast(list[object], _json_obj(layout)["cards"])) == 11

    unlock_begin = fixture.client.post("/app/unlock/begin", json={}, headers=headers)
    assert unlock_begin.status_code == 200
    unlock_nonce = cast(str, _json_obj(unlock_begin)["nonce_b64"])
    unlock_complete = fixture.client.post(
        "/app/unlock/complete",
        json={"nonce_b64": unlock_nonce, "counter": 10, "signature_b64": _b64(b"sig")},
        headers=headers,
    )
    assert unlock_complete.status_code == 200

    pending = fixture.client.get("/app/review/pending", headers=headers)
    assert pending.status_code == 200
    assert cast(list[object], pending.json())[0] == {
        "name": "pay-bill",
        "description": "Pay the utility bill",
        "status": "pending",
        "action_class": "takes_action",
        "safety": "gated",
        "explanation": "Needs approval.",
    }

    assert fixture.client.get("/app/review/auto-enabled", headers=headers).status_code == 200
    approve = fixture.client.post(
        "/app/review/approve",
        json={"name": "pay-bill"},
        headers=headers,
    )
    reject = fixture.client.post(
        "/app/review/reject",
        json={"name": "pay-bill"},
        headers=headers,
    )
    assert approve.status_code == 200
    assert reject.status_code == 200
    assert fixture.review.approved == ["pay-bill"]
    assert fixture.review.rejected == ["pay-bill"]

    ask = fixture.client.post("/app/ask", json={"text": "hello"}, headers=headers)
    assert ask.status_code == 200
    assert _json_obj(ask)["text"] == "owner-private:hello"
    with fixture.client.stream(
        "POST", "/app/ask/stream", json={"text": "hello"}, headers=headers
    ) as stream:
        body = stream.read().decode("utf-8")
    assert stream.status_code == 200
    assert "data: owner-private:" in body
    assert "data: hello" in body
    assert "data: [DONE]" in body

    status = fixture.client.get("/app/status", headers=headers)
    assert status.status_code == 200
    assert _json_obj(status)["vault_unlocked"] is True
    assert fixture.client.post("/app/lock", headers=headers).status_code == 200
    locked_status = fixture.client.get("/app/status", headers=headers)
    assert locked_status.status_code == 200
    assert _json_obj(locked_status)["vault_unlocked"] is False

    assert fixture.client.post("/app/logout", headers=headers).status_code == 200
    assert fixture.client.get("/app/status", headers=headers).status_code == 401
    assert fixture.client.get("/healthz").status_code == 200


def test_rate_limit_blocks_sixth_begin_attempt(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    statuses = [
        fixture.client.post("/app/session/begin", json={"device_id": "unknown"}).status_code
        for _ in range(6)
    ]
    assert statuses == [401, 401, 401, 401, 401, 429]


def test_layout_lww_round_trip_while_locked(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    phone = Phone()
    assert _pair(fixture, phone, "phone").status_code == 200
    token = _session_token(fixture, phone, "phone", 1)
    headers = _headers(token)

    old_layout = _layout(datetime.now(UTC) - timedelta(days=1), x=9)
    assert (
        fixture.client.put(
            "/app/layout", json=old_layout.model_dump(mode="json"), headers=headers
        ).status_code
        == 200
    )
    newer = _layout(datetime.now(UTC) + timedelta(days=1), x=3)
    accepted = fixture.client.put(
        "/app/layout",
        json=newer.model_dump(mode="json"),
        headers=headers,
    )
    assert accepted.status_code == 200
    assert cast(dict[str, object], cast(list[object], _json_obj(accepted)["cards"])[0])["x"] == 3
    older = _layout(datetime.now(UTC) - timedelta(days=2), x=1)
    ignored = fixture.client.put(
        "/app/layout",
        json=older.model_dump(mode="json"),
        headers=headers,
    )
    assert ignored.status_code == 200
    assert cast(dict[str, object], cast(list[object], _json_obj(ignored)["cards"])[0])["x"] == 3
    assert fixture.client.get("/app/layout", headers=headers).status_code == 200


def test_domain_reads_are_unlock_gated_and_typed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    phone = Phone()
    assert _pair(fixture, phone, "phone").status_code == 200
    token = _session_token(fixture, phone, "phone", 1)
    headers = _headers(token)

    for route in ["/app/calendar", "/app/tasks", "/app/projects", "/app/email", "/app/finance"]:
        assert fixture.client.get(route, headers=headers).status_code == 423

    fixture.key_provider.unlocked = True
    calendar = fixture.client.get("/app/calendar", headers=headers)
    tasks = fixture.client.get("/app/tasks", headers=headers)
    projects = fixture.client.get("/app/projects", headers=headers)
    email = fixture.client.get("/app/email", headers=headers)
    finance = fixture.client.get("/app/finance", headers=headers)

    assert calendar.status_code == 200
    assert CalendarRead.model_validate(calendar.json()).tasks_due_by_day == {"2026-06-24": 2}
    assert tasks.status_code == 200
    assert "today" in _json_obj(tasks)
    assert projects.status_code == 200
    assert "projects" in _json_obj(projects)
    assert email.status_code == 200
    assert "needs_you" in _json_obj(email)
    assert finance.status_code == 200
    assert "week_total" in _json_obj(finance)


def test_action_routes_require_bearer(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.app.state.action_staging = FakeActionStagingService()

    pending = fixture.client.get("/app/actions/pending")
    approve = fixture.client.post("/app/actions/approve", json={"id": "act-1"})
    reject = fixture.client.post("/app/actions/reject", json={"id": "act-1"})

    assert pending.status_code == 401
    assert approve.status_code == 401
    assert reject.status_code == 401


def test_pending_actions_require_unlocked_vault(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.app.state.action_staging = FakeActionStagingService()
    headers = _paired_session_headers(fixture, Phone())

    response = fixture.client.get("/app/actions/pending", headers=headers)

    assert response.status_code == 423


def test_pending_actions_return_display_fields_without_args(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.app.state.action_staging = FakeActionStagingService()
    headers = _unlocked_session_headers(fixture, Phone())

    response = fixture.client.get("/app/actions/pending", headers=headers)

    assert response.status_code == 200
    actions = cast(list[dict[str, object]], response.json())
    assert actions[0]["id"] == "act-1"
    assert actions[0]["summary"] == "Send invite to bob@example.com for 3pm Thu"
    assert "args" not in actions[0]


def test_approve_action_existing_nonexistent_and_already_settled(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.app.state.action_staging = FakeActionStagingService()
    headers = _unlocked_session_headers(fixture, Phone())

    approved = fixture.client.post("/app/actions/approve", json={"id": "act-1"}, headers=headers)
    missing = fixture.client.post(
        "/app/actions/approve",
        json={"id": "nonexistent"},
        headers=headers,
    )
    settled = fixture.client.post("/app/actions/approve", json={"id": "act-1"}, headers=headers)

    assert approved.status_code == 200
    assert _json_obj(approved)["status"] == "approved"
    assert missing.status_code == 404
    assert settled.status_code == 409


def test_reject_action_existing_and_nonexistent(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.app.state.action_staging = FakeActionStagingService()
    headers = _unlocked_session_headers(fixture, Phone())

    rejected = fixture.client.post("/app/actions/reject", json={"id": "act-1"}, headers=headers)
    missing = fixture.client.post(
        "/app/actions/reject",
        json={"id": "nonexistent"},
        headers=headers,
    )

    assert rejected.status_code == 200
    assert _json_obj(rejected)["status"] == "rejected"
    assert missing.status_code == 404


def test_existing_review_pending_and_healthz_still_pass(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.app.state.action_staging = FakeActionStagingService()
    headers = _unlocked_session_headers(fixture, Phone())

    assert fixture.client.get("/app/review/pending", headers=headers).status_code == 200
    assert fixture.client.get("/healthz").status_code == 200


def _pair(fixture: Fixture, phone: Phone, device_id: str) -> _JsonResponse:
    code = fixture.pairing_codes.mint()
    return cast(
        _JsonResponse,
        fixture.client.post(
            "/app/pair",
            json={
                "device_id": device_id,
                "public_key_b64": phone.public_key_b64,
                "pairing_code": code,
                "code_signature_b64": phone.sign_pairing(code, device_id),
            },
        ),
    )


def _session_token(fixture: Fixture, phone: Phone, device_id: str, counter: int) -> str:
    begin = fixture.client.post("/app/session/begin", json={"device_id": device_id})
    assert begin.status_code == 200
    nonce = base64.b64decode(cast(str, _json_obj(begin)["nonce_b64"]))
    complete = fixture.client.post(
        "/app/session/complete",
        json={
            "device_id": device_id,
            "nonce_b64": _b64(nonce),
            "counter": counter,
            "signature_b64": phone.sign_session(nonce, counter),
        },
    )
    assert complete.status_code == 200
    return cast(str, _json_obj(complete)["session_token"])


def _paired_session_headers(fixture: Fixture, phone: Phone) -> dict[str, str]:
    assert _pair(fixture, phone, "phone").status_code == 200
    return _headers(_session_token(fixture, phone, "phone", 1))


def _unlocked_session_headers(fixture: Fixture, phone: Phone) -> dict[str, str]:
    headers = _paired_session_headers(fixture, phone)
    fixture.key_provider.unlocked = True
    return headers


def _layout(updated_at: datetime, x: int) -> LayoutDTO:
    return LayoutDTO(
        version=1,
        updated_at=updated_at,
        cards=[
            CardPlacement(id="calendar", domain="calendar", cluster="today", x=x, y=0, w=1, h=1)
        ],
    )


@dataclass
class Fixture:
    app: FastAPI
    client: TestClient
    registry: DeviceRegistry
    broker: FakeBroker
    key_provider: FakeKeyProvider
    pairing_codes: PairingCodeStore
    review: FakeReviewSurface


def _fixture(tmp_path: Path, *, broker: FakeBroker | None = None) -> Fixture:
    app = _app(tmp_path, broker=broker)
    return cast(Fixture, app.state.fixture)


def _app(tmp_path: Path, *, broker: FakeBroker | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(app_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/guarded")
    async def guarded(
        _body: AskRequest, _principal: Principal = Depends(require_unlocked)
    ) -> dict[str, bool]:
        return {"ok": True}

    registry = DeviceRegistry(tmp_path / "identity" / "devices.json")
    key_provider = FakeKeyProvider()
    pairing_codes = PairingCodeStore()
    fake_broker = broker or FakeBroker()
    review = FakeReviewSurface()
    app.state.app_auth = AppAuth(registry, ChallengeStore(), SessionStore())
    app.state.broker_client = fake_broker
    app.state.key_provider = key_provider
    app.state.review_surface = review
    app.state.gateway = FakeGateway()
    app.state.pairing_codes = pairing_codes
    app.state.rate_limiter = RateLimiter()
    app.state.layout_store = LayoutStore(tmp_path / "identity" / "layout.json")
    app.state.domain_read_source = DefaultDomainReadSource()
    client = TestClient(app, client=("127.0.0.1", 5000))
    app.state.fixture = Fixture(
        app, client, registry, fake_broker, key_provider, pairing_codes, review
    )
    return app


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


def _json_obj(response: _JsonResponse) -> dict[str, object]:
    data = response.json()
    return cast(dict[str, object], data)


def test_ask_stream_fails_closed_if_vault_locks_before_first_chunk(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    phone = Phone()
    assert _pair(fixture, phone, "phone").status_code == 200
    token = _session_token(fixture, phone, "phone", 1)
    headers = _headers(token)

    # Unlocked for the require_unlocked gate, then locked before the first chunk.
    calls = {"n": 0}

    def flipping() -> bool:
        calls["n"] += 1
        return calls["n"] == 1

    fixture.key_provider.is_owner_unlocked = flipping  # type: ignore[method-assign]

    with fixture.client.stream(
        "POST", "/app/ask/stream", json={"text": "secret"}, headers=headers
    ) as stream:
        body = stream.read().decode("utf-8")

    assert stream.status_code == 200
    assert "vault_locked" in body
    assert "secret" not in body  # no owner content emitted before the lock re-check
    assert "[DONE]" not in body
