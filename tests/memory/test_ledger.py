from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from artemis.memory import MemoryLedger, decay_rank


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance_days(self, days: float) -> None:
        self.value += days * 86400.0


def _ledger_rows(
    ledger: MemoryLedger,
    key: str,
) -> Sequence[tuple[float, float, int, float, int]]:
    return cast(
        Sequence[tuple[float, float, int, float, int]],
        ledger._conn.execute(
            "SELECT first_seen, last_access, access_count, salience, archived "
            "FROM facts WHERE key=?",
            (key,),
        ).fetchall(),
    )


def test_decay_rank_is_monotonic_for_recency_access_and_salience() -> None:
    fresh = decay_rank(age_days=0.0, access_count=1, salience=1.0)
    old = decay_rank(age_days=60.0, access_count=1, salience=1.0)
    more_accessed = decay_rank(age_days=0.0, access_count=2, salience=1.0)
    more_salient = decay_rank(age_days=0.0, access_count=1, salience=2.0)

    assert fresh > old
    assert more_accessed > fresh
    assert more_salient > fresh


def test_record_and_touch_bumps_access_without_duplicate_record() -> None:
    clock = FakeClock(100.0)
    ledger = MemoryLedger(now=clock)

    ledger.record("k", salience=0.5)
    clock.advance_days(1.0)
    ledger.record("k", salience=0.9)
    ledger.touch(["k"])

    rows = _ledger_rows(ledger, "k")
    assert rows == [(100.0, 86500.0, 1, 0.5, 0)]


def test_decay_archives_old_and_low_salience_facts_only() -> None:
    clock = FakeClock()
    ledger = MemoryLedger(now=clock)

    ledger.record("old")
    clock.advance_days(99.0)
    ledger.record("young")
    clock.advance_days(1.0)

    assert ledger.decay(max_age_days=30.0, min_salience=None) == ["old"]
    assert ledger.archived_keys() == {"old"}

    ledger.record("low", salience=0.1)
    ledger.record("normal", salience=1.0)

    assert ledger.decay(max_age_days=None, min_salience=0.5) == ["low"]
    assert ledger.archived_keys() == {"old", "low"}
