"""Wake-triggered productivity proactive hooks.

The v1 productivity hook payloads carry counts and UUIDs only. They never
include titles, notes, or raw suggestion context; the LLM rendering seam gets
structured summaries rather than owner-authored text.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable

from artemis.manifest import HookSpec
from artemis.modules.productivity.store import ProductivityStore
from artemis.proactive.hit_handler import TemplateRegistry
from artemis.proactive.hook_types import HookResult
from artemis.runtime_config import get_runtime_config

logger = logging.getLogger(__name__)


def make_morning_digest_check(store: ProductivityStore) -> Callable[[], HookResult]:
    """Return a wake digest check with overdue tasks folded into one payload."""

    def check() -> HookResult:
        try:
            today_rows = store.today_tasks()
            overdue = store.overdue_tasks()
            overdue_ids = {task["id"] for task in overdue}
            today = [task for task in today_rows if task["id"] not in overdue_ids]
            if len(today) == 0 and len(overdue) == 0:
                return HookResult.miss()
            return HookResult.of(
                {
                    "today_count": len(today),
                    "overdue_count": len(overdue),
                    "today_task_ids": [task["id"] for task in today],
                    "overdue_task_ids": [task["id"] for task in overdue],
                },
                dedup_value=_today_iso(),
            )
        except Exception:
            logger.warning("productivity morning digest check failed", exc_info=True)
            return HookResult.miss()

    return check


def make_weekend_review_check(store: ProductivityStore) -> Callable[[], HookResult]:
    """Return a Saturday wake review check without Areas-era payload fields."""

    def check() -> HookResult:
        try:
            active_projects = store.list_projects(status="active")
            overdue = store.overdue_tasks()
            if len(active_projects) == 0 and len(overdue) == 0:
                return HookResult.miss()
            return HookResult.of(
                {
                    "project_count": len(active_projects),
                    "overdue_count": len(overdue),
                    "project_ids": [project["id"] for project in active_projects],
                },
                dedup_value=_week_iso(),
            )
        except Exception:
            logger.warning("productivity weekend review check failed", exc_info=True)
            return HookResult.miss()

    return check


def make_week_ahead_check(store: ProductivityStore) -> Callable[[], HookResult]:
    """Return a Sunday-gated check for the daily evening week-ahead cron."""

    def check() -> HookResult:
        try:
            now = datetime.datetime.now(datetime.UTC)
            cfg = get_runtime_config()
            if now.weekday() != cfg.tasks.week_ahead_day:
                return HookResult.miss()
            upcoming = store.upcoming_tasks(days=7)
            active_projects = store.list_projects(status="active")
            if len(upcoming) == 0 and len(active_projects) == 0:
                return HookResult.miss()
            return HookResult.of(
                {
                    "upcoming_count": len(upcoming),
                    "project_count": len(active_projects),
                    "upcoming_task_ids": [task["id"] for task in upcoming],
                    "project_ids": [project["id"] for project in active_projects],
                },
                dedup_value=_sunday_iso(),
            )
        except Exception:
            logger.warning("productivity week-ahead check failed", exc_info=True)
            return HookResult.miss()

    return check


def build_productivity_hooks(store: ProductivityStore) -> list[HookSpec]:
    """Build the wake/cron productivity hook set for the tasks manifest."""
    cfg = get_runtime_config().tasks
    hour_text, minute_text = cfg.week_ahead_time.split(":")
    hour = int(hour_text)
    minute = int(minute_text)
    return [
        HookSpec(
            name="productivity_morning_digest",
            wake=True,
            wake_fallback_time=cfg.morning_digest_fallback_time,
            urgency="normal",
            needs_llm=True,
            tier=1,
            dedup_key="prod_morning_digest",
            check_ref=make_morning_digest_check(store),
        ),
        HookSpec(
            name="productivity_weekend_review",
            wake=True,
            wake_day_gate=cfg.weekend_review_day,
            urgency="low",
            needs_llm=True,
            tier=1,
            dedup_key="prod_weekend_review",
            check_ref=make_weekend_review_check(store),
        ),
        HookSpec(
            name="productivity_week_ahead",
            cron=f"{minute} {hour} * * *",
            urgency="low",
            needs_llm=True,
            tier=1,
            dedup_key="prod_week_ahead",
            check_ref=make_week_ahead_check(store),
        ),
    ]


def register_productivity_templates(registry: TemplateRegistry) -> None:
    """Register deterministic templates for productivity hooks.

    v1 has no template-path productivity hook: all three hooks use the batched
    LLM renderer, so this stability seam intentionally registers nothing.
    """
    del registry


def _today_iso() -> str:
    return datetime.datetime.now(datetime.UTC).date().isoformat()


def _week_iso() -> str:
    date = datetime.datetime.now(datetime.UTC).date()
    iso = date.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _sunday_iso() -> str:
    date = datetime.datetime.now(datetime.UTC).date()
    iso = date.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
