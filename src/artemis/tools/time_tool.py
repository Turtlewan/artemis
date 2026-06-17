"""Time utilities tool — canonical manifest-contract example.

DataScope → storage-scope correspondence (documented here for reference
before M2 enforcement):
  - ``DataScope.SHARED`` → storage scope ``"general"``
  - ``DataScope.OWNER_PRIVATE`` → storage scope ``"owner-private"``
  - ``DataScope.GUEST_VISIBLE`` → ``"general"`` or ``"guest-<id>"`` (context-dependent)
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from artemis.manifest import (
    ActionRisk,
    DataScope,
    ModuleManifest,
    Permissions,
    ToolSpec,
    UiSurface,
)


class TimeArgs(BaseModel):
    """Arguments for ``get_current_time``."""

    tz: str | None = Field(
        default=None,
        description="IANA timezone name, e.g. 'Asia/Singapore'; None → system local time",
    )


class TimeResult(BaseModel):
    """Result from ``get_current_time``."""

    iso: str  # ISO-8601 timestamp
    tz: str  # Resolved timezone name


async def get_current_time(args: TimeArgs) -> TimeResult:
    """Get the current date and time, optionally in a specific timezone.

    Pure — no data, no auth, no I/O beyond the system clock (ADR-016:
    every ``callable_ref`` is ``async def`` even when internally sync).
    """
    if args.tz:
        try:
            zone = ZoneInfo(args.tz)
        except ZoneInfoNotFoundError:
            raise ValueError(f"Unknown timezone: {args.tz!r}") from None
    else:
        local = datetime.now().astimezone().tzinfo
        # stringify and re-parse as ZoneInfo to guarantee a ZoneInfo type
        try:
            zone = ZoneInfo(str(local)) if local else ZoneInfo("UTC")
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")

    now = datetime.now(zone)
    return TimeResult(iso=now.isoformat(), tz=str(zone))


def manifest() -> ModuleManifest:
    """Return the time module manifest.

    ``get_current_time`` is ``NO_DATA``, ``SHARED``, owner+guest permitted —
    the safest possible tool, chosen so the pipeline proof carries no
    scope/risk concerns.
    """
    return ModuleManifest(
        name="time",
        version="0.1.0",
        description="Time utilities: current time in any timezone.",
        data_scope=DataScope.SHARED,
        permissions=Permissions(owner=True, guest=True),
        tools=[
            ToolSpec(
                name="get_current_time",
                description="Get the current date and time, optionally in a specific timezone.",
                args_schema=TimeArgs,
                return_schema=TimeResult,
                callable_ref=get_current_time,
                action_risk=ActionRisk.NO_DATA,
            )
        ],
        proactive_hooks=[],
        ui=UiSurface(),
    )
