"""ntfy delivery adapter, dedup store, and quiet-hours hold store."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx

from artemis.config import Settings
from artemis.paths import slot_root
from artemis.proactive.hit_handler import OutboundMessage
from artemis.proactive.hook_types import DeliverySpec
from artemis.proactive.policy import ProactivePolicy

logger = logging.getLogger(__name__)

HttpPost = Callable[..., int]
Priority = Literal["min", "low", "default", "high", "max"]

_URGENCY_PRIORITY: dict[str, Priority] = {"low": "low", "normal": "default", "high": "high"}
_URGENCY_TAG: dict[str, str] = {"low": "memo", "normal": "bell", "high": "warning"}


class DedupStore:
    """Small JSON store for delivered dedup key/value pairs.

    Entries are Tier-0-safe metadata only: key, value, and timestamp. Corrupt or
    absent files are treated as empty to keep the delivery path non-fatal.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        path: Path | None = None,
        now: Callable[[], datetime] = datetime.now,
        ttl: timedelta = timedelta(days=7),
    ) -> None:
        if path is None:
            if settings is None:
                raise ValueError("DedupStore requires settings or path")
            path = _proactive_dir(settings) / "dedup.json"
        self.path = path
        self.now = now
        self.ttl = ttl
        self._entries = self._load()

    def seen(self, dedup_key: str | None, dedup_value: str | None) -> bool:
        """Return true when this key/value pair was previously delivered."""
        if dedup_key is None:
            return False
        self._prune()
        return _dedup_id(dedup_key, dedup_value) in self._entries

    def mark(self, dedup_key: str | None, dedup_value: str | None) -> None:
        """Record a delivered key/value pair and persist atomically."""
        if dedup_key is None:
            return
        self._prune()
        self._entries[_dedup_id(dedup_key, dedup_value)] = {
            "key": dedup_key,
            "value": dedup_value,
            "seen_at": self.now().isoformat(),
        }
        _atomic_json_write(self.path, list(self._entries.values()))

    def _load(self) -> dict[str, dict[str, str | None]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning(
                "proactive dedup store missing or corrupt; starting empty: %s", self.path
            )
            return {}
        if not isinstance(raw, list):
            return {}
        entries: dict[str, dict[str, str | None]] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            seen_at = item.get("seen_at")
            if not isinstance(key, str) or not isinstance(seen_at, str):
                continue
            value_obj = item.get("value")
            value = value_obj if isinstance(value_obj, str) or value_obj is None else str(value_obj)
            entries[_dedup_id(key, value)] = {"key": key, "value": value, "seen_at": seen_at}
        return entries

    def _prune(self) -> None:
        cutoff = self.now() - self.ttl
        self._entries = {
            key: entry
            for key, entry in self._entries.items()
            if _parse_iso(str(entry["seen_at"])) >= cutoff
        }


class NtfyDelivery:
    """Synchronous ``deliver(list[OutboundMessage]) -> int`` sink for HitHandler."""

    def __init__(
        self,
        settings: Settings,
        policy: ProactivePolicy,
        dedup: DedupStore,
        *,
        now: Callable[[], datetime] = datetime.now,
        http_post: HttpPost | None = None,
    ) -> None:
        self.settings = settings
        self.policy = policy
        self.dedup = dedup
        self.now = now
        self.http_post = http_post or _httpx_post
        self.base = ntfy_base_url(settings)
        self.topic = f"artemis-{settings.slot}-{settings.ntfy_topic_secret}"
        self.held_path = _proactive_dir(settings) / "held.json"

    def __call__(self, messages: list[OutboundMessage]) -> int:
        """Publish sendable messages and return the number of 2xx publishes."""
        delivered = 0
        for msg in messages:
            now = self.now()
            decision = self.policy.suppresses(msg, now=now)
            if decision == "drop":
                logger.info("proactive message dropped by policy: %s", msg.source)
                continue
            if decision == "hold" and msg.tier == 0:
                self._hold(msg, now)
                continue

            send_msg = _tier1_quiet_low(msg) if decision == "hold" and msg.tier == 1 else msg
            if self.dedup.seen(send_msg.dedup_key, send_msg.dedup_value):
                logger.info("proactive message deduped: %s", send_msg.source)
                continue
            try:
                status = self._publish(send_msg)
            except Exception:
                logger.exception("ntfy publish failed: %s", send_msg.source)
                continue
            if 200 <= status < 300:
                delivered += 1
                self.dedup.mark(send_msg.dedup_key, send_msg.dedup_value)
            else:
                logger.warning("ntfy publish returned non-2xx: %s", status)
        return delivered

    def flush_held(self) -> None:
        """Deliver non-stale held Tier-0 messages once quiet hours have ended."""
        held = self._load_held()
        if not held:
            return

        now = self.now()
        remaining: list[dict[str, object]] = []
        ready: list[OutboundMessage] = []
        for item in held:
            held_at = _parse_iso(str(item.get("held_at", "")))
            if held_at + timedelta(hours=self.policy.held_ttl_hours) < now:
                continue
            msg = _held_to_message(item)
            if msg.tier == 1:
                continue
            if self.policy.quiet_hours.is_quiet(now):
                remaining.append(item)
            else:
                ready.append(msg)

        _atomic_json_write(self.held_path, remaining)
        if ready:
            self(ready)

    def _publish(self, msg: OutboundMessage) -> int:
        delivery = msg.delivery or DeliverySpec()
        priority = delivery.priority or _URGENCY_PRIORITY[msg.urgency]
        headers = {
            "Title": msg.title,
            "Priority": priority,
            "Tags": ",".join(delivery.tags or [_URGENCY_TAG[msg.urgency]]),
        }
        if delivery.click_url is not None:
            headers["Click"] = delivery.click_url
        actions = _render_actions(delivery.actions)
        if actions:
            headers["Actions"] = actions
        return self.http_post(f"{self.base}/{self.topic}", headers=headers, content=msg.body)

    def _hold(self, msg: OutboundMessage, now: datetime) -> None:
        if msg.tier == 1:
            return
        held = self._load_held()
        held.append(
            {
                "title": msg.title,
                "body": msg.body,
                "urgency": msg.urgency,
                "disposition": msg.disposition,
                "tier": msg.tier,
                "dedup_key": msg.dedup_key,
                "dedup_value": msg.dedup_value,
                "source": msg.source,
                "held_at": now.isoformat(),
            }
        )
        _atomic_json_write(self.held_path, held)

    def _load_held(self) -> list[dict[str, object]]:
        try:
            raw = json.loads(self.held_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning(
                "proactive held store missing or corrupt; starting empty: %s", self.held_path
            )
            return []
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]


def ntfy_base_url(settings: Settings) -> str:
    """Return the local ntfy base URL for the active slot."""
    return f"http://127.0.0.1:{settings.ntfy_port}"


def _render_actions(actions: list[dict[str, str]]) -> str:
    """Render allowed ntfy actions and strip unsafe action URLs."""
    rendered: list[str] = []
    for action in actions:
        url = action.get("url")
        if url is None or not _allowed_action_url(url):
            continue
        kind = action.get("action", "view")
        label = action.get("label", "Open")
        rendered.append(f"{_clean_action_part(kind)}, {_clean_action_part(label)}, {url}")
    return "; ".join(rendered)


def _allowed_action_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme == "artemis":
        return True
    if parsed.scheme != "https":
        return False
    host = parsed.hostname or ""
    return host == "127.0.0.1" or host.endswith(".ts.net")


def _clean_action_part(value: str) -> str:
    return value.replace(",", " ").replace(";", " ").strip()


def _httpx_post(url: str, *, headers: dict[str, str], content: str) -> int:
    response = httpx.post(url, headers=headers, content=content)
    return response.status_code


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


def _dedup_id(key: str, value: str | None) -> str:
    return f"{key}\0{value or ''}"


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min


def _held_to_message(item: dict[str, object]) -> OutboundMessage:
    return OutboundMessage(
        title=str(item["title"]),
        body=str(item["body"]),
        urgency=_literal_urgency(str(item["urgency"])),
        disposition=_literal_disposition(str(item["disposition"])),
        tier=0,
        delivery=None,
        dedup_key=_optional_str(item.get("dedup_key")),
        dedup_value=_optional_str(item.get("dedup_value")),
        source=str(item["source"]),
    )


def _tier1_quiet_low(msg: OutboundMessage) -> OutboundMessage:
    return OutboundMessage(
        title=msg.title,
        body=msg.body,
        urgency="low",
        disposition=msg.disposition,
        tier=msg.tier,
        delivery=msg.delivery,
        dedup_key=msg.dedup_key,
        dedup_value=msg.dedup_value,
        source=msg.source,
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _literal_urgency(value: str) -> Literal["low", "normal", "high"]:
    if value == "high":
        return "high"
    if value == "normal":
        return "normal"
    return "low"


def _literal_disposition(value: str) -> Literal["immediate", "deferrable", "digest"]:
    if value == "immediate":
        return "immediate"
    if value == "digest":
        return "digest"
    return "deferrable"
