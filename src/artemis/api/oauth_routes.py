"""Session-gated Google OAuth connect/status/disconnect routes."""

from __future__ import annotations

import asyncio
from typing import Literal, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from artemis.api.auth import Principal, require_session
from artemis.oauth.broker import DEFAULT_ACCOUNT, OAuthBroker, OAuthUnavailable


_NOT_CONFIGURED_MESSAGE = "Google OAuth client credentials are not configured"


class ConnectRequest(BaseModel):
    scopes: list[str] = Field(default_factory=list)


class ConnectStartedResponse(BaseModel):
    consent_url: str


class ClientNotConfiguredResponse(BaseModel):
    status: Literal["client_not_configured"] = "client_not_configured"


class StatusResponse(BaseModel):
    account: str
    connected: bool
    granted_scopes: list[str]


class DisconnectRequest(BaseModel):
    account: str = DEFAULT_ACCOUNT


class DisconnectResponse(BaseModel):
    disconnected: bool


router = APIRouter(prefix="/app/oauth/google")


def _broker(request: Request) -> OAuthBroker:
    broker = cast(OAuthBroker, request.app.state.oauth_broker)
    return broker


@router.post("/connect", response_model=ConnectStartedResponse | ClientNotConfiguredResponse)
async def connect_google(
    body: ConnectRequest,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> ConnectStartedResponse | ClientNotConfiguredResponse:
    """Start Google OAuth and serve the loopback callback in the background."""

    broker = _broker(request)
    try:
        consent_url = broker.begin_connect(body.scopes)
    except OAuthUnavailable as exc:
        if str(exc) == _NOT_CONFIGURED_MESSAGE:
            return ClientNotConfiguredResponse()
        raise
    request.app.state.oauth_connect_task = asyncio.create_task(broker.listen_for_callback())
    return ConnectStartedResponse(consent_url=consent_url)


@router.get("/status", response_model=StatusResponse)
async def google_status(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> StatusResponse:
    """Read stored Google OAuth account status without returning token material."""

    account = DEFAULT_ACCOUNT
    status = _broker(request).account_status(account)
    return StatusResponse(
        account=account,
        connected=status.connected,
        granted_scopes=list(status.granted_scopes),
    )


@router.post("/disconnect", response_model=DisconnectResponse)
async def disconnect_google(
    body: DisconnectRequest,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> DisconnectResponse:
    """Disconnect a stored Google OAuth account."""

    await _broker(request).disconnect(body.account)
    return DisconnectResponse(disconnected=True)
