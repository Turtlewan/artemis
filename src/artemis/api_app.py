"""Authenticated `/app/*` HTTP surface for the Artemis client."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from artemis.app_layout_store import LayoutDTO, LayoutStore, default_layout
from artemis.brain import BrainResponse
from artemis.identity.app_auth import (
    AppAuth,
    AuthError,
    DeviceRegistry,
    Principal,
    require_session,
    resolve_scope,
)
from artemis.identity.broker_client import BrokerError
from artemis.identity.key_provider import ScopeLockedError
from artemis.identity.scope import Identity
from artemis.ports.types import Scope
from artemis.recipes.promotion import RecipeAlreadyRetiredError
from artemis.recipes.review import RecipeReview
from artemis.recipes.signing import RecipeSignatureError
from artemis.speakable import DisplaySeg, SpeakSeg

if TYPE_CHECKING:
    from artemis.staging import PendingAction

PAIRING_CODE_TTL_SECONDS = 600
RATE_LIMIT_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 900.0

app_router = APIRouter(prefix="/app")


class PairRelay(Protocol):
    """Broker pairing relay surface used by the bootstrap route."""

    def pair(self, device_id: str, public_key_b64: str) -> None:
        """Store a paired device key in the broker."""
        ...


class UnlockProvider(Protocol):
    """Vault unlock surface required by the app routes."""

    def begin_unlock(self, scope: Scope) -> bytes:
        """Return a broker nonce for ``scope``."""
        ...

    def complete_unlock(self, scope: Scope, nonce: bytes, proof: dict[str, object]) -> None:
        """Complete an unlock relay."""
        ...

    def is_owner_unlocked(self) -> bool:
        """Return whether owner data endpoints may be served."""
        ...

    def lock_all(self) -> None:
        """Zeroize any cached owner data keys."""
        ...


class ReviewSurfaceProtocol(Protocol):
    """Review surface shape used by the app router."""

    def auto_enabled(self) -> list[RecipeReview]:
        """Return auto-enabled recipes."""
        ...

    def pending_for_review(self) -> list[RecipeReview]:
        """Return recipes awaiting owner review."""
        ...

    async def approve(self, name: str) -> RecipeReview:
        """Approve a recipe."""
        ...

    async def reject(self, name: str) -> RecipeReview:
        """Reject a recipe."""
        ...


class GatewayProtocol(Protocol):
    """Scoped gateway methods used by app chat routes."""

    async def handle_text_scoped(self, request_text: str, scope: Scope) -> BrainResponse:
        """Return one completed answer for a scoped request."""
        ...

    def handle_text_stream_scoped(self, request_text: str, scope: Scope) -> AsyncIterator[str]:
        """Stream answer chunks for a scoped request."""
        ...

    async def handle_ask_unified(
        self,
        query: str,
        *,
        scope_or_identity: Scope | Identity,
        speak: bool,
    ) -> tuple[AsyncIterator[DisplaySeg], AsyncIterator[SpeakSeg]]:
        """Return display and speak branches for one scoped request."""
        ...


class PairingCodeStore:
    """Single-slot hashed pairing-code store.

    The app runs as one uvicorn worker in this deployment, so the in-memory
    single outstanding code does not need cross-thread locking.
    """

    def __init__(self, ttl_seconds: int = PAIRING_CODE_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._code_hash: str | None = None
        self._expires_at = 0.0

    @property
    def stored_hash(self) -> str | None:
        """Return the stored SHA-256 hex digest for tests and diagnostics."""
        return self._code_hash

    def mint(self) -> str:
        """Mint one short-lived code, invalidating any previous code."""
        code = secrets.token_urlsafe(9)
        self._code_hash = _sha256_hex(code)
        self._expires_at = time.time() + self._ttl_seconds
        return code

    def consume(self, code: str) -> bool:
        """Consume the code exactly once when it matches and is unexpired."""
        code_hash = self._code_hash
        if code_hash is None or self._expires_at <= time.time():
            self._clear()
            return False
        if not hmac.compare_digest(_sha256_hex(code), code_hash):
            return False
        self._clear()
        return True

    def _clear(self) -> None:
        self._code_hash = None
        self._expires_at = 0.0


class RateLimiter:
    """In-memory sliding-window limiter keyed by client peer IP."""

    def __init__(
        self,
        attempts: int = RATE_LIMIT_ATTEMPTS,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self._attempts = attempts
        self._window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str) -> bool:
        """Return True when ``key`` is still inside its allowed attempt budget."""
        now = time.monotonic()
        live = [hit for hit in self._hits.get(key, []) if now - hit < self._window_seconds]
        if len(live) >= self._attempts:
            self._hits[key] = live
            return False
        live.append(now)
        self._hits[key] = live
        return True


class PairRequest(BaseModel):
    """Unauthenticated pairing bootstrap request."""

    device_id: str
    public_key_b64: str
    pairing_code: str
    code_signature_b64: str


class SessionBeginRequest(BaseModel):
    """Begin an API-session challenge for a known device."""

    device_id: str


class SessionBeginResponse(BaseModel):
    """Base64 session nonce response."""

    nonce_b64: str


class SessionCompleteRequest(BaseModel):
    """Complete API-session challenge response."""

    device_id: str
    nonce_b64: str
    counter: int
    signature_b64: str


class SessionCompleteResponse(BaseModel):
    """Opaque bearer token returned after API-session authentication."""

    session_token: str
    expires_at: float


class UnlockBeginRequest(BaseModel):
    """Unlock-begin body; scope is intentionally session-derived."""


class UnlockBeginResponse(BaseModel):
    """Base64 vault-unlock nonce response."""

    nonce_b64: str


class UnlockCompleteRequest(BaseModel):
    """Unlock-complete body; scope is intentionally session-derived."""

    nonce_b64: str
    counter: int
    signature_b64: str


class StatusResponse(BaseModel):
    """Authenticated app status."""

    connected: bool
    vault_unlocked: bool
    device_id: str


class AskRequest(BaseModel):
    """Scoped app chat request."""

    text: str
    speak: bool = False


class AskResponse(BaseModel):
    """Scoped app chat response."""

    text: str
    path: str
    tool_used: str | None = None
    escalated: bool = False


class ReviewItem(BaseModel):
    """Recipe review item returned to the client."""

    name: str
    description: str
    status: str
    action_class: str
    safety: str
    explanation: str

    @classmethod
    def from_recipe_review(cls, review: RecipeReview) -> ReviewItem:
        """Convert a ReviewSurface dataclass to the wire DTO."""
        return cls(
            name=review.name,
            description=review.description,
            status=review.status,
            action_class=review.action_class,
            safety=review.safety,
            explanation=review.explanation,
        )


class PendingActionResponse(BaseModel):
    """Pending one-off action returned to the client without bound args."""

    id: str
    module: str
    tool: str
    summary: str
    action_class: str
    status: str
    created_at: datetime
    expires_at: datetime
    result: dict[str, object] | None = None

    @classmethod
    def from_pending_action(cls, pa: PendingAction) -> PendingActionResponse:
        """Convert a PendingAction to the wire DTO."""
        return cls(
            id=pa.id,
            module=pa.module,
            tool=pa.tool,
            summary=pa.summary,
            action_class=pa.action_class,
            status=pa.status,
            created_at=pa.created_at,
            expires_at=pa.expires_at,
            result=pa.result,
        )


class ReviewNameRequest(BaseModel):
    """Recipe name command body."""

    name: str


class ActionIdRequest(BaseModel):
    """Pending-action command body."""

    id: str


class CalendarEvent(BaseModel):
    """Calendar event DTO."""

    id: str
    title: str
    start: str
    end: str
    kind: str
    attendees: list[str] | None = None
    rsvp: str | None = None


class CalendarRead(BaseModel):
    """Calendar read DTO."""

    events: list[CalendarEvent]
    tasks_due_by_day: dict[str, int]


class TasksRead(BaseModel):
    """Task dashboard read DTO."""

    overdue: list[str]
    today: list[str]
    upcoming: list[str]
    suggestions: list[str]


class ProjectItem(BaseModel):
    """Project summary DTO."""

    id: str
    name: str
    status: str
    target: str | None = None
    open_tasks: int


class ProjectsRead(BaseModel):
    """Projects read DTO."""

    projects: list[ProjectItem]


class GmailNeed(BaseModel):
    """Email item needing owner attention."""

    id: str
    sender: str
    subject: str
    why: str


class GmailSignal(BaseModel):
    """Important email signal."""

    id: str
    sender: str
    subject: str
    ts: str


class GmailRead(BaseModel):
    """Gmail read DTO."""

    needs_you: list[GmailNeed]
    signal: list[GmailSignal]


class FinanceDaily(BaseModel):
    """Daily spend item."""

    date: str
    amount: float


class FinanceCategory(BaseModel):
    """Spend category item."""

    name: str
    amount: float
    color: str


class FinanceTransaction(BaseModel):
    """Finance transaction item."""

    id: str
    merchant: str
    amount: float
    date: str
    category: str


class FinanceBill(BaseModel):
    """Upcoming bill item."""

    id: str
    name: str
    amount: float
    due: str


class FinanceRead(BaseModel):
    """Finance read DTO."""

    week_total: float
    mtd_total: float
    daily: list[FinanceDaily]
    categories: list[FinanceCategory]
    transactions: list[FinanceTransaction]
    bills: list[FinanceBill]
    unusual: list[str] | None = None
    duplicate: list[str] | None = None
    ambiguous: list[str] | None = None


class DomainReadSource(Protocol):
    """Injected read-source seam for per-domain owner data routes."""

    def calendar(self) -> CalendarRead:
        """Return calendar data."""
        ...

    def tasks(self) -> TasksRead:
        """Return task data."""
        ...

    def projects(self) -> ProjectsRead:
        """Return project data."""
        ...

    def email(self) -> GmailRead:
        """Return email data."""
        ...

    def finance(self) -> FinanceRead:
        """Return finance data."""
        ...


@dataclass
class DefaultDomainReadSource:
    """Typed fake payloads until broker/OAuth-gated domain readers are injected.

    Deviation logged for CLIENT-b Task 8: calendar/tasks/projects are specified
    as real, but this dev tree cannot build them without broker owner DEKs and
    Google OAuth, so all five routes use this typed fake by default behind the
    same injection seam the Mini can replace with real read modules.
    """

    def calendar(self) -> CalendarRead:
        return CalendarRead(
            events=[
                CalendarEvent(
                    id="cal-1",
                    title="Planning",
                    start="2026-06-24T09:00:00+08:00",
                    end="2026-06-24T09:30:00+08:00",
                    kind="meeting",
                    attendees=["owner@example.com"],
                    rsvp="accepted",
                )
            ],
            tasks_due_by_day={"2026-06-24": 2},
        )

    def tasks(self) -> TasksRead:
        return TasksRead(
            overdue=["renew passport"],
            today=["review recipes"],
            upcoming=["book train"],
            suggestions=["Batch admin tasks this afternoon"],
        )

    def projects(self) -> ProjectsRead:
        return ProjectsRead(
            projects=[
                ProjectItem(
                    id="proj-1",
                    name="Artemis client",
                    status="active",
                    target="2026-07-01",
                    open_tasks=4,
                )
            ]
        )

    def email(self) -> GmailRead:
        return GmailRead(
            needs_you=[
                GmailNeed(
                    id="mail-1",
                    sender="alex@example.com",
                    subject="Contract notes",
                    why="contains a direct question",
                )
            ],
            signal=[
                GmailSignal(
                    id="mail-2",
                    sender="ops@example.com",
                    subject="Receipt",
                    ts="2026-06-24T10:00:00+08:00",
                )
            ],
        )

    def finance(self) -> FinanceRead:
        return FinanceRead(
            week_total=321.45,
            mtd_total=1420.10,
            daily=[FinanceDaily(date="2026-06-24", amount=42.0)],
            categories=[FinanceCategory(name="Groceries", amount=123.4, color="#4f7cac")],
            transactions=[
                FinanceTransaction(
                    id="txn-1",
                    merchant="Market",
                    amount=42.0,
                    date="2026-06-24",
                    category="Groceries",
                )
            ],
            bills=[FinanceBill(id="bill-1", name="Internet", amount=79.0, due="2026-06-30")],
            unusual=[],
            duplicate=[],
            ambiguous=[],
        )


async def rate_limited(request: Request) -> None:
    """FastAPI dependency enforcing the peer-IP sliding-window budget."""
    host = request.client.host if request.client is not None else "unknown"
    limiter = cast(RateLimiter, request.app.state.rate_limiter)
    if not limiter.check(host):
        raise HTTPException(status_code=429, detail="too many attempts")


async def require_unlocked(
    request: Request,
    principal: Principal = Depends(require_session),
) -> Principal:
    """Require a valid API session and an unlocked owner vault."""
    key_provider = cast(UnlockProvider, request.app.state.key_provider)
    if not key_provider.is_owner_unlocked():
        raise HTTPException(status_code=423, detail="vault locked")
    return principal


@app_router.post("/admin/pair-code")
async def admin_pair_code(request: Request) -> dict[str, str]:
    """Mint a raw pairing code for localhost callers only."""
    host = request.client.host if request.client is not None else ""
    if host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="loopback only")
    store = cast(PairingCodeStore, request.app.state.pairing_codes)
    return {"code": store.mint()}


@app_router.post("/pair", dependencies=[Depends(rate_limited)])
async def pair(request: Request, body: PairRequest) -> dict[str, bool]:
    """Pair a new app device after code and key-possession verification."""
    _verify_pairing_signature(body)
    codes = cast(PairingCodeStore, request.app.state.pairing_codes)
    if not codes.consume(body.pairing_code):
        raise HTTPException(status_code=401, detail="invalid pairing")

    auth = cast(AppAuth, request.app.state.app_auth)
    registry: DeviceRegistry = auth.registry
    broker = cast(PairRelay, request.app.state.broker_client)
    try:
        registry.register(body.device_id, body.public_key_b64)
        broker.pair(body.device_id, body.public_key_b64)
    except BrokerError as exc:
        registry.remove(body.device_id)
        raise HTTPException(status_code=503, detail="pairing unavailable") from exc
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="invalid pairing") from exc
    return {"paired": True}


@app_router.post(
    "/session/begin",
    response_model=SessionBeginResponse,
    dependencies=[Depends(rate_limited)],
)
async def session_begin(request: Request, body: SessionBeginRequest) -> SessionBeginResponse:
    """Begin an unauthenticated API-session challenge."""
    auth = cast(AppAuth, request.app.state.app_auth)
    try:
        nonce = auth.begin_session(body.device_id)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="authentication failed") from exc
    return SessionBeginResponse(nonce_b64=_b64encode(nonce))


@app_router.post(
    "/session/complete",
    response_model=SessionCompleteResponse,
    dependencies=[Depends(rate_limited)],
)
async def session_complete(
    request: Request, body: SessionCompleteRequest
) -> SessionCompleteResponse:
    """Complete API-session authentication and return a bearer token."""
    auth = cast(AppAuth, request.app.state.app_auth)
    try:
        session = auth.complete_session(
            body.device_id,
            _b64decode(body.nonce_b64),
            body.counter,
            _b64decode(body.signature_b64),
        )
    except (AuthError, binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=401, detail="authentication failed") from exc
    return SessionCompleteResponse(session_token=session.token, expires_at=session.expires_at)


@app_router.post(
    "/unlock/begin",
    response_model=UnlockBeginResponse,
    dependencies=[Depends(rate_limited)],
)
async def unlock_begin(
    request: Request,
    _body: UnlockBeginRequest,
    principal: Principal = Depends(require_session),
) -> UnlockBeginResponse:
    """Begin a vault unlock relay using the scope resolved from the session."""
    key_provider = cast(UnlockProvider, request.app.state.key_provider)
    try:
        nonce = key_provider.begin_unlock(resolve_scope(principal))
    except BrokerError as exc:
        raise HTTPException(status_code=401, detail="unlock failed") from exc
    return UnlockBeginResponse(nonce_b64=_b64encode(nonce))


@app_router.post("/unlock/complete")
async def unlock_complete(
    request: Request,
    body: UnlockCompleteRequest,
    principal: Principal = Depends(require_session),
) -> dict[str, bool]:
    """Complete a vault unlock relay with phone proof passed through to the broker."""
    key_provider = cast(UnlockProvider, request.app.state.key_provider)
    proof: dict[str, object] = {
        "device_id": principal.device_id,
        "counter": body.counter,
        "signature": body.signature_b64,
    }
    try:
        key_provider.complete_unlock(resolve_scope(principal), _b64decode(body.nonce_b64), proof)
    except (BrokerError, binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=401, detail="unlock failed") from exc
    return {"unlocked": True}


@app_router.get("/status", response_model=StatusResponse)
async def status(
    request: Request,
    principal: Principal = Depends(require_session),
) -> StatusResponse:
    """Return session and vault status without requiring an unlocked vault."""
    key_provider = cast(UnlockProvider, request.app.state.key_provider)
    return StatusResponse(
        connected=True,
        vault_unlocked=key_provider.is_owner_unlocked(),
        device_id=principal.device_id,
    )


@app_router.post("/lock")
async def lock(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> dict[str, bool]:
    """Lock owner data without revoking the API session."""
    key_provider = cast(UnlockProvider, request.app.state.key_provider)
    key_provider.lock_all()
    return {"locked": True}


@app_router.post("/logout")
async def logout(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> dict[str, bool]:
    """Revoke the current API-session token."""
    auth = cast(AppAuth, request.app.state.app_auth)
    auth.logout(_bearer_token(request))
    return {"ok": True}


@app_router.get("/layout", response_model=LayoutDTO)
async def get_layout(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> LayoutDTO:
    """Return stored layout or the default seed while the vault may be locked."""
    store = cast(LayoutStore, request.app.state.layout_store)
    return store.get() or default_layout()


@app_router.put("/layout", response_model=LayoutDTO)
async def put_layout(
    request: Request,
    body: LayoutDTO,
    _principal: Principal = Depends(require_session),
) -> LayoutDTO:
    """Persist a layout using last-writer-wins semantics."""
    store = cast(LayoutStore, request.app.state.layout_store)
    return store.put(body)


@app_router.get("/review/pending", response_model=list[ReviewItem])
async def review_pending(
    request: Request,
    _principal: Principal = Depends(require_unlocked),
) -> list[ReviewItem]:
    """Return recipes pending owner review."""
    surface = cast(ReviewSurfaceProtocol, request.app.state.review_surface)
    return [ReviewItem.from_recipe_review(item) for item in surface.pending_for_review()]


@app_router.get("/review/auto-enabled", response_model=list[ReviewItem])
async def review_auto_enabled(
    request: Request,
    _principal: Principal = Depends(require_unlocked),
) -> list[ReviewItem]:
    """Return auto-enabled recipes."""
    surface = cast(ReviewSurfaceProtocol, request.app.state.review_surface)
    return [ReviewItem.from_recipe_review(item) for item in surface.auto_enabled()]


@app_router.post("/review/approve", response_model=ReviewItem)
async def review_approve(
    request: Request,
    body: ReviewNameRequest,
    _principal: Principal = Depends(require_unlocked),
) -> ReviewItem:
    """Approve one pending recipe."""
    surface = cast(ReviewSurfaceProtocol, request.app.state.review_surface)
    try:
        return ReviewItem.from_recipe_review(await surface.approve(body.name))
    except (KeyError, RecipeAlreadyRetiredError, RecipeSignatureError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app_router.post("/review/reject", response_model=ReviewItem)
async def review_reject(
    request: Request,
    body: ReviewNameRequest,
    _principal: Principal = Depends(require_unlocked),
) -> ReviewItem:
    """Reject one pending recipe."""
    surface = cast(ReviewSurfaceProtocol, request.app.state.review_surface)
    try:
        return ReviewItem.from_recipe_review(await surface.reject(body.name))
    except (KeyError, RecipeAlreadyRetiredError, RecipeSignatureError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app_router.get("/actions/pending", response_model=list[PendingActionResponse])
async def get_pending_actions(
    request: Request,
    principal: Principal = Depends(require_unlocked),
) -> list[PendingActionResponse]:
    """Return one-off actions awaiting owner approval."""
    actions = request.app.state.action_staging.list_pending()
    return [PendingActionResponse.from_pending_action(a) for a in actions]


@app_router.post("/actions/approve", response_model=PendingActionResponse)
async def approve_action(
    request: Request,
    body: ActionIdRequest,
    principal: Principal = Depends(require_unlocked),
) -> PendingActionResponse:
    """Execute an approved pending action once."""
    try:
        pa = await request.app.state.action_staging.approve(body.id)
    except KeyError:
        raise HTTPException(status_code=404, detail="action not found")
    except ValueError:
        raise HTTPException(status_code=409, detail="action already settled")
    except ScopeLockedError:
        raise HTTPException(status_code=423, detail="vault locked")
    return PendingActionResponse.from_pending_action(pa)


@app_router.post("/actions/reject", response_model=PendingActionResponse)
async def reject_action(
    request: Request,
    body: ActionIdRequest,
    principal: Principal = Depends(require_unlocked),
) -> PendingActionResponse:
    """Reject a pending action without executing it."""
    try:
        pa = request.app.state.action_staging.reject(body.id)
    except KeyError:
        raise HTTPException(status_code=404, detail="action not found")
    except ValueError:
        raise HTTPException(status_code=409, detail="action already settled")
    return PendingActionResponse.from_pending_action(pa)


@app_router.post("/ask", response_model=AskResponse)
async def ask(
    request: Request,
    body: AskRequest,
    principal: Principal = Depends(require_unlocked),
) -> AskResponse:
    """Answer one scoped chat request."""
    gateway = cast(GatewayProtocol, request.app.state.gateway)
    result = await gateway.handle_text_scoped(body.text, resolve_scope(principal))
    return AskResponse(
        text=result.text,
        path=result.path,
        tool_used=result.tool_used,
        escalated=result.escalated,
    )


@app_router.post("/ask/stream")
async def ask_stream(
    request: Request,
    body: AskRequest,
    principal: Principal = Depends(require_unlocked),
) -> StreamingResponse:
    """Stream a scoped chat answer as SSE frames."""
    gateway = cast(GatewayProtocol, request.app.state.gateway)
    key_provider = cast(UnlockProvider, request.app.state.key_provider)
    scope = resolve_scope(principal)
    if hasattr(gateway, "handle_ask_unified"):
        display_iter, speak_iter = await gateway.handle_ask_unified(
            body.text,
            scope_or_identity=scope,
            speak=body.speak,
        )
    else:
        display_iter = gateway.handle_text_stream_scoped(body.text, scope)
        speak_iter = _drainable_empty_speak()
    if body.speak:
        # S1 default sink drains (no emission). S3 NOTE: a real TTS speak_sink MUST
        # re-check key_provider.is_owner_unlocked() before speaking each segment (the
        # display branch below already does per-chunk) and should retain this task
        # reference + log failures (fire-and-forget here is safe only for the drain).
        speak_sink = getattr(request.app.state, "speak_sink", _drain_speak)
        asyncio.create_task(speak_sink(speak_iter))

    async def event_stream() -> AsyncIterator[str]:
        # Fail closed: re-check the vault BEFORE emitting any owner content,
        # including before the first chunk (the vault may lock between the
        # require_unlocked gate and the first token).
        if not key_provider.is_owner_unlocked():
            yield f"data: {json.dumps({'error': 'vault_locked'})}\n\n"
            return
        try:
            async for chunk in display_iter:
                if not key_provider.is_owner_unlocked():
                    yield f"data: {json.dumps({'error': 'vault_locked'})}\n\n"
                    return
                yield f"data: {chunk}\n\n"
        except Exception:  # noqa: BLE001 - never truncate silently; fail closed
            yield f"data: {json.dumps({'error': 'stream_failed'})}\n\n"
            return
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _drain_speak(it: AsyncIterator[SpeakSeg]) -> None:
    async for _ in it:
        pass


async def _drainable_empty_speak() -> AsyncIterator[SpeakSeg]:
    if False:
        yield ""


@app_router.get("/calendar", response_model=CalendarRead)
async def calendar(
    request: Request,
    _principal: Principal = Depends(require_unlocked),
) -> CalendarRead:
    """Read calendar data through the injected domain read source."""
    return _domain_source(request).calendar()


@app_router.get("/tasks", response_model=TasksRead)
async def tasks(
    request: Request,
    _principal: Principal = Depends(require_unlocked),
) -> TasksRead:
    """Read task data through the injected domain read source."""
    return _domain_source(request).tasks()


@app_router.get("/projects", response_model=ProjectsRead)
async def projects(
    request: Request,
    _principal: Principal = Depends(require_unlocked),
) -> ProjectsRead:
    """Read project data through the injected domain read source."""
    return _domain_source(request).projects()


@app_router.get("/email", response_model=GmailRead)
async def email(
    request: Request,
    _principal: Principal = Depends(require_unlocked),
) -> GmailRead:
    """Read email data through the injected domain read source."""
    return _domain_source(request).email()


@app_router.get("/finance", response_model=FinanceRead)
async def finance(
    request: Request,
    _principal: Principal = Depends(require_unlocked),
) -> FinanceRead:
    """Read finance data through the injected domain read source."""
    return _domain_source(request).finance()


def _domain_source(request: Request) -> DomainReadSource:
    value = getattr(request.app.state, "domain_read_source", None)
    if value is None:
        return DefaultDomainReadSource()
    return cast(DomainReadSource, value)


def _verify_pairing_signature(body: PairRequest) -> None:
    try:
        public_key_bytes = _b64decode(body.public_key_b64)
        signature = _b64decode(body.code_signature_b64)
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(),
            public_key_bytes,
        )
        code_bytes = body.pairing_code.encode("utf-8")
        message = len(code_bytes).to_bytes(2, "big") + code_bytes + body.device_id.encode("utf-8")
        public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
    except (ValueError, binascii.Error, InvalidSignature) as exc:
        raise HTTPException(status_code=401, detail="invalid pairing") from exc


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def _sha256_hex(value: str) -> str:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(value.encode("utf-8"))
    return digest.finalize().hex()


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token == "":
        raise HTTPException(status_code=401, detail="unauthenticated")
    return token
