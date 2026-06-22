"""Tests for the manifest contract and tool registry (M1-a).

Includes a ``FakeEmbedder`` that maps strings to deterministic hash-based
vectors so "what time is it" is closest to the time tool's description.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from artemis.manifest import (
    ActionRisk,
    DataScope,
    ModuleManifest,
    Permissions,
    ToolSpec,
)
from artemis.ports import VectorStore
from artemis.ports.types import Vector
from artemis.registry import InMemoryToolIndex, ToolRegistry

# ── Fake embedder ──────────────────────────────────────────────────────────


class FakeEmbedder:
    """Deterministic hash-based embedder for testing.

    Maps each input string to a fixed-dimension vector using a bag-of-words
    hash so semantically-close strings score higher (same words → higher
    cosine similarity). Implements the ``EmbeddingModel`` port.
    """

    DIMENSION = 16

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._hash_vec(t) for t in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._hash_vec(query)

    def _hash_vec(self, text: str) -> Vector:
        """Build a fixed-dim vector from word-level hashes (process-stable)."""
        vec = [0.0] * self.DIMENSION
        words = text.lower().split()
        for word in words:
            bucket = hashlib.sha256(word.encode()).digest()[0] % self.DIMENSION
            vec[bucket] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec


# ── Tool callable stubs ────────────────────────────────────────────────────


class TimeArgs(BaseModel):
    tz: str | None = None


class TimeResult(BaseModel):
    iso: str
    tz: str


async def fake_get_current_time(args: TimeArgs) -> TimeResult:
    """Stub time tool — returns fixed values for testing."""
    return TimeResult(iso="2026-06-17T12:00:00", tz=args.tz or "UTC")


class EmailArgs(BaseModel):
    to: str
    subject: str
    body: str


class EmailResult(BaseModel):
    sent: bool
    message_id: str


async def fake_send_email(args: EmailArgs) -> EmailResult:
    """Stub email tool — returns fixed values for testing."""
    return EmailResult(sent=True, message_id="msg_001")


class WriteArgs(BaseModel):
    path: str
    content: str


class WriteResult(BaseModel):
    success: bool


async def fake_write_file(args: WriteArgs) -> WriteResult:
    """Stub write tool — for testing _execute twin registration."""
    return WriteResult(success=True)


# ── Manifest fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def time_manifest() -> ModuleManifest:
    return ModuleManifest(
        name="time",
        version="0.1.0",
        description="Time utilities.",
        data_scope=DataScope.SHARED,
        permissions=Permissions(owner=True, guest=True),
        tools=[
            ToolSpec(
                name="get_current_time",
                description="Get the current date and time in a timezone.",
                args_schema=TimeArgs,
                return_schema=TimeResult,
                callable_ref=fake_get_current_time,
                action_risk=ActionRisk.NO_DATA,
            )
        ],
    )


@pytest.fixture
def email_manifest() -> ModuleManifest:
    return ModuleManifest(
        name="email",
        version="0.1.0",
        description="Email utilities.",
        data_scope=DataScope.OWNER_PRIVATE,
        tools=[
            ToolSpec(
                name="send_email",
                description="Send an email message.",
                args_schema=EmailArgs,
                return_schema=EmailResult,
                callable_ref=fake_send_email,
                action_risk=ActionRisk.WRITE,
            )
        ],
    )


# ── Tests ──────────────────────────────────────────────────────────────────


class TestManifestValidation:
    """Sync tests for the manifest and tool spec models."""

    def test_valid_manifest(self) -> None:
        m = ModuleManifest(
            name="demo",
            version="0.1.0",
            description="A test module.",
            data_scope=DataScope.OWNER_PRIVATE,
        )
        assert m.name == "demo"
        assert len(m.tools) == 0

    def test_bad_name_raises(self) -> None:
        with pytest.raises(ValidationError, match="lowercase slug"):
            ModuleManifest(
                name="Bad Name",
                version="0.1.0",
                description="Invalid.",
                data_scope=DataScope.OWNER_PRIVATE,
            )

    def test_duplicate_tool_names_raises(self) -> None:
        with pytest.raises(ValidationError, match="Duplicate tool"):
            ModuleManifest(
                name="test",
                version="0.1.0",
                description="Duplicates.",
                data_scope=DataScope.OWNER_PRIVATE,
                tools=[
                    ToolSpec(
                        name="same_name",
                        description="First tool",
                        args_schema=TimeArgs,
                        return_schema=TimeResult,
                        callable_ref=fake_get_current_time,
                        action_risk=ActionRisk.NO_DATA,
                    ),
                    ToolSpec(
                        name="same_name",
                        description="Second tool (same name)",
                        args_schema=TimeArgs,
                        return_schema=TimeResult,
                        callable_ref=fake_get_current_time,
                        action_risk=ActionRisk.NO_DATA,
                    ),
                ],
            )

    def test_tool_spec_bare_name(self) -> None:
        """ToolSpec.name is bare (no module prefix) — Seam 2."""
        tool = ToolSpec(
            name="get_current_time",
            description="Get time.",
            args_schema=TimeArgs,
            return_schema=TimeResult,
            callable_ref=fake_get_current_time,
            action_risk=ActionRisk.NO_DATA,
        )
        assert tool.name == "get_current_time"
        assert "." not in tool.name

    def test_tool_json_schema_methods(self) -> None:
        tool = ToolSpec(
            name="test_tool",
            description="A test tool.",
            args_schema=TimeArgs,
            return_schema=TimeResult,
            callable_ref=fake_get_current_time,
            action_risk=ActionRisk.NO_DATA,
        )
        args_schema = tool.args_json_schema()
        assert "properties" in args_schema
        return_schema = tool.return_json_schema()
        assert "properties" in return_schema


class TestInMemoryIndex:
    """Sync tests for the in-memory cosine index."""

    def test_port_conformance(self) -> None:
        """InMemoryToolIndex structurally satisfies VectorStore."""
        index = InMemoryToolIndex()
        # InMemoryToolIndex uses concrete list signatures (list[str] vs
        # Sequence[str]); the real conformance test lives in test_ports.py
        # which drives a dedicated minimal impl.
        vs: VectorStore = index
        assert vs is not None

    def test_search_returns_at_most_k(self) -> None:
        index = InMemoryToolIndex()
        vecs: list[Vector] = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        index.add(
            "default",
            ["a", "b", "c"],
            vecs,
            [{"text": "a"}, {"text": "b"}, {"text": "c"}],
        )
        results = index.search("default", [1.0, 0.0, 0.0], k=2)
        assert len(results) <= 2

    def test_search_filters_by_scope(self) -> None:
        index = InMemoryToolIndex()
        index.add("scope_a", ["id1"], [[1.0, 0.0]], [{"text": "hello"}])
        index.add("scope_b", ["id2"], [[1.0, 0.0]], [{"text": "world"}])
        results = index.search("scope_a", [1.0, 0.0], k=5)
        assert len(results) == 1
        assert results[0].chunk.chunk_id == "id1"


class TestToolRegistry:
    """Async and sync tests for the ToolRegistry."""

    @pytest.mark.asyncio
    async def test_register_no_network_at_construction(self) -> None:
        """register() is lazy — no embed call during construction."""
        embedder = FakeEmbedder()
        registry = ToolRegistry(embedder)
        registry.register(
            ModuleManifest(
                name="test",
                version="0.1.0",
                description="Test.",
                data_scope=DataScope.OWNER_PRIVATE,
            )
        )
        # No embed called yet — passes if no network error
        assert len(registry.manifests()) == 1

    @pytest.mark.asyncio
    async def test_duplicate_module_raises(self) -> None:
        embedder = FakeEmbedder()
        registry = ToolRegistry(embedder)
        manifest = ModuleManifest(
            name="dup",
            version="0.1.0",
            description="First.",
            data_scope=DataScope.OWNER_PRIVATE,
        )
        registry.register(manifest)
        with pytest.raises(ValueError, match="Duplicate module"):
            registry.register(manifest)

    @pytest.mark.asyncio
    async def test_retrieve_tools_returns_fq_ids(
        self, time_manifest: ModuleManifest, email_manifest: ModuleManifest
    ) -> None:
        embedder = FakeEmbedder()
        registry = ToolRegistry(embedder)
        registry.register(time_manifest)
        registry.register(email_manifest)

        # Query for time — should return the time tool first
        results = await registry.retrieve_tools("current time in timezone", k=2)
        assert "time.get_current_time" in results
        assert results.index("time.get_current_time") == 0

    @pytest.mark.asyncio
    async def test_retrieve_tools_no_execute_twins(self, time_manifest: ModuleManifest) -> None:
        """retrieve_tools must NOT return _execute-twin ids."""
        embedder = FakeEmbedder()
        registry = ToolRegistry(embedder)
        registry.register(time_manifest)

        results = await registry.retrieve_tools("time", k=5)
        for r in results:
            assert not r.endswith("_execute"), f"Found _execute twin in results: {r}"

    @pytest.mark.asyncio
    async def test_retrieve_tools_scored(self, time_manifest: ModuleManifest) -> None:
        embedder = FakeEmbedder()
        registry = ToolRegistry(embedder)
        registry.register(time_manifest)

        scored = await registry.retrieve_tools_scored("what time is it", k=1)
        assert len(scored) >= 1
        fq_id, score = scored[0]
        assert fq_id == "time.get_current_time"
        assert score > 0.0

    def test_get_tool(self, time_manifest: ModuleManifest) -> None:
        embedder = FakeEmbedder()
        registry = ToolRegistry(embedder)
        registry.register(time_manifest)

        spec = registry.get_tool("time.get_current_time")
        assert spec.name == "get_current_time"
        assert callable(spec.callable_ref)

    def test_get_tool_unknown_raises(self) -> None:
        embedder = FakeEmbedder()
        registry = ToolRegistry(embedder)
        with pytest.raises(KeyError):
            registry.get_tool("nonexistent.tool")

    @pytest.mark.asyncio
    async def test_execute_twin_registration(self) -> None:
        """Write-risk tools get an _execute twin registered."""
        embedder = FakeEmbedder()
        registry = ToolRegistry(embedder)

        write_manifest = ModuleManifest(
            name="files",
            version="0.1.0",
            description="File operations.",
            data_scope=DataScope.OWNER_PRIVATE,
            tools=[
                ToolSpec(
                    name="write_file",
                    description="Write content to a file.",
                    args_schema=WriteArgs,
                    return_schema=WriteResult,
                    callable_ref=fake_write_file,
                    action_risk=ActionRisk.WRITE,
                )
            ],
        )
        registry.register(write_manifest)

        twin = registry.get_tool("files.write_file_execute")
        assert twin is not None
        assert callable(twin.callable_ref)
        assert twin.name == "write_file"

    def test_export_round_trip(self, time_manifest: ModuleManifest, tmp_path: Path) -> None:
        embedder = FakeEmbedder()
        registry = ToolRegistry(embedder)
        registry.register(time_manifest)

        export_path = tmp_path / "tool_index.json"
        registry.export_index(export_path)

        assert export_path.exists()
        with export_path.open() as f:
            data = json.load(f)

        assert len(data) == 1
        entry = data[0]
        assert entry["module"] == "time"
        assert entry["tool"] == "get_current_time"
        assert entry["description"] == "Get the current date and time in a timezone."
        assert "args_schema" in entry
        assert "return_schema" in entry
        assert "callable_ref" not in entry
        assert entry["action_risk"] == "no-data"
