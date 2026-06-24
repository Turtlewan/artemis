"""Telemetry sink and read-side source for Curiosity gap scanning."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from artemis.curiosity.gaps import ConfidenceEvent, EscalationEvent, StaleItem
from artemis.obs.telemetry.store import TelemetryStore
from artemis.recipes import RecipeStore


class TelemetrySink:
    """Observability sink that persists route and escalation metrics only."""

    def __init__(self, store: TelemetryStore) -> None:
        self._store = store

    def on_route_decision(
        self,
        task_class_key: str,
        confidence: float,
        path: str,
        *,
        now: datetime,
    ) -> None:
        """Record only the route row; escalations are recorded by on_escalation."""

        self._store.record_route(task_class_key, confidence, path, at=now)

    def on_escalation(
        self,
        task_class_key: str,
        *,
        is_cloud_safe: bool,
        now: datetime,
    ) -> None:
        """Record one real escalation row."""

        self._store.record_escalation(task_class_key, is_cloud_safe, at=now)

    def on_error(self, component: str, exc: BaseException, *, now: datetime) -> None:
        """Ignore errors; OBS-a ErrorCaptureSink owns error persistence."""

        pass


class SqliteTelemetrySource:
    """Read telemetry rows using the Curiosity ``TelemetrySource`` contract."""

    def __init__(
        self,
        store: TelemetryStore,
        recipe_store: RecipeStore,
        *,
        staleness_days: int = 90,
        chunk_stale_reader: Callable[[], Sequence[StaleItem]] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._recipe_store = recipe_store
        self._staleness_days = staleness_days
        self._chunk_stale_reader = chunk_stale_reader
        self._clock = clock

    def escalations(self) -> Sequence[EscalationEvent]:
        """Return escalation events projected into Curiosity event types."""

        return [
            EscalationEvent(task_class_key=task_class_key, at=at)
            for task_class_key, at in self._store.escalation_events()
        ]

    def low_confidence_answers(self) -> Sequence[ConfidenceEvent]:
        """Return ALL confidence events; callers must apply any confidence floor."""

        return [
            ConfidenceEvent(task_class_key=task_class_key, confidence=confidence, at=at)
            for task_class_key, confidence, _path, at in self._store.route_events()
        ]

    def topic_counts(self) -> dict[str, int]:
        """Return route counts grouped by task class key."""

        return self._store.topic_counts()

    def stale_items(self) -> Sequence[StaleItem]:
        """Return stale recipes plus optional chunk staleness events."""

        cutoff = self._clock() - timedelta(days=self._staleness_days)
        items: list[StaleItem] = []
        for recipe in self._recipe_store.list():
            verified_at_text = recipe.provenance.get("verified_at")
            if verified_at_text is None:
                continue
            try:
                verified_at = datetime.fromisoformat(verified_at_text)
            except ValueError:
                continue
            if verified_at.tzinfo is None:
                verified_at = verified_at.replace(tzinfo=UTC)
            if verified_at < cutoff:
                items.append(
                    StaleItem(
                        item_id=recipe.name,
                        kind="recipe",
                        last_verified_at=verified_at,
                    )
                )
        if self._chunk_stale_reader is not None:
            items.extend(self._chunk_stale_reader())
        return items
