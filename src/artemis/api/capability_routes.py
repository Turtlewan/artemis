"""Capability-build routes: drive CB-1's gated forge over HTTP (propose -> build -> promote)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from artemis.api.auth import Principal, require_session
from artemis.capabilities.forge import CapabilityForge
from artemis.expiry import evict_expired
from artemis.capabilities.store import FileCapabilityStore
from artemis.ports.secrets import SecretStorePort
from artemis.types import BuildProposal


# Server-held builds are created deliberately (one per "Build it"), so a longer TTL / larger cap
# than invokes suffices. Eviction is lazy at proposal creation (see expiry.py).
_BUILD_TTL_SECONDS = 3600.0
_BUILD_MAX_ENTRIES = 64


@dataclass
class BuildState:
    """Server-side state for one in-flight build, between the plan gate and the result gate."""

    proposal: BuildProposal
    staged_id: str | None = None
    created_at: float = field(default_factory=time.monotonic)


class ProposeRequest(BaseModel):
    goal: str


class PlanCard(BaseModel):
    build_id: str
    name: str
    description: str
    summary: str
    secrets: list[str]
    # Network domains the capability is granted (empty = no network) — shown at the gate so the
    # owner consents to network scope before the build/verify runs.
    egress_domains: list[str]
    # Subset of `secrets` NOT yet in the credential store — surfaced so the client can prompt for
    # them (the end-of-build pending item deep-links into the keys panel to capture each).
    missing_secrets: list[str]
    blocked: bool
    block_reason: str | None = None


class PromoteRequest(BaseModel):
    build_id: str


class InstalledCard(BaseModel):
    name: str
    version: int
    path: str
    auth_status: str
    built_at: str | None


class CapabilitySummary(BaseModel):
    name: str
    description: str
    version: int
    uses: list[str]
    secrets: list[str]
    auth_status: str
    oauth_scopes: list[str]
    goal: str
    built_at: str | None


class CapabilitiesList(BaseModel):
    capabilities: list[CapabilitySummary]


router = APIRouter(prefix="/app/capabilities")


def _forge(request: Request) -> CapabilityForge:
    forge: CapabilityForge = request.app.state.forge
    return forge


def _store(request: Request) -> FileCapabilityStore:
    store: FileCapabilityStore = request.app.state.capability_store
    return store


def _builds(request: Request) -> dict[str, BuildState]:
    builds: dict[str, BuildState] = request.app.state.builds
    return builds


def _named_event(event: str, data: str) -> str:
    """One named SSE event; multi-line data is split into `data:` lines per the SSE spec."""
    lines = "".join(f"data: {line}\n" for line in data.split("\n"))
    return f"event: {event}\n{lines}\n"


@router.get("", response_model=CapabilitiesList)
async def list_capabilities(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> CapabilitiesList:
    skills = _store(request).list()
    return CapabilitiesList(
        capabilities=[
            CapabilitySummary(
                name=s.name,
                description=s.description,
                version=s.version,
                uses=s.uses,
                secrets=s.secrets,
                auth_status=s.auth_status,
                oauth_scopes=s.oauth_scopes,
                goal=s.goal,
                built_at=s.built_at,
            )
            for s in skills
        ]
    )


@router.post("/propose", response_model=PlanCard)
async def propose(
    req: ProposeRequest,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> PlanCard:
    proposal = await _forge(request).propose(req.goal)
    builds = _builds(request)
    evict_expired(builds, ttl_seconds=_BUILD_TTL_SECONDS, max_entries=_BUILD_MAX_ENTRIES)
    build_id = uuid4().hex
    builds[build_id] = BuildState(proposal=proposal)
    draft = proposal.draft
    secrets_store: SecretStorePort = request.app.state.secrets
    stored = set(secrets_store.list_names())
    missing_secrets = [name for name in draft.secrets if name not in stored]
    return PlanCard(
        build_id=build_id,
        name=draft.name,
        description=draft.description,
        summary=draft.body,
        secrets=draft.secrets,
        egress_domains=draft.egress_domains,
        missing_secrets=missing_secrets,
        blocked=proposal.blocked,
        block_reason=proposal.block_reason,
    )


@router.post("/{build_id}/build")
async def build(
    build_id: str,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> StreamingResponse:
    forge = _forge(request)
    state = _builds(request).get(build_id)

    async def event_stream() -> AsyncIterator[str]:
        if state is None:
            yield _named_event("error", "unknown build")
            yield "data: [DONE]\n\n"
            return
        if state.proposal.blocked:
            reason = state.proposal.block_reason or "blocked"
            yield _named_event("status", reason)
            yield _named_event(
                "result",
                json.dumps(
                    {
                        "build_id": build_id,
                        "passed": False,
                        "blocked": True,
                        "output": reason,
                    }
                ),
            )
            yield "data: [DONE]\n\n"
            return
        yield _named_event("status", "Testing in sandbox…")
        attempt = await forge.build_proposed(state.proposal)
        state.staged_id = attempt.staged_id
        yield _named_event(
            "result",
            json.dumps(
                {
                    "build_id": build_id,
                    "passed": attempt.passed,
                    "blocked": False,
                    "output": attempt.output[:1000],
                }
            ),
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/promote", response_model=InstalledCard)
async def promote(
    req: PromoteRequest,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> InstalledCard:
    builds = _builds(request)
    state = builds.get(req.build_id)
    if state is None or state.staged_id is None:
        raise HTTPException(status_code=409, detail="build not verified")
    skill = await _forge(request).promote(state.staged_id)
    del builds[req.build_id]
    return InstalledCard(
        name=skill.name,
        version=skill.version,
        path=skill.path,
        auth_status=skill.auth_status,
        built_at=skill.built_at,
    )
