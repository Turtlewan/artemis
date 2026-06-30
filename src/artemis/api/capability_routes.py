"""Capability-build routes: drive CB-1's gated forge over HTTP (propose -> build -> promote)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from artemis.api.auth import Principal, require_session
from artemis.capabilities.forge import CapabilityForge
from artemis.types import BuildProposal


@dataclass
class BuildState:
    """Server-side state for one in-flight build, between the plan gate and the result gate."""

    proposal: BuildProposal
    staged_id: str | None = None


class ProposeRequest(BaseModel):
    goal: str


class PlanCard(BaseModel):
    build_id: str
    name: str
    description: str
    summary: str
    secrets: list[str]
    blocked: bool
    block_reason: str | None = None


class PromoteRequest(BaseModel):
    build_id: str


class InstalledCard(BaseModel):
    name: str
    version: int
    path: str


router = APIRouter(prefix="/app/capabilities")


def _forge(request: Request) -> CapabilityForge:
    forge: CapabilityForge = request.app.state.forge
    return forge


def _builds(request: Request) -> dict[str, BuildState]:
    builds: dict[str, BuildState] = request.app.state.builds
    return builds


def _named_event(event: str, data: str) -> str:
    """One named SSE event; multi-line data is split into `data:` lines per the SSE spec."""
    lines = "".join(f"data: {line}\n" for line in data.split("\n"))
    return f"event: {event}\n{lines}\n"


@router.post("/propose", response_model=PlanCard)
async def propose(
    req: ProposeRequest,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> PlanCard:
    proposal = await _forge(request).propose(req.goal)
    build_id = uuid4().hex
    _builds(request)[build_id] = BuildState(proposal=proposal)
    draft = proposal.draft
    return PlanCard(
        build_id=build_id,
        name=draft.name,
        description=draft.description,
        summary=draft.body,
        secrets=draft.secrets,
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
    return InstalledCard(name=skill.name, version=skill.version, path=skill.path)
