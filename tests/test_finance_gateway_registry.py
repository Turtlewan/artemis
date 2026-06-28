from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.gateway import _register_modules
from artemis.heartbeat import Heartbeat
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ports.types import Vector
from artemis.proactive.hook_types import HookResult
from artemis.registry import ToolRegistry


class FakeEmbedder:
    DIMENSION = 16

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._hash_vec(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._hash_vec(query)

    def _hash_vec(self, text: str) -> Vector:
        vec = [0.0] * self.DIMENSION
        for word in text.lower().split():
            bucket = hashlib.sha256(word.encode()).digest()[0] % self.DIMENSION
            vec[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vec))
        return [value / norm for value in vec] if norm > 0 else vec


def test_live_finance_registry_exposes_hooks_and_read_tools_only(tmp_path: Path) -> None:
    registry = _registry(tmp_path, owner_unlocked=True)

    finance = registry.manifests()["finance"]
    registered = {f"finance.{tool.name}" for tool in finance.tools}

    assert {hook.name for hook in finance.proactive_hooks} == {
        "finance_renewal",
        "finance_new_recurring",
        "finance_bill_due",
        "finance_spending_summary",
    }
    assert registered == {
        "finance.spend_summary",
        "finance.spend_total",
        "finance.transaction_list",
        "finance.transaction_get",
        "finance.category_list",
        "finance.account_list",
        "finance.fin_suggestion_list",
        "finance.subscription_list",
        "finance.bill_list",
        "finance.unusual_spend_list",
    }
    assert all(tool.action_risk.value == "read" for tool in finance.tools)

    write_tools = {
        "finance.transaction_add",
        "finance.transaction_update",
        "finance.transaction_recategorize",
        "finance.category_add",
        "finance.account_add",
        "finance.csv_import",
        "finance.transaction_extract_email",
        "finance.fin_suggestion_accept",
        "finance.fin_suggestion_reject",
        "finance.recurring_scan",
        "finance.reconcile_run",
        "finance.finance_knowledge_push",
    }
    assert write_tools.isdisjoint(registered)
    for fq_name in write_tools:
        with pytest.raises(KeyError):
            registry.get_tool(fq_name)
        with pytest.raises(KeyError):
            registry.get_tool(f"{fq_name}_execute")


def test_heartbeat_tick_evaluates_finance_and_productivity_hooks(tmp_path: Path) -> None:
    key_provider = _key_provider(owner_unlocked=True)
    registry = _registry(tmp_path, owner_unlocked=True)
    calls: list[str] = []

    for module_name in ("finance", "tasks"):
        for hook in registry.manifests()[module_name].proactive_hooks:
            fq_name = f"{module_name}.{hook.name}"

            def check(name: str = fq_name) -> HookResult:
                calls.append(name)
                return HookResult.miss()

            hook.check_ref = check

    wall = datetime(2026, 6, 27, 23, 59)
    heartbeat = Heartbeat(registry, key_provider, wall_clock=lambda: wall)
    heartbeat.note_wake(wall)

    result = heartbeat.tick()

    assert result.hits == ()
    assert {
        "finance.finance_renewal",
        "finance.finance_new_recurring",
        "finance.finance_bill_due",
        "finance.finance_spending_summary",
    } <= set(calls)
    assert any(call.startswith("tasks.") for call in calls)


def test_locked_owner_skips_finance_manifest_without_crashing(tmp_path: Path) -> None:
    key_provider = _key_provider(owner_unlocked=False)
    registry = _register_modules(
        FakeEmbedder(),
        settings=Settings(data_root=tmp_path, slot="dev"),
        key_provider=key_provider,
    )

    assert "finance" not in registry.manifests()
    Heartbeat(registry, key_provider).tick()


def _registry(tmp_path: Path, *, owner_unlocked: bool) -> ToolRegistry:
    return _register_modules(
        FakeEmbedder(),
        settings=Settings(data_root=tmp_path, slot="dev"),
        key_provider=_key_provider(owner_unlocked=owner_unlocked),
    )


def _key_provider(*, owner_unlocked: bool) -> FakeKeyProvider:
    return FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=owner_unlocked)
