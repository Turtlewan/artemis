"""Artemis ports — typed Protocol interfaces for every swappable seam.

Every upgradeability seam is defined here as a ``typing.Protocol``.
Concrete adapters live in ``artemis.adapters.*`` or engine packages.
"""

from artemis.ports.memory import MemoryStore
from artemis.ports.model import ModelPort, ModelResponse
from artemis.ports.retrieval import EmbeddingModel, Reranker, Retriever, VectorStore
from artemis.ports.routing import RouteDecision, Router
from artemis.ports.types import (
    AsOf,
    Chunk,
    Document,
    Fact,
    Message,
    Mode,
    PersonId,
    RetrievedChunk,
    Scope,
    Usage,
    Vector,
)
from artemis.ports.voice import VAD, AudioFrontend, SpeakerID, Stt, Tts, WakeWord

__all__ = [
    "AsOf",
    "AudioFrontend",
    "Chunk",
    "Document",
    "EmbeddingModel",
    "Fact",
    "MemoryStore",
    "Message",
    "Mode",
    "ModelPort",
    "ModelResponse",
    "PersonId",
    "Reranker",
    "RetrievedChunk",
    "Retriever",
    "RouteDecision",
    "Router",
    "Scope",
    "SpeakerID",
    "Stt",
    "Tts",
    "Usage",
    "VAD",
    "Vector",
    "VectorStore",
    "WakeWord",
]
