"""Loop tools: the FREE LOCAL-READ affordances the agent loop can chain (ADR-047 #2).

AL-1 registers exactly two: a local record-store read and a memory retrieve. Both are deterministic
local reads (no model call inside a tool - the driver is the only LLM in the loop). A tool returns an
OBSERVATION string that becomes the next transcript turn; the local-read observation renders
Record.sanitized_text ONLY (never the raw structured payload - the same ingest-quarantine injection
boundary data/read.py enforces).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from artemis.data.store import DataStore, Record
from artemis.ports.memory import MemoryPort

_MAX_ROWS = 20
_MEMORY_TOKEN_BUDGET = 512


@runtime_checkable
class LoopTool(Protocol):
    """One local-read affordance. `run` returns an observation string for the driver."""

    name: str
    description: str
    args_schema: dict[str, Any]

    async def run(self, args: dict[str, Any]) -> str: ...


class ToolRegistry:
    """Injectable name->tool map + a `specs()` view for the driver prompt."""

    def __init__(self, tools: Sequence[LoopTool]) -> None:
        self._tools: dict[str, LoopTool] = {t.name: t for t in tools}

    def get(self, name: str) -> LoopTool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "args_schema": t.args_schema}
            for t in self._tools.values()
        ]


class _LocalStoreReadTool:
    name = "local_read"
    description = (
        "Read the owner's LOCAL synced/curated records for one domain (e.g. calendar, tasks). "
        "args: {domain: string (required, a domain label), text: string (optional substring "
        "filter), limit: integer (optional, default 20)}. Returns matching records, newest first."
    )
    args_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "text": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["domain"],
        "additionalProperties": False,
    }

    def __init__(self, store: DataStore) -> None:
        self._store = store

    async def run(self, args: dict[str, Any]) -> str:
        domain = str(args.get("domain", "")).strip()
        if not domain:
            return "ERROR: local_read requires a 'domain'."
        text = args.get("text")
        text = str(text) if isinstance(text, str) and text.strip() else None
        limit = args.get("limit")
        limit = limit if isinstance(limit, int) and 0 < limit <= _MAX_ROWS else _MAX_ROWS
        rows = self._store.query(domain=domain, text=text, limit=limit)
        if not rows:
            return f"No records in domain '{domain}'."
        return f"{len(rows)} record(s) in '{domain}':\n" + _render_rows(rows)


class _MemoryRetrieveTool:
    name = "memory_retrieve"
    description = (
        "Retrieve relevant items from the owner's long-term memory. "
        "args: {query: string (required), token_budget: integer (optional, default 512)}."
    )
    args_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "token_budget": {"type": "integer"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(
        self, memory: MemoryPort, *, default_token_budget: int = _MEMORY_TOKEN_BUDGET
    ) -> None:
        self._memory = memory
        self._default_token_budget = default_token_budget

    async def run(self, args: dict[str, Any]) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "ERROR: memory_retrieve requires a 'query'."
        budget = args.get("token_budget")
        budget = budget if isinstance(budget, int) and budget > 0 else self._default_token_budget
        ctx = await self._memory.retrieve(query, token_budget=budget)
        if not ctx.items:
            return f"No memory items for '{query}'."
        return f"{len(ctx.items)} memory item(s):\n" + "\n".join(
            f"- [{item.layer}] {item.content}" for item in ctx.items
        )


def build_local_read_tool(store: DataStore) -> LoopTool:
    """Build a `LoopTool` that reads local synced records for one domain from `store`."""
    return _LocalStoreReadTool(store)


def build_memory_tool(memory: MemoryPort) -> LoopTool:
    """Build a `LoopTool` that retrieves items from long-term memory via `memory`."""
    return _MemoryRetrieveTool(memory)


def _render_rows(rows: Sequence[Record]) -> str:
    # sanitized_text ONLY - never raw payload (the ingest quarantine boundary).
    return "\n".join(f"- [{r.kind}] {r.sanitized_text}" for r in rows)
