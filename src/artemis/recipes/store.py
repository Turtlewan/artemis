"""File-backed recipe store and in-memory RAG-for-recipes index."""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from artemis import paths
from artemis.config import Settings
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ports.retrieval import EmbeddingModel, VectorStore
from artemis.ports.types import Chunk, RetrievedChunk, Vector
from artemis.recipes.model import Recipe, RecipeStatus
from artemis.recipes.signing import RecipeSignatureError, RecipeSigner

_RECIPE_SCOPE = "recipes"
_Entry = tuple[str, str, tuple[float, ...], dict[str, object]]
type _RecipeNames = list[str]

logger = logging.getLogger(__name__)


def recipes_dir(s: Settings) -> Path:
    """Return the owner-private encrypted-volume recipe directory."""
    return paths.scope_dir(s, OWNER_PRIVATE) / "recipes"


class RecipeIndex:
    """Brute-force cosine index satisfying ``artemis.ports.VectorStore``.

    Entries are upserted by ``(scope, id)`` so status changes cannot leave stale
    enabled rows behind in retrieval.
    """

    def __init__(self) -> None:
        self._entries: list[_Entry] = []

    def add(
        self,
        scope: str,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None:
        """Store or replace vectors under a scope."""
        if len(ids) != len(vectors) or len(vectors) != len(metadata):
            raise ValueError(
                f"Mismatched lengths: ids={len(ids)}, vectors={len(vectors)}, "
                f"metadata={len(metadata)}"
            )
        for entry_id, vec, meta in zip(ids, vectors, metadata):
            self._entries = [
                entry for entry in self._entries if not (entry[0] == scope and entry[1] == entry_id)
            ]
            norm = self._l2_norm(vec)
            normalised = tuple(x / norm for x in vec) if norm > 0 else tuple(vec)
            self._entries.append((scope, entry_id, normalised, dict(meta)))

    def search(self, scope: str, query: Vector, k: int) -> list[RetrievedChunk]:
        """Return top-k entries within the given scope."""
        query_norm = self._l2_norm(query)
        if query_norm == 0:
            return []
        q = [x / query_norm for x in query]

        scored: list[tuple[float, str, dict[str, object]]] = []
        for entry_scope, entry_id, entry_vec, meta in self._entries:
            if entry_scope != scope:
                continue
            dot = sum(a * b for a, b in zip(q, entry_vec))
            scored.append((dot, entry_id, meta))

        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[RetrievedChunk] = []
        for score, entry_id, meta in scored[:k]:
            chunk = Chunk(
                chunk_id=entry_id,
                document_id=str(meta.get("name", "")),
                text=str(meta.get("text", "")),
                scope=scope,
            )
            results.append(RetrievedChunk(chunk=chunk, score=score))
        return results

    @staticmethod
    def _l2_norm(v: Vector) -> float:
        return math.sqrt(sum(x * x for x in v))


class RecipeStore:
    """Signed file-backed recipe store with an in-memory description index."""

    def __init__(
        self,
        embedder: EmbeddingModel,
        recipes_dir: Path,
        index: VectorStore | None = None,
        signer: RecipeSigner | None = None,
    ) -> None:
        self._embedder = embedder
        self._recipes_dir = recipes_dir
        self._index = index if index is not None else RecipeIndex()
        self._signer = signer

    async def write(self, recipe: Recipe) -> None:
        """Sign, persist atomically, and upsert a recipe description vector."""
        if self._signer is not None:
            recipe.signature = self._signer.sign(recipe)
        self._recipes_dir.mkdir(parents=True, exist_ok=True)
        target = self._path_for(recipe.name, recipe.version)
        temp = target.with_name(f".{target.name}.tmp")
        temp.write_text(recipe.to_skill_md(), encoding="utf-8")
        os.replace(temp, target)

        vec = (await self._embedder.embed_documents([recipe.description]))[0]
        self._index.add(
            scope=_RECIPE_SCOPE,
            ids=[recipe.name],
            vectors=[vec],
            metadata=[
                {
                    "text": recipe.description,
                    "name": recipe.name,
                    "status": recipe.status.value,
                    "action_class": recipe.action_class.value,
                }
            ],
        )

    def get(self, name: str, version: str | None = None) -> Recipe:
        """Load a signed recipe by exact or latest numeric version."""
        path = self._path_for(name, version) if version is not None else self._latest_path(name)
        recipe = Recipe.from_skill_md(path.read_text(encoding="utf-8"))
        self._verify_or_raise(recipe)
        return recipe

    def list(self, *, status: RecipeStatus | None = None) -> list[Recipe]:
        """Return latest-version-per-name recipes, verifying signatures if set."""
        latest: dict[str, Recipe] = {}
        for path in self._recipes_dir.glob("*.skill.md"):
            try:
                recipe = Recipe.from_skill_md(path.read_text(encoding="utf-8"))
                self._verify_or_raise(recipe)
            except RecipeSignatureError:
                logger.warning("Skipping recipe with invalid signature: %s", path.name)
                continue
            if status is not None and recipe.status != status:
                continue
            current = latest.get(recipe.name)
            if current is None or _version_tuple(recipe.version) > _version_tuple(current.version):
                latest[recipe.name] = recipe
        return sorted(latest.values(), key=lambda recipe: recipe.name)

    async def retrieve_recipes(
        self,
        query: str,
        k: int = 3,
        *,
        status: RecipeStatus | None = RecipeStatus.ENABLED,
    ) -> _RecipeNames:
        """Retrieve recipe names by description similarity."""
        vec = await self._embedder.embed_query(query)
        chunks = self._index.search(_RECIPE_SCOPE, vec, max(k, 50))
        names: _RecipeNames = []
        for chunk in chunks:
            try:
                recipe = self.get(chunk.chunk.chunk_id)
            except (KeyError, RecipeSignatureError):
                continue
            if status is not None and recipe.status != status:
                continue
            names.append(recipe.name)
            if len(names) == k:
                break
        return names

    async def set_status(
        self,
        name: str,
        status: RecipeStatus,
        *,
        version: str | None = None,
    ) -> None:
        """Verify, update status, re-sign, and re-index a recipe."""
        recipe = self.get(name, version=version)
        recipe.status = status
        await self.write(recipe)

    def _path_for(self, name: str, version: str) -> Path:
        return self._recipes_dir / f"{name}@{version}.skill.md"

    def _latest_path(self, name: str) -> Path:
        candidates: list[tuple[tuple[int, ...], Path]] = []
        prefix = f"{name}@"
        for path in self._recipes_dir.glob(f"{name}@*.skill.md"):
            stem = path.name
            if not stem.startswith(prefix) or not stem.endswith(".skill.md"):
                continue
            version = stem[len(prefix) : -len(".skill.md")]
            candidates.append((_version_tuple(version), path))
        if not candidates:
            raise KeyError(name)
        candidates.sort(key=lambda item: item[0])
        return candidates[-1][1]

    def _verify_or_raise(self, recipe: Recipe) -> None:
        if self._signer is not None and not self._signer.verify(recipe):
            raise RecipeSignatureError(f"Invalid recipe signature: {recipe.name}@{recipe.version}")


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))
