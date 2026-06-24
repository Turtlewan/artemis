"""Owner-tunable proactive notification policy.

The policy file lives at ``<slot>/proactive/policy.json`` and is intended to be
owner-editable. It controls noise reduction only: security-sensitive tiering is
enforced earlier by the heartbeat and Tier-1 queue.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from artemis.config import Settings
from artemis.paths import slot_root
from artemis.proactive.hit_handler import OutboundMessage

logger = logging.getLogger(__name__)

Urgency = Literal["low", "normal", "high"]
Decision = Literal["send", "hold", "drop"]
Disposition = Literal["immediate", "deferrable", "digest"]

_URGENCY_RANK: dict[Urgency, int] = {"low": 0, "normal": 1, "high": 2}


def _default_hold_dispositions() -> list[Disposition]:
    return ["deferrable", "digest"]


class QuietHours(BaseModel):
    """Local quiet-hours window for delaying lower-priority notifications."""

    start: str = "22:00"
    end: str = "07:00"
    hold_dispositions: list[Disposition] = Field(default_factory=_default_hold_dispositions)

    def is_quiet(self, now: datetime) -> bool:
        """Return true when ``now`` falls inside the configured local window."""
        start = _parse_hhmm(self.start)
        end = _parse_hhmm(self.end)
        current = now.time().replace(second=0, microsecond=0)
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end


class ProactivePolicy(BaseModel):
    """Typed owner policy for proactive delivery decisions."""

    muted: bool = False
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    module_min_urgency: dict[str, Urgency] = Field(default_factory=dict)
    min_urgency_global: Urgency = "low"
    held_ttl_hours: int = 8
    max_drain_attempts: int = 5

    def suppresses(self, msg: OutboundMessage, *, now: datetime) -> Decision:
        """Classify a message as send, hold, or drop under this policy."""
        if self.muted:
            return "drop"
        if _URGENCY_RANK[msg.urgency] < _URGENCY_RANK[self.min_urgency_global]:
            return "drop"
        module_floor = self.module_min_urgency.get(msg.source.split(".", 1)[0])
        if module_floor is not None and _URGENCY_RANK[msg.urgency] < _URGENCY_RANK[module_floor]:
            return "drop"
        if self.quiet_hours.is_quiet(now) and msg.disposition in self.quiet_hours.hold_dispositions:
            return "hold"
        return "send"


def load_policy(settings: Settings) -> ProactivePolicy:
    """Load the owner-editable policy, returning defaults when absent/corrupt."""
    path = _policy_path(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ProactivePolicy()
    except json.JSONDecodeError:
        logger.warning("proactive policy is corrupt; using defaults: %s", path)
        return ProactivePolicy()
    return ProactivePolicy.model_validate(raw)


def save_policy(settings: Settings, policy: ProactivePolicy) -> None:
    """Atomically save the owner-editable proactive policy."""
    path = _policy_path(settings)
    _atomic_json_write(path, policy.model_dump(mode="json"))


def _policy_path(settings: Settings) -> Path:
    return _proactive_dir(settings) / "policy.json"


def _proactive_dir(settings: Settings) -> Path:
    path = slot_root(settings) / "proactive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_json_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            tmp_name = tmp.name
            json.dump(payload, tmp, indent=2, sort_keys=True)
            tmp.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
        raise


def _parse_hhmm(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))
