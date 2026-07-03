"""Session-gated desktop bless/revoke routes for capability invocation consent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from artemis.api.auth import Principal, require_session
from artemis.capabilities.bless import BlessStore
from artemis.capabilities.store import FileCapabilityStore


class BlessEntry(BaseModel):
    name: str
    current_version: int | None
    blessed_version: int | None
    blessed: bool


class BlessListResponse(BaseModel):
    capabilities: list[BlessEntry]


router = APIRouter(prefix="/app/bless")


def _bless_store(request: Request) -> BlessStore:
    store: BlessStore = request.app.state.bless
    return store


def _capability_store(request: Request) -> FileCapabilityStore:
    store: FileCapabilityStore = request.app.state.capability_store
    return store


def _entry(name: str, current_version: int | None, blessed_version: int | None) -> BlessEntry:
    return BlessEntry(
        name=name,
        current_version=current_version,
        blessed_version=blessed_version,
        blessed=current_version is not None and blessed_version == current_version,
    )


@router.get("", response_model=BlessListResponse)
async def list_blessed(
    bless: BlessStore = Depends(_bless_store),
    capabilities: FileCapabilityStore = Depends(_capability_store),
    _principal: Principal = Depends(require_session),
) -> BlessListResponse:
    blessed_versions = dict(bless.list_blessed())
    entries: dict[str, BlessEntry] = {}
    for skill in capabilities.list():
        entries[skill.name] = _entry(
            skill.name,
            current_version=skill.version,
            blessed_version=blessed_versions.get(skill.name),
        )
    for name, version in blessed_versions.items():
        if name not in entries:
            entries[name] = _entry(name, current_version=None, blessed_version=version)
    return BlessListResponse(capabilities=[entries[name] for name in sorted(entries)])


@router.post("/{name}", response_model=BlessEntry)
async def set_blessed(
    name: str,
    bless: BlessStore = Depends(_bless_store),
    capabilities: FileCapabilityStore = Depends(_capability_store),
    _principal: Principal = Depends(require_session),
) -> BlessEntry:
    skill = capabilities.get(name)
    if skill is None:
        raise HTTPException(status_code=404, detail="unknown capability")
    bless.bless(skill.name, skill.version)
    return _entry(skill.name, current_version=skill.version, blessed_version=skill.version)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_blessed(
    name: str,
    bless: BlessStore = Depends(_bless_store),
    _principal: Principal = Depends(require_session),
) -> Response:
    bless.unbless(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
