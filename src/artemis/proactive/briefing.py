"""Daily briefing proactive hook.

The briefing check only collects Tier-0-safe module summaries. It is declared
as ``needs_llm=True`` so the prose rendering happens through the hit handler's
single batched LLM call for the tick; no template registration is needed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from artemis.manifest import DataScope, HookSpec, ModuleManifest, Permissions, UiSurface
from artemis.proactive.hook_types import HookResult
from artemis.registry import ToolRegistry


def build_briefing_check(
    registry: ToolRegistry,
    summarisers: Mapping[str, Callable[[], dict[str, object]]],
) -> Callable[[], HookResult]:
    """Build a deterministic briefing check from registered module summarisers."""

    def check_ref() -> HookResult:
        sections: dict[str, dict[str, object]] = {}
        for module_name in registry.manifests():
            summariser = summarisers.get(module_name)
            if summariser is None:
                continue
            summary = summariser()
            if summary:
                sections[module_name] = summary

        if not sections:
            return HookResult.miss()
        return HookResult.of(
            {"sections": sections},
            dedup_value=datetime.now().date().isoformat(),
        )

    return check_ref


def briefing_manifest(check_ref: Callable[[], HookResult]) -> ModuleManifest:
    """Return the Tier-0 shared daily briefing module manifest."""
    return ModuleManifest(
        name="briefing",
        version="0.1.0",
        description="Daily owner briefing.",
        data_scope=DataScope.SHARED,
        permissions=Permissions(owner=True, guest=False),
        tools=[],
        proactive_hooks=[
            HookSpec(
                name="daily_briefing",
                cron="30 7 * * *",
                urgency="normal",
                needs_llm=True,
                tier=0,
                dedup_key="briefing",
                check_ref=check_ref,
            )
        ],
        ui=UiSurface(),
    )
