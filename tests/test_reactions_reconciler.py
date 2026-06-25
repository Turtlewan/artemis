from __future__ import annotations

from decimal import Decimal

from artemis.reactions.reconciler import (
    EntityRef,
    LinkPair,
    MatchOutcome,
    Reconciler,
    ReconcileRecord,
    normalize_merchant,
    sweep_link_integrity,
)


def _record(
    id: str,
    *,
    amount: str = "12.50",
    date: str = "2026-06-25",
    merchant: str = "NTUC FairPrice",
    currency: str = "SGD",
) -> ReconcileRecord:
    return ReconcileRecord(
        id=id,
        amount=Decimal(amount),
        currency=currency,
        date=date,
        merchant=merchant,
    )


def test_exact_auto_merge_single_candidate() -> None:
    reconciler = Reconciler(date_window_days=1, amount_exact=True)

    result = reconciler.match(_record("target"), [_record("candidate")])

    assert result.outcome is MatchOutcome.EXACT
    assert result.matched_id == "candidate"
    assert result.score == 1.0


def test_tie_is_ambiguous_without_auto_pick() -> None:
    reconciler = Reconciler(date_window_days=1, amount_exact=True)

    result = reconciler.match(_record("target"), [_record("first"), _record("second")])

    assert result.outcome is MatchOutcome.AMBIGUOUS
    assert result.matched_id is None


def test_partial_same_merchant_amount_off_is_ambiguous() -> None:
    reconciler = Reconciler(date_window_days=1, amount_exact=True)

    result = reconciler.match(_record("target"), [_record("candidate", amount="13.00")])

    assert result.outcome is MatchOutcome.AMBIGUOUS
    assert result.matched_id == "candidate"


def test_out_of_window_is_none() -> None:
    reconciler = Reconciler(date_window_days=1, amount_exact=True)

    result = reconciler.match(_record("target"), [_record("candidate", date="2026-06-20")])

    assert result.outcome is MatchOutcome.NONE
    assert result.matched_id is None


def test_recurring_monthly_charge_is_not_duplicate_outside_window() -> None:
    reconciler = Reconciler(date_window_days=1, amount_exact=True)

    result = reconciler.match(_record("target"), [_record("candidate", date="2026-05-25")])

    assert result.outcome is MatchOutcome.NONE


def test_merchant_normalization_drops_suffix_punctuation_and_store_numbers() -> None:
    assert normalize_merchant("NTUC FairPrice #123  PTE LTD") == normalize_merchant(
        "ntuc fairprice"
    )
    assert normalize_merchant("NTUC #123 PTE LTD") == normalize_merchant("NTUC")


def test_amount_tolerance_path_can_auto_merge_when_amount_exact_false() -> None:
    reconciler = Reconciler(
        date_window_days=1,
        amount_exact=False,
        amount_tol=Decimal("0.10"),
    )

    result = reconciler.match(_record("target"), [_record("candidate", amount="12.55")])

    assert result.outcome is MatchOutcome.EXACT
    assert result.matched_id == "candidate"


def test_link_sweep_repairs_deterministic_half_link() -> None:
    repaired: list[LinkPair] = []
    flagged: list[LinkPair] = []
    pair = LinkPair(
        kind="task-calendar",
        left_ref=EntityRef(module="tasks", id="task-1"),
        right_ref=None,
        deterministic=True,
    )

    report = sweep_link_integrity(
        link_pairs=[pair],
        repair_fn=repaired.append,
        flag_fn=flagged.append,
    )

    assert repaired == [pair]
    assert flagged == []
    assert report.repaired == ("task-calendar:tasks:task-1->missing",)
    assert report.flagged == ()
    assert report.checked == 1


def test_link_sweep_flags_fuzzy_half_link() -> None:
    repaired: list[LinkPair] = []
    flagged: list[LinkPair] = []
    pair = LinkPair(
        kind="bill-payment",
        left_ref="finance:bill-1",
        right_ref=None,
        deterministic=False,
    )

    report = sweep_link_integrity(
        link_pairs=[pair],
        repair_fn=repaired.append,
        flag_fn=flagged.append,
    )

    assert repaired == []
    assert flagged == [pair]
    assert report.repaired == ()
    assert report.flagged == ("bill-payment:finance:bill-1->missing",)
    assert report.checked == 1


def test_link_sweep_clean_pair_calls_neither_callback() -> None:
    repaired: list[LinkPair] = []
    flagged: list[LinkPair] = []
    pair = LinkPair(
        kind="task-calendar",
        left_ref=EntityRef(module="tasks", id="task-1"),
        right_ref=EntityRef(module="calendar", id="event-1"),
        deterministic=True,
    )

    report = sweep_link_integrity(
        link_pairs=[pair],
        repair_fn=repaired.append,
        flag_fn=flagged.append,
    )

    assert repaired == []
    assert flagged == []
    assert report.repaired == ()
    assert report.flagged == ()
    assert report.checked == 1
