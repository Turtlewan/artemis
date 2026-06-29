"""Durable Tier-1 hook queue and drain-on-unlock wiring."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from artemis.config import Settings
from artemis.heartbeat import Heartbeat
from artemis.identity.key_provider import KeyProvider
from artemis.manifest import HookSpec
from artemis.paths import slot_root
from artemis.proactive.hit_handler import HitHandler, OutboundMessage
from artemis.proactive.hook_types import Hit, TickResult
from artemis.proactive.ntfy_delivery import NtfyDelivery
from artemis.registry import ToolRegistry


@dataclass(frozen=True)
class QueuedHook:
    """Persisted Tier-1 hook identity; no result payload is stored."""

    module: str
    hook_name: str
    queued_at: str
    retry_count: int


class Tier1Queue:
    """JSON-backed Tier-1 queue storing only module/hook identities."""

    def __init__(self, settings: Settings | None = None, *, path: Path | None = None) -> None:
        if path is None:
            if settings is None:
                raise ValueError("Tier1Queue requires settings or path")
            path = _proactive_dir(settings) / "tier1_queue.json"
        self.path = path
        self.dead_path = path.with_name("tier1_dead.json")
        self._items = self._load()
        self._lock = threading.Lock()

    def enqueue(self, hit: Hit) -> None:
        """Queue a Tier-1 hook identity, coalescing duplicates by fq hook name."""
        with self._lock:
            key = _queue_key(hit.module, hit.hook_name)
            existing = self._items.get(key)
            if existing is None:
                self._items[key] = QueuedHook(
                    module=hit.module,
                    hook_name=hit.hook_name,
                    queued_at=datetime.now().isoformat(),
                    retry_count=0,
                )
            else:
                self._items[key] = QueuedHook(
                    module=hit.module,
                    hook_name=hit.hook_name,
                    queued_at=existing.queued_at,
                    retry_count=existing.retry_count,
                )
            self._persist()

    def pending(self) -> list[QueuedHook]:
        """Return queued hooks in persisted order."""
        return list(self._items.values())

    def drain(
        self,
        *,
        registry: ToolRegistry,
        key_provider: KeyProvider,
        hit_handler: HitHandler,
        logger: logging.Logger,
        max_attempts: int = 5,
    ) -> int:
        """Run queued Tier-1 hooks while unlocked and remove confirmed deliveries."""
        if not key_provider.is_owner_unlocked():
            return 0
        return _run_blocking(
            self._drain_async(
                registry=registry,
                key_provider=key_provider,
                hit_handler=hit_handler,
                logger=logger,
                max_attempts=max_attempts,
            )
        )

    async def _drain_async(
        self,
        *,
        registry: ToolRegistry,
        key_provider: KeyProvider,
        hit_handler: HitHandler,
        logger: logging.Logger,
        max_attempts: int,
    ) -> int:
        drained = 0
        with self._lock:
            items = list(self._items.values())
        for item in items:
            if not key_provider.is_owner_unlocked():
                return drained
            hook = _resolve_hook(registry, item.module, item.hook_name)
            if hook is None or hook.check_ref is None:
                self._fail(item, logger=logger, max_attempts=max_attempts)
                continue
            try:
                result = hook.check_ref()
            except Exception:
                logger.exception("tier1 queued hook failed: %s.%s", item.module, item.hook_name)
                self._fail(item, logger=logger, max_attempts=max_attempts)
                continue
            if not result.hit:
                self._remove(item)
                continue

            hit = Hit(
                module=item.module,
                hook_name=item.hook_name,
                tier=hook.tier,
                urgency=_literal_urgency(hook.urgency),
                needs_llm=hook.needs_llm,
                dedup_key=hook.dedup_key,
                result=result,
                delivery=hook.delivery,
            )
            delivered = await _handle_with_delivery_count(hit_handler, hit)
            if delivered > 0:
                drained += 1
                self._remove(item)
            else:
                self._fail(item, logger=logger, max_attempts=max_attempts)
        return drained

    def _load(self) -> dict[str, QueuedHook]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            _rename_corrupt(self.path)
            logging.getLogger(__name__).warning(
                "tier1 queue corrupt; starting empty: %s", self.path
            )
            return {}
        if not isinstance(raw, list):
            return {}
        items: dict[str, QueuedHook] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            module = entry.get("module")
            hook_name = entry.get("hook_name")
            queued_at = entry.get("queued_at")
            retry_count = entry.get("retry_count")
            if (
                isinstance(module, str)
                and isinstance(hook_name, str)
                and isinstance(queued_at, str)
                and isinstance(retry_count, int)
            ):
                items[_queue_key(module, hook_name)] = QueuedHook(
                    module=module,
                    hook_name=hook_name,
                    queued_at=queued_at,
                    retry_count=retry_count,
                )
        return items

    def _persist(self) -> None:
        _atomic_json_write(self.path, [asdict(item) for item in self._items.values()])

    def _remove(self, item: QueuedHook) -> None:
        with self._lock:
            self._items.pop(_queue_key(item.module, item.hook_name), None)
            self._persist()

    def _fail(self, item: QueuedHook, *, logger: logging.Logger, max_attempts: int) -> None:
        with self._lock:
            updated = QueuedHook(
                module=item.module,
                hook_name=item.hook_name,
                queued_at=item.queued_at,
                retry_count=item.retry_count + 1,
            )
            if updated.retry_count >= max_attempts:
                self._dead_letter(updated)
                self._items.pop(_queue_key(item.module, item.hook_name), None)
                logger.warning(
                    "tier1 queued hook dead-lettered: %s.%s", item.module, item.hook_name
                )
            else:
                self._items[_queue_key(item.module, item.hook_name)] = updated
            self._persist()

    def _dead_letter(self, item: QueuedHook) -> None:
        existing: list[dict[str, object]]
        try:
            raw = json.loads(self.dead_path.read_text(encoding="utf-8"))
            existing = raw if isinstance(raw, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            existing = []
        existing.append(asdict(item))
        _atomic_json_write(self.dead_path, existing)


def attach_to_heartbeat(
    heartbeat: Heartbeat,
    queue: Tier1Queue,
    ntfy_delivery: NtfyDelivery,
    registry: ToolRegistry,
    key_provider: KeyProvider,
    hit_handler: HitHandler,
    *,
    pre_tick_steps: list[Callable[[], Awaitable[None]]] | None = None,
) -> None:
    """Wire Tier-1 enqueue, held flush, and drain steps into a Heartbeat."""

    async def _flush_step() -> None:
        ntfy_delivery.flush_held()

    async def _drain_step() -> None:
        if key_provider.is_owner_unlocked():
            queue.drain(
                registry=registry,
                key_provider=key_provider,
                hit_handler=hit_handler,
                logger=logging.getLogger(__name__),
                max_attempts=ntfy_delivery.policy.max_drain_attempts,
            )

    heartbeat._tier1_sink = queue.enqueue
    heartbeat.pre_tick_steps = [_flush_step, _drain_step] + list(pre_tick_steps or [])


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


def _rename_corrupt(path: Path) -> None:
    if not path.exists():
        return
    corrupt_path = path.with_name(f"{path.name}.corrupt.{datetime.now().strftime('%Y%m%d%H%M%S')}")
    try:
        os.replace(path, corrupt_path)
    except OSError:
        logging.getLogger(__name__).warning("failed to rename corrupt tier1 queue: %s", path)


def _resolve_hook(registry: ToolRegistry, module: str, hook_name: str) -> HookSpec | None:
    manifest = registry.manifests().get(module)
    if manifest is None:
        return None
    for hook in manifest.proactive_hooks:
        if hook.name == hook_name:
            return hook
    return None


async def _handle_with_delivery_count(hit_handler: HitHandler, hit: Hit) -> int:
    delivered = 0
    original = hit_handler.deliver

    def _counting_deliver(messages: list[OutboundMessage]) -> int:
        nonlocal delivered
        count = original(messages)
        delivered += count
        return count

    hit_handler.deliver = _counting_deliver
    try:
        tick = TickResult(hits=(hit,), summary="1 hit(s)", tier1_skipped=())
        await hit_handler.handle(tick)
    finally:
        hit_handler.deliver = original
    return delivered


def _run_blocking(coro: Coroutine[Any, Any, int]) -> int:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: int | None = None
    error: BaseException | None = None

    def _runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:
            error = exc

    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    if result is None:
        raise RuntimeError("tier1 drain did not produce a result")
    return result


def _queue_key(module: str, hook_name: str) -> str:
    return f"{module}.{hook_name}"


def _literal_urgency(value: str) -> Literal["low", "normal", "high"]:
    if value == "high":
        return "high"
    if value == "low":
        return "low"
    return "normal"
