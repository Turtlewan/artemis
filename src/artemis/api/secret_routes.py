"""Session-gated secret CRUD routes.

These routes deliberately expose only secret names. Secret values are accepted
only on write and are never logged, echoed, or included in error messages here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from artemis.api.auth import Principal, require_session
from artemis.ports.secrets import SecretStorePort


class SecretWriteRequest(BaseModel):
    name: str
    value: str


class SecretNamesResponse(BaseModel):
    names: list[str]


router = APIRouter(prefix="/app")


def _store(request: Request) -> SecretStorePort:
    store: SecretStorePort = request.app.state.secrets
    return store


@router.post("/secrets", status_code=status.HTTP_204_NO_CONTENT)
async def set_secret(
    body: SecretWriteRequest,
    store: SecretStorePort = Depends(_store),
    _principal: Principal = Depends(require_session),
) -> Response:
    store.set(body.name, body.value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/secrets", response_model=SecretNamesResponse)
async def list_secrets(
    store: SecretStorePort = Depends(_store),
    _principal: Principal = Depends(require_session),
) -> SecretNamesResponse:
    return SecretNamesResponse(names=store.list_names())


@router.delete("/secrets/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(
    name: str,
    store: SecretStorePort = Depends(_store),
    _principal: Principal = Depends(require_session),
) -> Response:
    store.delete(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
