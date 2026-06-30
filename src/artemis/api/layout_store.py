"""Session-gated app layout persistence outside the encrypted vault."""

from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class CardPlacement(BaseModel):
    """One card's position in the Artemis client map."""

    model_config = ConfigDict(extra="forbid")

    id: str
    domain: str
    cluster: str
    x: int
    y: int
    w: int
    h: int


class LayoutDTO(BaseModel):
    """Client map layout DTO persisted as identity-scope JSON."""

    model_config = ConfigDict(extra="forbid")

    version: int
    updated_at: datetime
    cards: list[CardPlacement]


def default_layout() -> LayoutDTO:
    """Empty seed: the brain has no layout opinion until the owner drags a card.

    The client treats an empty card list as "use my canonical seed" (`world/clusters.ts`
    `defaultPlacements`, 250x150 cards positioned around the core), so the brain must NOT ship
    placeholder coordinates — the client reads x/y/w/h as raw pixels and would render tiny clumped
    cards. Once the owner repositions a card, the client PUTs the real layout and it persists here.
    """
    return LayoutDTO(version=1, updated_at=datetime.now(UTC), cards=[])


class LayoutStore:
    """Atomic JSON layout store readable while the owner vault is locked."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self) -> LayoutDTO | None:
        """Return the stored layout, or None when no valid layout exists."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            return LayoutDTO.model_validate_json(raw)
        except ValueError:
            return None

    def put(self, layout: LayoutDTO) -> LayoutDTO:
        """Persist ``layout`` only if it wins the last-writer-wins timestamp check."""
        stored = self.get()
        if stored is not None and layout.updated_at <= stored.updated_at:
            return stored
        accepted = layout.model_copy(update={"updated_at": datetime.now(UTC)})
        self._write(accepted)
        return accepted

    def _write(self, layout: LayoutDTO) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp_path = self._path.with_name(f".{self._path.name}.{secrets.token_hex(8)}.tmp")
        temp_path.write_text(
            json.dumps(layout.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        os.replace(temp_path, self._path)
