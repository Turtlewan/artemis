from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.finance import FinanceStore


def test_get_bill_returns_row_with_linked_task_ref_and_none_for_missing(tmp_path: Path) -> None:
    store = FinanceStore(
        Settings(data_root=tmp_path),
        FakeKeyProvider({OWNER_PRIVATE: b"f" * 32}, owner_unlocked=True),
    )
    bill_id = store.upsert_bill(
        payee="Utility Co",
        due_date="2026-07-01",
        amount=Decimal("100.00"),
        raw_ref="bill-1",
    )
    store._get_conn().execute(
        "UPDATE bill SET linked_task_ref = ? WHERE id = ?",
        ("tasks:task:task-bill-1", bill_id),
    )
    store._get_conn().commit()

    bill = store.get_bill(bill_id)

    assert bill is not None
    assert bill["id"] == bill_id
    assert bill["linked_task_ref"] == "tasks:task:task-bill-1"
    assert store.get_bill("missing") is None
