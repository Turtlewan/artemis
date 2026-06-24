"""Telemetry gap scanning for the Curiosity loop."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol


@dataclass(frozen=True)
class EscalationEvent:
    """A routed task that required escalation."""

    task_class_key: str
    at: datetime


@dataclass(frozen=True)
class ConfidenceEvent:
    """An answer confidence observation from telemetry."""

    task_class_key: str
    confidence: float
    at: datetime


@dataclass(frozen=True)
class StaleItem:
    """A knowledge or recipe item whose freshness can be inspected."""

    item_id: str
    kind: Literal["chunk", "recipe"]
    last_verified_at: datetime


class TelemetrySource(Protocol):
    """Read-only telemetry source consumed by the Curiosity gap scanner."""

    def escalations(self) -> Sequence[EscalationEvent]:
        """Return recent escalation events."""
        ...

    def low_confidence_answers(self) -> Sequence[ConfidenceEvent]:
        """Return answer confidence observations."""
        ...

    def topic_counts(self) -> Mapping[str, int]:
        """Return routed topic frequencies keyed by task class."""
        ...

    def stale_items(self) -> Sequence[StaleItem]:
        """Return candidate stale knowledge or recipe items."""
        ...


@dataclass(frozen=True)
class Gap:
    """A deterministic curriculum candidate for one Curiosity cycle."""

    task_class_key: str
    kind: Literal["escalation-cluster", "low-confidence", "recurring-topic", "staleness"]
    score: float
    evidence_count: int


def scan_gaps(
    telemetry: TelemetrySource,
    *,
    now: datetime,
    confidence_floor: float = 0.5,
    staleness_days: int = 90,
) -> list[Gap]:
    """Build scored gaps from telemetry signals.

    Scores use ``evidence_count * recency_weight * (1 + staleness_factor)``. Recency
    weight is ``1 / (1 + age_days)`` for event-backed signals; staleness factor is
    the number of days beyond the freshness threshold divided by the threshold.
    """

    gaps: list[Gap] = []
    escalation_groups: dict[str, list[EscalationEvent]] = defaultdict(list)
    for event in telemetry.escalations():
        escalation_groups[event.task_class_key].append(event)
    for task_class_key, escalation_events in escalation_groups.items():
        latest = max(event.at for event in escalation_events)
        gaps.append(
            Gap(
                task_class_key=task_class_key,
                kind="escalation-cluster",
                score=_score(len(escalation_events), now=now, latest=latest, staleness_factor=0.0),
                evidence_count=len(escalation_events),
            )
        )

    confidence_groups: dict[str, list[ConfidenceEvent]] = defaultdict(list)
    for confidence_event in telemetry.low_confidence_answers():
        if confidence_event.confidence < confidence_floor:
            confidence_groups[confidence_event.task_class_key].append(confidence_event)
    for task_class_key, confidence_events in confidence_groups.items():
        latest = max(event.at for event in confidence_events)
        confidence_gap = max(
            0.0,
            confidence_floor - min(event.confidence for event in confidence_events),
        )
        gaps.append(
            Gap(
                task_class_key=task_class_key,
                kind="low-confidence",
                score=_score(
                    len(confidence_events),
                    now=now,
                    latest=latest,
                    staleness_factor=confidence_gap,
                ),
                evidence_count=len(confidence_events),
            )
        )

    for task_class_key, count in telemetry.topic_counts().items():
        if count <= 0:
            continue
        gaps.append(
            Gap(
                task_class_key=task_class_key,
                kind="recurring-topic",
                score=float(count),
                evidence_count=count,
            )
        )

    cutoff = now - timedelta(days=staleness_days)
    stale_counts: Counter[str] = Counter()
    stale_factor_sum: dict[str, float] = defaultdict(float)
    for item in telemetry.stale_items():
        if item.last_verified_at >= cutoff:
            continue
        task_class_key = item.item_id
        stale_counts[task_class_key] += 1
        stale_factor_sum[task_class_key] += _staleness_factor(
            now=now,
            last_verified_at=item.last_verified_at,
            staleness_days=staleness_days,
        )
    for task_class_key, count in stale_counts.items():
        gaps.append(
            Gap(
                task_class_key=task_class_key,
                kind="staleness",
                score=_score(
                    count,
                    now=now,
                    latest=now,
                    staleness_factor=stale_factor_sum[task_class_key] / count,
                ),
                evidence_count=count,
            )
        )

    return gaps


def pick_top_gap(gaps: Sequence[Gap]) -> Gap | None:
    """Return the highest-scored gap, or ``None`` when no candidate exists."""

    if not gaps:
        return None
    return max(gaps, key=lambda gap: (gap.score, gap.evidence_count, gap.task_class_key))


def _score(
    evidence_count: int,
    *,
    now: datetime,
    latest: datetime,
    staleness_factor: float,
) -> float:
    age = max(timedelta(), now - latest)
    recency_weight = 1.0 / (1.0 + age.total_seconds() / 86_400.0)
    return evidence_count * recency_weight * (1.0 + staleness_factor)


def _staleness_factor(*, now: datetime, last_verified_at: datetime, staleness_days: int) -> float:
    age_days = max(0.0, (now - last_verified_at).total_seconds() / 86_400.0)
    if staleness_days <= 0:
        return age_days
    return max(0.0, (age_days - staleness_days) / staleness_days)
