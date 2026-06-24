"""Content-free observability sink protocol and fan-out helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from artemis.obs.logging import get_logger


class ObservabilitySink(Protocol):
    """Observability events carrying only non-content primitives."""

    def on_route_decision(
        self,
        task_class_key: str,
        confidence: float,
        path: str,
        *,
        now: datetime,
    ) -> None:
        """Record a route decision without raw request content."""
        ...

    def on_escalation(
        self,
        task_class_key: str,
        *,
        is_cloud_safe: bool,
        now: datetime,
    ) -> None:
        """Record an escalation by safe task class key."""
        ...

    def on_error(self, component: str, exc: BaseException, *, now: datetime) -> None:
        """Record a component error without traceback content."""
        ...


class NullSink:
    """No-op sink used as the backward-compatible default."""

    def on_route_decision(
        self,
        task_class_key: str,
        confidence: float,
        path: str,
        *,
        now: datetime,
    ) -> None:
        pass

    def on_escalation(
        self,
        task_class_key: str,
        *,
        is_cloud_safe: bool,
        now: datetime,
    ) -> None:
        pass

    def on_error(self, component: str, exc: BaseException, *, now: datetime) -> None:
        pass


class CompositeSink:
    """Fan out events to child sinks while never raising to callers."""

    def __init__(self, sinks: Sequence[ObservabilitySink]) -> None:
        self._sinks = tuple(sinks)

    def on_route_decision(
        self,
        task_class_key: str,
        confidence: float,
        path: str,
        *,
        now: datetime,
    ) -> None:
        for sink in self._sinks:
            try:
                sink.on_route_decision(task_class_key, confidence, path, now=now)
            except Exception as exc:
                self._log_child_failure(sink, exc)

    def on_escalation(
        self,
        task_class_key: str,
        *,
        is_cloud_safe: bool,
        now: datetime,
    ) -> None:
        for sink in self._sinks:
            try:
                sink.on_escalation(task_class_key, is_cloud_safe=is_cloud_safe, now=now)
            except Exception as exc:
                self._log_child_failure(sink, exc)

    def on_error(self, component: str, exc: BaseException, *, now: datetime) -> None:
        for sink in self._sinks:
            try:
                sink.on_error(component, exc, now=now)
            except Exception as child_exc:
                self._log_child_failure(sink, child_exc)

    def _log_child_failure(self, sink: ObservabilitySink, exc: BaseException) -> None:
        get_logger("obs").warning(
            "sink_child_failed",
            extra={"sink": type(sink).__name__, "error_type": type(exc).__name__},
        )
