"""Curiosity loop orchestration, token ledger, and owner-gated staging."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from artemis.curiosity.gaps import Gap, TelemetrySource, pick_top_gap, scan_gaps
from artemis.curiosity.research import Reachability, Researcher, Source, grounding_gate
from artemis.obs import get_logger
from artemis.ports import ModelPort
from artemis.recipes.model import ActionClass, Recipe, RecipeClass, RecipeStatus
from artemis.recipes.store import RecipeStore

logger = get_logger("curiosity.loop")


@dataclass(frozen=True)
class StagedItem:
    """Owner-reviewed item produced by Curiosity but not yet live."""

    item_id: str
    kind: Literal["recipe", "chunk"]
    summary: str
    payload: dict[str, object]
    gap: str
    sources: list[str]


@dataclass(frozen=True)
class _TokenEntry:
    at: datetime
    tokens: int


class TokenLedger:
    """JSON token ledger enforcing hard per-cycle and rolling weekly caps."""

    def __init__(self, path: Path, per_cycle_cap: int, weekly_cap: int) -> None:
        self._path = path
        self._per_cycle_cap = per_cycle_cap
        self._weekly_cap = weekly_cap
        self._cycle_spent = 0

    def remaining_this_cycle(self) -> int:
        """Return remaining token headroom for the current process-local cycle."""

        return max(0, self._per_cycle_cap - self._cycle_spent)

    def begin_cycle(self) -> None:
        """Reset process-local per-cycle spend before a new Curiosity tick."""

        self._cycle_spent = 0

    def remaining_this_week(self, now: datetime) -> int:
        """Return remaining rolling seven-day token headroom."""

        cutoff = now - timedelta(days=7)
        spent = sum(entry.tokens for entry in self._entries() if entry.at >= cutoff)
        return max(0, self._weekly_cap - spent)

    def record(self, tokens: int, now: datetime) -> None:
        """Persist a token spend entry atomically in the same directory."""

        if tokens < 0:
            raise ValueError("tokens must be non-negative")
        self._cycle_spent += tokens
        entries = self._entries()
        entries.append(_TokenEntry(at=now, tokens=tokens))
        self._write_entries(entries)

    def can_spend(self, now: datetime) -> bool:
        """Return True iff both hard token caps have headroom."""

        return self.remaining_this_cycle() > 0 and self.remaining_this_week(now) > 0

    def _entries(self) -> list[_TokenEntry]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("token ledger must contain a JSON list")
        entries: list[_TokenEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("token ledger entry must be an object")
            at = item.get("at")
            tokens = item.get("tokens")
            if not isinstance(at, str) or not isinstance(tokens, int):
                raise ValueError("token ledger entry has invalid fields")
            entries.append(_TokenEntry(at=datetime.fromisoformat(at), tokens=tokens))
        return entries

    def _write_entries(self, entries: list[_TokenEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serialised = [{"at": entry.at.isoformat(), "tokens": entry.tokens} for entry in entries]
        temp = self._path.with_name(f".{self._path.name}.tmp")
        temp.write_text(json.dumps(serialised, sort_keys=True), encoding="utf-8")
        os.replace(temp, self._path)


class StagingStore:
    """Atomic JSON store for Curiosity items awaiting owner action."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def stage(self, item: StagedItem) -> None:
        """Add or replace one staged item."""

        items = {existing.item_id: existing for existing in self.list()}
        items[item.item_id] = item
        self._write_items(list(items.values()))

    def list(self) -> list[StagedItem]:
        """Return all staged items."""

        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("staging store must contain a JSON list")
        items: list[StagedItem] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("staged item must be an object")
            items.append(
                StagedItem(
                    item_id=str(item["item_id"]),
                    kind=cast(Literal["recipe", "chunk"], item["kind"]),
                    summary=str(item["summary"]),
                    payload=cast(dict[str, object], item["payload"]),
                    gap=str(item["gap"]),
                    sources=[str(source) for source in cast(list[object], item["sources"])],
                )
            )
        return items

    def get(self, item_id: str) -> StagedItem:
        """Return a staged item by id."""

        for item in self.list():
            if item.item_id == item_id:
                return item
        raise KeyError(item_id)

    def remove(self, item_id: str) -> None:
        """Remove a staged item by id."""

        items = [item for item in self.list() if item.item_id != item_id]
        self._write_items(items)

    def _write_items(self, items: Sequence[StagedItem]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_name(f".{self._path.name}.tmp")
        temp.write_text(
            json.dumps([asdict(item) for item in items], sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temp, self._path)


class CuriosityLoop:
    """Idle-only Curiosity cycle that stages grounded results for owner commit."""

    def __init__(
        self,
        telemetry: TelemetrySource,
        researcher: Researcher,
        reachability: Reachability,
        model: ModelPort,
        recipe_store: RecipeStore,
        ledger: TokenLedger,
        staging: StagingStore,
    ) -> None:
        self._telemetry = telemetry
        self._researcher = researcher
        self._reachability = reachability
        self._model = model
        self._recipe_store = recipe_store
        self._ledger = ledger
        self._staging = staging

    async def curiosity_tick(self, *, is_idle: Callable[[], bool], now: datetime) -> str:
        """Run one non-raising idle Curiosity cycle and return a typed status."""

        try:
            self._ledger.begin_cycle()
            if not is_idle() or not self._ledger.can_spend(now):
                return "CURIOSITY_SKIP"

            gap = pick_top_gap(scan_gaps(self._telemetry, now=now))
            if gap is None:
                return "CURIOSITY_NO_GAP"

            query = _research_query(gap)
            token_cap = min(
                self._ledger.remaining_this_cycle(),
                self._ledger.remaining_this_week(now),
            )
            result = await self._researcher.research(
                query,
                token_cap=token_cap,
            )
            self._ledger.record(result.token_usage, now)

            if not grounding_gate(result, self._reachability):
                return "CURIOSITY_UNGROUNDED"

            self._staging.stage(
                _stage_recipe(gap=gap, content=result.content, sources=result.sources)
            )
            return "CURIOSITY_STAGED"
        except Exception:
            logger.exception("Curiosity tick failed")
            return "CURIOSITY_ERROR"

    def staged_for_digest(self) -> list[StagedItem]:
        """Return staged Curiosity items for owner review surfaces."""

        return self._staging.list()

    async def commit_staged(self, item_id: str) -> None:
        """Owner action: write a staged recipe candidate or reject raw chunk bypass."""

        item = self._staging.get(item_id)
        if item.kind == "chunk":
            raise NotImplementedError("Curiosity chunk ingest awaits the M3 ingest hook")
        recipe = _recipe_from_payload(item.payload)
        await self._recipe_store.write(recipe)
        self._staging.remove(item_id)

    def discard_staged(self, item_id: str) -> None:
        """Owner action: drop a staged item without writing it live."""

        self._staging.remove(item_id)


def _research_query(gap: Gap) -> str:
    return (
        "Research an Artemis improvement for "
        f"{gap.task_class_key} ({gap.kind}, evidence={gap.evidence_count})."
    )


def _stage_recipe(*, gap: Gap, content: str, sources: Sequence[Source]) -> StagedItem:
    source_urls = [source.url for source in sources]
    name = _recipe_name(gap.task_class_key)
    payload: dict[str, object] = {
        "name": name,
        "description": f"Curiosity candidate for {gap.task_class_key}",
        "version": "1.0.0",
        "recipe_class": RecipeClass.INSTRUCTIONS.value,
        "action_class": ActionClass.READ_ONLY.value,
        "task_class_key": gap.task_class_key,
        "inputs_schema": {"type": "object", "additionalProperties": True},
        "outputs_schema": {"type": "object", "additionalProperties": True},
        "instructions": content,
        "script": None,
        "status": RecipeStatus.CANDIDATE.value,
        "provenance": {
            "source": "curiosity",
            "gap_kind": gap.kind,
            "sources": "\n".join(source_urls),
        },
    }
    return StagedItem(
        item_id=f"curiosity-{uuid4().hex}",
        kind="recipe",
        summary=f"{gap.kind}: {gap.task_class_key}",
        payload=payload,
        gap=gap.task_class_key,
        sources=source_urls,
    )


def _recipe_from_payload(payload: dict[str, object]) -> Recipe:
    return Recipe(
        name=str(payload["name"]),
        description=str(payload["description"]),
        version=str(payload["version"]),
        recipe_class=RecipeClass(str(payload["recipe_class"])),
        action_class=ActionClass(str(payload["action_class"])),
        task_class_key=str(payload["task_class_key"]),
        inputs_schema=cast(dict[str, object], payload["inputs_schema"]),
        outputs_schema=cast(dict[str, object], payload["outputs_schema"]),
        instructions=str(payload["instructions"]),
        script=cast(str | None, payload["script"]),
        status=RecipeStatus.CANDIDATE,
        provenance=cast(dict[str, str], payload["provenance"]),
    )


def _recipe_name(task_class_key: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in task_class_key.lower())
    cleaned = cleaned.strip("_") or "gap"
    if not cleaned[0].isalpha():
        cleaned = f"gap_{cleaned}"
    return f"curiosity_{cleaned}"[:80].rstrip("_")
