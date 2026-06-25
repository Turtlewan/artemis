"""Ask-and-graduate seam for the Ground Rules v1 sensitivity fallback."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from artemis.sensitivity import Sensitivity

logger = logging.getLogger(__name__)


@dataclass
class SensitivityReviewItem:
    """A document queued for owner sensitivity review."""

    source_id: str
    text_preview: str
    proposed_sensitivity: Sensitivity = "sensitive"
    review_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        # Privacy invariant: never persist/return more than a 200-char preview of
        # potentially-sensitive document text. Enforced here, not at call sites.
        self.text_preview = self.text_preview[:200]


class SensitivityReviewQueue:
    """Persists items for owner sensitivity review."""

    def __init__(self, queue_path: Path) -> None:
        self._path = queue_path

    def enqueue(self, item: SensitivityReviewItem) -> None:
        """Add an item to the review queue."""
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "review_id": item.review_id,
                        "source_id": item.source_id,
                        "text_preview": item.text_preview,
                        "proposed_sensitivity": item.proposed_sensitivity,
                    }
                )
                + "\n"
            )

    def pending(self) -> list[SensitivityReviewItem]:
        """Return all pending review items."""
        if not self._path.exists():
            return []
        items: list[SensitivityReviewItem] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            items.append(
                SensitivityReviewItem(
                    source_id=raw["source_id"],
                    text_preview=raw["text_preview"],
                    proposed_sensitivity=raw["proposed_sensitivity"],
                    review_id=raw["review_id"],
                )
            )
        return items


def graduate_to_policy(
    review_id: str,
    sensitivity: Sensitivity,
    policy_path: Path,
) -> None:
    """Record an owner answer as a new ground rule in policy.json."""
    raw: dict[str, object] = {}
    if policy_path.exists():
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
    sens_section = raw.setdefault("sensitivity", {})
    if not isinstance(sens_section, dict):
        raise ValueError("policy.json sensitivity section must be an object")
    overrides = sens_section.setdefault("owner_overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("policy.json sensitivity.owner_overrides must be an object")
    overrides[review_id] = sensitivity
    policy_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    logger.info("graduated review_id=%s to sensitivity=%s", review_id, sensitivity)
