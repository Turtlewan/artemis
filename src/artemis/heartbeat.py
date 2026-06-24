"""Heartbeat scheduler and pure proactive hook dispatch loop."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as datetime_time
from typing import Literal, cast

from artemis.identity.key_provider import KeyProvider
from artemis.manifest import HookSpec
from artemis.proactive.hook_types import HEARTBEAT_OK as HEARTBEAT_OK
from artemis.proactive.hook_types import Hit, HookResult, TickResult
from artemis.registry import ToolRegistry
from artemis.runtime_config import get_runtime_config

logger = logging.getLogger(__name__)


class _UnlockedKeyProvider:
    """Default back-compat provider: no owner-private hooks are registered."""

    def is_owner_unlocked(self) -> bool:
        return True


@dataclass
class _ResolvedHook:
    module: str
    hook: HookSpec
    next_due_monotonic: float | None
    last_fired_date: date | None
    cron_minute: int | None
    cron_hour: int | None


class Heartbeat:
    """Scheduled-tick engine for deterministic proactive hooks.

    ``tick`` evaluates due hooks and returns a ``TickResult``. It never calls an
    LLM or delivery transport; later milestones consume the ``on_hits`` and
    ``tier1_sink`` seams.
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        key_provider: KeyProvider | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = datetime.now,
        on_hits: Callable[[TickResult], Awaitable[None]] | None = None,
        tier1_sink: Callable[[Hit], None] | None = None,
        pre_tick_steps: list[Callable[[], Awaitable[None]]] | None = None,
        interval_seconds: float = 60.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._registry = registry
        self._key_provider = key_provider or _UnlockedKeyProvider()
        self._clock = clock
        self._wall_clock = wall_clock
        self._on_hits = on_hits
        self._tier1_sink = tier1_sink
        self.pre_tick_steps = list(pre_tick_steps or [])
        self._sleep_seconds = interval_seconds
        self._log = logger or logging.getLogger(__name__)
        runtime_config = get_runtime_config()
        self._wake_fallback_time = runtime_config.tasks.morning_digest_fallback_time
        self._weekend_review_day = runtime_config.tasks.weekend_review_day
        self._week_ahead_day = runtime_config.tasks.week_ahead_day
        self._wake_date: date | None = None
        self._hooks = self._build_hook_table()

    def _build_hook_table(self) -> list[_ResolvedHook]:
        records: list[_ResolvedHook] = []
        if self._registry is None:
            return records

        now = self._clock()
        for module, manifest in self._registry.manifests().items():
            for hook in manifest.proactive_hooks:
                cron_minute: int | None = None
                cron_hour: int | None = None
                if hook.cron is not None:
                    cron_minute, cron_hour = self._parse_daily_cron(hook.cron)
                records.append(
                    _ResolvedHook(
                        module=module,
                        hook=hook,
                        next_due_monotonic=now if hook.interval_seconds is not None else None,
                        last_fired_date=None,
                        cron_minute=cron_minute,
                        cron_hour=cron_hour,
                    )
                )
        return records

    @staticmethod
    def _parse_daily_cron(cron: str) -> tuple[int, int]:
        parts = cron.split()
        if len(parts) != 5:
            raise ValueError(f"unsupported cron expression: {cron}")
        minute, hour, day, month, weekday = parts
        if day != "*" or month != "*" or weekday != "*":
            raise ValueError(f"unsupported cron expression: {cron}")
        if not minute.isdigit() or not hour.isdigit():
            raise ValueError(f"unsupported cron expression: {cron}")

        minute_int = int(minute)
        hour_int = int(hour)
        if not 0 <= minute_int <= 59 or not 0 <= hour_int <= 23:
            raise ValueError(f"unsupported cron expression: {cron}")
        return minute_int, hour_int

    def _interval_due(self, rec: _ResolvedHook, now_mono: float) -> bool:
        if rec.hook.interval_seconds is None or rec.next_due_monotonic is None:
            return False
        if now_mono < rec.next_due_monotonic:
            return False
        rec.next_due_monotonic += rec.hook.interval_seconds
        return True

    def _cron_due(self, rec: _ResolvedHook, now_wall: datetime) -> bool:
        if rec.hook.cron is None:
            return False
        if rec.cron_hour is None or rec.cron_minute is None:
            rec.cron_minute, rec.cron_hour = self._parse_daily_cron(rec.hook.cron)

        today = now_wall.date()
        due_at = datetime.combine(today, datetime_time(rec.cron_hour, rec.cron_minute))
        if now_wall >= due_at and rec.last_fired_date != today:
            rec.last_fired_date = today
            return True
        return False

    @staticmethod
    def _today_at(now_wall: datetime, hhmm: str) -> datetime:
        """Return today's wall-clock datetime for a validated ``HH:MM`` value."""
        hour_text, minute_text = hhmm.split(":")
        return datetime.combine(now_wall.date(), datetime_time(int(hour_text), int(minute_text)))

    def note_wake(self, now_wall: datetime) -> None:
        """Record the daily wake signal from the gateway's first owner interaction.

        This seam is idempotent within a day. Wake hooks still pass through the
        normal tier gate; the latch only records that a wake was observed.
        """
        self._wake_date = now_wall.date()

    def _wake_due(self, rec: _ResolvedHook, now_wall: datetime) -> bool:
        """Evaluate a wake hook's wake-or-fallback single-fire invariant."""
        hook = rec.hook
        today = now_wall.date()
        if rec.last_fired_date == today:
            return False
        if hook.wake_day_gate is not None and now_wall.weekday() != hook.wake_day_gate:
            return False

        wake_observed = self._wake_date == today
        fallback_reached = hook.wake_fallback_time is not None and now_wall >= self._today_at(
            now_wall, hook.wake_fallback_time
        )
        if wake_observed or fallback_reached:
            rec.last_fired_date = today
            return True
        return False

    def tick(self) -> TickResult:
        """Execute one scheduler tick and return its ``TickResult``."""
        now_mono = self._clock()
        now_wall = self._wall_clock()
        hits: list[Hit] = []
        tier1_skipped: list[str] = []

        for rec in self._hooks:
            if not self._is_due(rec, now_mono, now_wall):
                continue

            hook = rec.hook
            fq_name = f"{rec.module}.{hook.name}"
            if hook.tier == 1 and not self._key_provider.is_owner_unlocked():
                tier1_skipped.append(fq_name)
                if self._tier1_sink is not None:
                    self._send_tier1_queue_token(rec)
                continue

            result = self._run_check_ref(rec)
            if not result.hit:
                continue

            hits.append(
                Hit(
                    module=rec.module,
                    hook_name=hook.name,
                    tier=hook.tier,
                    urgency=cast(Literal["low", "normal", "high"], hook.urgency),
                    needs_llm=hook.needs_llm,
                    dedup_key=hook.dedup_key,
                    result=result,
                    delivery=hook.delivery,
                )
            )

        summary = HEARTBEAT_OK if not hits else f"{len(hits)} hit(s)"
        tick_result = TickResult(
            hits=tuple(hits), summary=summary, tier1_skipped=tuple(tier1_skipped)
        )

        if not hits:
            self._log.debug("heartbeat tick: silent success")

        return tick_result

    def _is_due(self, rec: _ResolvedHook, now_mono: float, now_wall: datetime) -> bool:
        return (
            self._interval_due(rec, now_mono)
            or self._cron_due(rec, now_wall)
            or (rec.hook.wake and self._wake_due(rec, now_wall))
        )

    def _send_tier1_queue_token(self, rec: _ResolvedHook) -> None:
        hook = rec.hook
        token = Hit(
            module=rec.module,
            hook_name=hook.name,
            tier=hook.tier,
            urgency=cast(Literal["low", "normal", "high"], hook.urgency),
            needs_llm=hook.needs_llm,
            dedup_key=hook.dedup_key,
            result=HookResult.miss(),
            delivery=hook.delivery,
        )
        try:
            if self._tier1_sink is not None:
                self._tier1_sink(token)
        except Exception:
            self._log.exception("heartbeat tier1 sink failed")

    def _run_check_ref(self, rec: _ResolvedHook) -> HookResult:
        if rec.hook.check_ref is None:
            return HookResult.miss()
        try:
            return rec.hook.check_ref()
        except Exception:
            self._log.exception("heartbeat hook failed: %s.%s", rec.module, rec.hook.name)
            return HookResult.miss()

    async def run_forever(
        self, *, max_ticks: int | None = None, sleep_seconds: float | None = None
    ) -> None:
        """Run ticks until cancelled or ``max_ticks`` is reached."""
        ticks = 0
        delay = self._sleep_seconds if sleep_seconds is None else sleep_seconds
        try:
            while max_ticks is None or ticks < max_ticks:
                for step in self.pre_tick_steps:
                    try:
                        await step()
                    except Exception:
                        self._log.exception("heartbeat pre-tick step failed")
                tr = self.tick()
                if tr.hits and self._on_hits is not None:
                    try:
                        await self._on_hits(tr)
                    except Exception:
                        self._log.exception("heartbeat on_hits handler failed")
                ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    break
                await asyncio.sleep(delay)
        finally:
            self._log.debug("heartbeat shutdown after %d ticks", ticks)
