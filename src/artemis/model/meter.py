"""Per-role model-call meter: append-only SQLite, mirrors scheduler/ledger.py.

ADR-049 #4. Every role-resolved call records role, binding provider, actually-served model
(ModelResponse.model_id -- for router-bound roles this is the backend the router chose, not the
"router" sentinel), prompt/completion/cache tokens, latency ms, timestamp. Recording is fail-soft:
a meter failure logs a warning and returns the response, never raising into the model call path.
Cache fields are read getattr-with-default: the meter works whether or not the usage-parse spec
(which adds cache_read_tokens/cache_creation_tokens to Usage) has landed -- build-order independent.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from artemis.ports.model import ModelPort
from artemis.types import Message, ModelResponse

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoleUsage:
    role: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    avg_latency_ms: float


class ModelMeter:
    """Append-only per-call meter in SQLite (sync; low-volume; called from async handlers)."""

    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        now: Callable[[], float] = time.time,
        check_same_thread: bool = True,
    ) -> None:
        self._now = now
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS calls ("
            " id INTEGER PRIMARY KEY, role TEXT NOT NULL, provider TEXT NOT NULL,"
            " model TEXT NOT NULL, prompt_tokens INTEGER NOT NULL,"
            " completion_tokens INTEGER NOT NULL,"
            " cache_read_tokens INTEGER NOT NULL DEFAULT 0,"
            " cache_creation_tokens INTEGER NOT NULL DEFAULT 0,"
            " latency_ms INTEGER NOT NULL, at REAL NOT NULL)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS calls_role ON calls(role)")
        self._conn.commit()

    def record(
        self,
        role: str,
        provider: str,
        model: str,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        self._conn.execute(
            "INSERT INTO calls(role, provider, model, prompt_tokens, completion_tokens,"
            " cache_read_tokens, cache_creation_tokens, latency_ms, at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (
                role,
                provider,
                model,
                prompt_tokens,
                completion_tokens,
                cache_read_tokens,
                cache_creation_tokens,
                latency_ms,
                self._now(),
            ),
        )
        self._conn.commit()

    def usage(self) -> list[RoleUsage]:
        """Per-role aggregates (calls, summed tokens incl. cache, mean latency), by role."""
        rows = cast(
            Iterable[tuple[str, int, int, int, int, int, float]],
            self._conn.execute(
                "SELECT role, COUNT(*), COALESCE(SUM(prompt_tokens), 0),"
                " COALESCE(SUM(completion_tokens), 0), COALESCE(SUM(cache_read_tokens), 0),"
                " COALESCE(SUM(cache_creation_tokens), 0), COALESCE(AVG(latency_ms), 0.0)"
                " FROM calls GROUP BY role ORDER BY role"
            ),
        )
        return [RoleUsage(r, c, p, comp, cr, cc, lat) for (r, c, p, comp, cr, cc, lat) in rows]

    def close(self) -> None:
        self._conn.close()


class MeteredPort:
    """Wrap a ModelPort so every completion is recorded to the meter (fail-soft).

    Satisfies ModelPort structurally. The inner call is NOT guarded -- a real model failure
    propagates unchanged; only the meter write is guarded.
    """

    def __init__(self, inner: ModelPort, *, meter: ModelMeter, role: str, provider: str) -> None:
        self._inner = inner
        self._meter = meter
        self._role = role
        self._provider = provider

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        t0 = time.perf_counter()
        resp = await self._inner.complete(
            messages=messages,
            model=model,
            response_schema=response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        try:
            # Cache fields via getattr-with-default: present once the usage-parse spec lands
            # (Usage gains cache_read_tokens/cache_creation_tokens, defaults 0); zeros before.
            # Either build order works -- neither spec blocks the other.
            self._meter.record(
                self._role,
                self._provider,
                resp.model_id,
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                latency_ms=latency_ms,
                cache_read_tokens=int(getattr(resp.usage, "cache_read_tokens", 0)),
                cache_creation_tokens=int(getattr(resp.usage, "cache_creation_tokens", 0)),
            )
        except Exception:  # noqa: BLE001 -- metering must never fail the model call
            _log.warning("model_meter: record failed for role %r", self._role, exc_info=True)
        return resp
