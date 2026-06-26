from __future__ import annotations

import datetime
import inspect
from decimal import Decimal
from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.finance.hooks import (
    build_finance_hooks,
    make_bill_due_check,
    make_new_recurring_check,
    make_renewal_check,
    make_spending_summary_check,
)
from artemis.modules.finance.manifest import finance_manifest
from artemis.modules.finance.store import FinanceStore
from artemis.ports.types import Scope
from artemis.proactive.hit_handler import TemplateRegistry


class FakeKeyProvider:
    def __init__(self, *, owner_unlocked: bool = True) -> None:
        self.owner_unlocked = owner_unlocked

    def dek_for_scope(self, scope: Scope) -> SecretKey:
        if scope != OWNER_PRIVATE or not self.owner_unlocked:
            raise ScopeLockedError(f"Scope is locked: {scope}")
        return SecretKey(b"f" * 32)

    def is_owner_unlocked(self) -> bool:
        return self.owner_unlocked


@pytest.fixture
def store(tmp_path: Path) -> FinanceStore:
    return FinanceStore(Settings(data_root=tmp_path), FakeKeyProvider())


def test_hooks_miss_empty_store(store: FinanceStore) -> None:
    assert not make_renewal_check(store)().hit
    assert not make_new_recurring_check(store)().hit
    assert not make_bill_due_check(store)().hit
    assert not make_spending_summary_check(store)().hit


def test_hooks_hit_with_count_id_scalar_payloads(store: FinanceStore) -> None:
    anchor = datetime.datetime.now(datetime.UTC).date()
    today = anchor.isoformat()
    subscription_id = store.upsert_subscription(
        merchant="Music Box",
        cadence="monthly",
        amount=Decimal("10.00"),
        next_renewal=today,
        last_seen_price=Decimal("12.00"),
        last_seen_date=today,
    )
    suggestion_id = store.create_fin_suggestion(
        "new_recurring",
        '{"merchant":"Video","amount":"9.99"}',
    )
    bill_id = store.upsert_bill(payee="Power", due_date=today, amount=Decimal("88.00"))
    account_id = store.create_account("Card", "card")
    for index, amount in enumerate(("10.00", "11.00", "9.00", "10.50", "60.00"), start=1):
        txn_date = (anchor - datetime.timedelta(days=6 - index)).isoformat()
        store.add_transaction(
            txn_date=txn_date,
            amount=Decimal(amount),
            merchant="Lunch",
            source="manual",
            instrument_account_id=account_id,
            raw_ref=f"hook:lunch:{index}",
        )

    renewal = make_renewal_check(store)()
    new_recurring = make_new_recurring_check(store)()
    bill_due = make_bill_due_check(store)()
    spending = make_spending_summary_check(store)()

    assert renewal.hit
    assert renewal.payload == {
        "renewing_count": 1,
        "price_increase_count": 1,
        "subscription_ids": [subscription_id],
    }
    assert new_recurring.hit
    assert new_recurring.payload == {
        "new_recurring_count": 1,
        "suggestion_ids": [suggestion_id],
    }
    assert bill_due.hit
    assert bill_due.payload == {"due_count": 1, "bill_ids": [bill_id]}
    assert spending.hit
    assert set(spending.payload) == {
        "period_total",
        "top_category",
        "unusual_count",
        "unusual_txn_ids",
    }
    for result in (renewal, new_recurring, bill_due, spending):
        assert _payload_is_counts_ids_scalars(result.payload)


def test_build_hooks_and_manifest_validate(tmp_path: Path) -> None:
    registry = TemplateRegistry()
    store = FinanceStore(Settings(data_root=tmp_path), FakeKeyProvider())

    hooks = build_finance_hooks(store)
    manifest = finance_manifest(store, registry=registry)

    assert len(hooks) == 4
    assert len(manifest.proactive_hooks) == 4
    assert all(hook.tier == 1 for hook in manifest.proactive_hooks)
    assert [hook.needs_llm for hook in manifest.proactive_hooks] == [False, False, False, True]
    assert (
        registry.render("finance.finance_bill_due", make_bill_due_check(store)())
        == "0 bills due soon"
    )
    assert all(inspect.iscoroutinefunction(tool.callable_ref) for tool in manifest.tools)
    assert {
        "subscription_list",
        "bill_list",
        "recurring_scan",
        "reconcile_run",
        "unusual_spend_list",
    } <= {tool.name for tool in manifest.tools}


def test_scope_locked_degrades_to_miss(tmp_path: Path) -> None:
    locked = FinanceStore(Settings(data_root=tmp_path), FakeKeyProvider(owner_unlocked=False))

    assert not make_renewal_check(locked)().hit
    assert not make_new_recurring_check(locked)().hit
    assert not make_bill_due_check(locked)().hit
    assert not make_spending_summary_check(locked)().hit


def test_finance_package_has_no_external_model_imports() -> None:
    finance_dir = Path(__file__).parents[1] / "src" / "artemis" / "modules" / "finance"
    combined = "\n".join(path.read_text() for path in finance_dir.glob("*.py"))

    assert "model_adapters" not in combined
    assert "Codex" not in combined
    assert "responder_cloud" not in combined
    assert "from artemis.reactions.emit import EventBus" not in combined


def _payload_is_counts_ids_scalars(payload: dict[str, object]) -> bool:
    for value in payload.values():
        if isinstance(value, list):
            if not all(isinstance(item, str) for item in value):
                return False
            continue
        if not isinstance(value, (str, int, float, bool)):
            return False
    return True
