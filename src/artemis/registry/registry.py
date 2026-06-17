"""Tool registry — register module manifests, embed on first retrieval,
auto-export to JSON for index-free tool discovery.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from artemis.manifest import ActionRisk, ModuleManifest, ToolSpec
from artemis.ports.retrieval import EmbeddingModel
from artemis.registry.index import InMemoryToolIndex

# Synthetic scope used for the tool index
_TOOLS_SCOPE = "tools"


class ToolRegistry:
    """Registry for module manifests and tool discovery.

    Construction + ``register()`` are network-free (lazy embedding).
    The first ``retrieve_tools*()`` call drains pending entries and
    embeds tool descriptions via the supplied ``EmbeddingModel``.
    """

    def __init__(
        self,
        embedder: EmbeddingModel,
        index: InMemoryToolIndex | None = None,
    ) -> None:
        self._embedder = embedder
        self._index = index or InMemoryToolIndex()
        self._manifests: dict[str, ModuleManifest] = {}
        self._pending: list[tuple[str, ToolSpec]] = []  # (fq_id, tool)
        self._drained = False
        # All registered tools keyed by fq_id — includes _execute twins
        self._tools: dict[str, ToolSpec] = {}
        self._execute_callables: dict[str, Any] = {}

    def register(self, manifest: ModuleManifest) -> None:
        """Register a module manifest.

        Lazy — does NOT embed or contact any network. The embed happens
        on the first ``retrieve_tools*()`` call.
        """
        if manifest.name in self._manifests:
            raise ValueError(f"Duplicate module name: {manifest.name}")

        self._manifests[manifest.name] = manifest

        for tool in manifest.tools:
            fq_id = f"{manifest.name}.{tool.name}"
            self._tools[fq_id] = tool
            self._pending.append((fq_id, tool))

            # Register _execute twin for write/high-stakes tools
            if tool.action_risk in (ActionRisk.WRITE, ActionRisk.HIGH_STAKES):
                exec_id = f"{fq_id}_execute"
                self._execute_callables[exec_id] = tool.callable_ref

    async def _drain_pending(self) -> None:
        """Embed all pending tool descriptions and add them to the index."""
        if not self._pending or self._drained:
            return

        fq_ids = []
        descriptions = []
        for fq_id, tool in self._pending:
            fq_ids.append(fq_id)
            descriptions.append(f"{tool.name}: {tool.description}")

        # Batch-embed all descriptions (stored text — NO query prefix)
        vectors = await self._embedder.embed_documents(descriptions)

        metadata_list: list[dict[str, object]] = []
        for fq_id in fq_ids:
            parts = fq_id.split(".", 1)
            module_name = parts[0] if len(parts) == 2 else ""
            tool_name = parts[1] if len(parts) == 2 else fq_id
            tool = self._tools[fq_id]
            metadata_list.append(
                {
                    "text": f"{tool.name}: {tool.description}",
                    "module": module_name,
                    "tool": tool_name,
                    "action_risk": tool.action_risk.value,
                }
            )

        self._index.add(_TOOLS_SCOPE, fq_ids, vectors, metadata_list)
        self._pending.clear()
        self._drained = True

    async def retrieve_tools(self, query: str, k: int = 3) -> list[str]:
        """Retrieve top-k tool fq ids by embedding similarity."""
        await self._drain_pending()
        query_vec = await self._embedder.embed_query(query)
        results = self._index.search(_TOOLS_SCOPE, query_vec, k)
        return [r.chunk.chunk_id for r in results]

    async def retrieve_tools_scored(self, query: str, k: int = 3) -> list[tuple[str, float]]:
        """Retrieve top-k (fq_id, cosine_score) pairs."""
        await self._drain_pending()
        query_vec = await self._embedder.embed_query(query)
        results = self._index.search(_TOOLS_SCOPE, query_vec, k)
        return [(r.chunk.chunk_id, r.score) for r in results]

    def get_tool(self, fq_name: str) -> ToolSpec:
        """Resolve a ``module.tool`` fq id to its ``ToolSpec``.

        Also accepts ``{fq_name}_execute`` to retrieve a write-execute
        twin (returns a synthetic ``ToolSpec`` wrapping the twin callable).
        """
        if fq_name in self._execute_callables:
            # Build a synthetic ToolSpec for the execute twin
            base_name = fq_name.replace("_execute", "", 1)
            if base_name in self._tools:
                base = self._tools[base_name]
                return ToolSpec(
                    name=base.name,
                    description=base.description,
                    args_schema=base.args_schema,
                    return_schema=base.return_schema,
                    callable_ref=self._execute_callables[fq_name],
                    action_risk=base.action_risk,
                )
        if fq_name in self._tools:
            return self._tools[fq_name]
        raise KeyError(f"Unknown tool: {fq_name}")

    def export_index(self, path: Path) -> None:
        """Write the auto-exported indexed form as JSON.

        Each entry has ``module``, ``version``, ``data_scope``, ``tool``,
        ``description``, ``args_schema``, ``return_schema``, ``action_risk``.
        Callables are NOT serialised.
        """
        entries: list[dict[str, object]] = []
        for name, manifest in self._manifests.items():
            for tool in manifest.tools:
                entries.append(
                    {
                        "module": name,
                        "version": manifest.version,
                        "data_scope": manifest.data_scope.value,
                        "tool": tool.name,
                        "description": tool.description,
                        "args_schema": tool.args_json_schema(),
                        "return_schema": tool.return_json_schema(),
                        "action_risk": tool.action_risk.value,
                    }
                )

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(entries, f, indent=2, default=str)
            os.replace(tmp_path, path)
        except BaseException:
            os.unlink(tmp_path)
            raise

    def manifests(self) -> dict[str, ModuleManifest]:
        """Return a read-only view of registered manifests."""
        return dict(self._manifests)
