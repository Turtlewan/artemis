"""Module manifest contract — typed tool/hook specifications.

Every Artemis module declares a ``ModuleManifest`` with typed
``ToolSpec`` and ``HookSpec`` entries forming the hybrid contract
(code carries callables + schemas; auto-export carries descriptions
+ JSON schemas for retrieval).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from artemis.proactive.hook_types import DeliverySpec

if TYPE_CHECKING:
    from artemis.proactive.hook_types import HookResult
else:
    HookResult = object


class ActionRisk(StrEnum):
    """Risk level for a tool action."""

    NO_DATA = "no-data"
    READ = "read"
    WRITE = "write"
    HIGH_STAKES = "high-stakes"


class DataScope(StrEnum):
    """Data visibility scope for a module."""

    OWNER_PRIVATE = "owner-private"
    GUEST_VISIBLE = "guest-visible"
    SHARED = "shared"


class Permissions(BaseModel):
    """Per-capability permission flags."""

    owner: bool = True
    guest: bool = False


class ToolSpec(BaseModel):
    """Specification for a single tool in a module manifest.

    The ``callable_ref`` is an ``async def`` callable that takes a
    single validated Pydantic args model and returns a Pydantic result
    model (ADR-016: uniform async tool dispatch).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    args_schema: type[BaseModel]
    return_schema: type[BaseModel]
    callable_ref: Callable[..., Awaitable[BaseModel]]
    action_risk: ActionRisk

    def args_json_schema(self) -> dict[str, object]:
        """Return the JSON Schema for ``args_schema``."""
        return self.args_schema.model_json_schema()

    def return_json_schema(self) -> dict[str, object]:
        """Return the JSON Schema for ``return_schema``."""
        return self.return_schema.model_json_schema()


class HookSpec(BaseModel):
    """Specification for a proactive hook (deterministic check callback)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    interval_seconds: int | None = None
    cron: str | None = None
    tier: Literal[0, 1] = 1
    urgency: str = "normal"  # Literal["low", "normal", "high"]
    needs_llm: bool = False
    dedup_key: str | None = None
    delivery: DeliverySpec | None = None
    check_ref: Callable[[], HookResult] | None = None

    @model_validator(mode="after")
    def _validate_one_schedule(self) -> HookSpec:
        if (self.interval_seconds is None) == (self.cron is None):
            raise ValueError("hook needs exactly one of interval_seconds or cron")
        return self


class UiSurface(BaseModel):
    """UI surface hint for a module."""

    kind: str = "none"  # Literal["none", "card", "page"]
    title: str | None = None


class ModuleManifest(BaseModel):
    """Typed manifest for an Artemis module.

    A module declares tools, data scope, permissions, hooks, and UI
    surface through this manifest. The manifest is consumed by the
    ``ToolRegistry`` at registration time.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    version: str
    description: str
    tools: list[ToolSpec] = []
    data_scope: DataScope = DataScope.OWNER_PRIVATE
    permissions: Permissions = Permissions()
    proactive_hooks: list[HookSpec] = []
    ui: UiSurface = UiSurface()

    @field_validator("name")
    @classmethod
    def _validate_name_slug(cls, v: str) -> str:
        if not re.match(r"^[a-z][a-z0-9_]*$", v):
            raise ValueError(f"Module name must be a non-empty lowercase slug (a-z, 0-9, _): {v!r}")
        return v

    @field_validator("tools")
    @classmethod
    def _validate_unique_tool_names(cls, v: list[ToolSpec]) -> list[ToolSpec]:
        names = [t.name for t in v]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate tool names in manifest: {names}")
        return v

    @model_validator(mode="after")
    def _validate_owner_private_hooks_are_tier1(self) -> ModuleManifest:
        if self.data_scope is DataScope.OWNER_PRIVATE:
            for hook in self.proactive_hooks:
                if hook.tier == 0:
                    raise ValueError(
                        f"Tier-0 hook may not sit on an owner-private module: {hook.name}"
                    )
        return self
