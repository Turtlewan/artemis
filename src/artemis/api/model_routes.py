"""Session-gated model-role registry + per-role usage routes (ADR-049 #2, #4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from artemis.api.auth import Principal, require_session
from artemis.model.meter import ModelMeter
from artemis.model.roles import (
    PROVIDERS,
    ROLES,
    DropReason,
    ModelRoleRegistry,
    RoleBinding,
    RoleRegistryError,
)

# Boundary pinning (mirrors secret_routes' pattern idiom): reject junk before it reaches the
# registry. model allows "" only so router bindings round-trip -- the registry 422s an empty
# model for any non-router provider.
_PROVIDER_PATTERN = r"^[a-z_]{1,32}$"
_MODEL_PATTERN = r"^[A-Za-z0-9._:-]{0,64}$"


class ConstraintsDTO(BaseModel):
    no_tools: bool
    temperature: float | None


class RoleBindingDTO(BaseModel):
    role: str
    provider: str
    model: str
    constraints: ConstraintsDTO
    eligible_providers: list[str]
    editable_fields: list[str] = Field(default_factory=lambda: ["provider", "model"])


class DroppedOverrideDTO(BaseModel):
    role: str
    reason: DropReason


class ModelsResponse(BaseModel):
    roles: list[RoleBindingDTO]
    providers: list[str]
    dropped_overrides: list[DroppedOverrideDTO]


class RoleUpdateRequest(BaseModel):
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    model: str = Field(pattern=_MODEL_PATTERN)


class RoleUsageDTO(BaseModel):
    role: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    avg_latency_ms: float


class UsageResponse(BaseModel):
    roles: list[RoleUsageDTO]


router = APIRouter(prefix="/app")


def _registry(request: Request) -> ModelRoleRegistry:
    reg: ModelRoleRegistry = request.app.state.model_roles
    return reg


def _meter(request: Request) -> ModelMeter:
    meter: ModelMeter = request.app.state.model_meter
    return meter


def _binding_dto(reg: ModelRoleRegistry, role: str) -> RoleBindingDTO:
    binding = reg.get(role)
    constraints = reg.constraints(role)
    return RoleBindingDTO(
        role=role,
        provider=binding.provider,
        model=binding.model,
        constraints=ConstraintsDTO(
            no_tools=constraints.no_tools, temperature=constraints.temperature
        ),
        eligible_providers=reg.eligible_providers(role),
    )


@router.get("/models", response_model=ModelsResponse)
async def list_models(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> ModelsResponse:
    reg = _registry(request)
    return ModelsResponse(
        roles=[_binding_dto(reg, role) for role in ROLES],
        providers=list(PROVIDERS),
        dropped_overrides=[
            DroppedOverrideDTO(role=d.role, reason=d.reason) for d in reg.dropped_overrides()
        ],
    )


@router.put("/models/{role}", response_model=RoleBindingDTO)
async def put_model(
    role: str,
    body: RoleUpdateRequest,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> RoleBindingDTO:
    reg = _registry(request)
    try:
        reg.put(role, RoleBinding(provider=body.provider, model=body.model))
    except RoleRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return _binding_dto(reg, role)


@router.get("/models/usage", response_model=UsageResponse)
async def usage_models(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> UsageResponse:
    rows = _meter(request).usage()
    return UsageResponse(
        roles=[
            RoleUsageDTO(
                role=u.role,
                calls=u.calls,
                prompt_tokens=u.prompt_tokens,
                completion_tokens=u.completion_tokens,
                cache_read_tokens=u.cache_read_tokens,
                cache_creation_tokens=u.cache_creation_tokens,
                avg_latency_ms=u.avg_latency_ms,
            )
            for u in rows
        ]
    )
