from __future__ import annotations

from artemis.sensitivity_detectors import (
    exceeds_masked_tail,
    has_dob,
    has_full_card_number,
    has_home_address,
    has_nric,
    is_content_sensitive,
)


def test_has_full_card_number_detects_luhn_valid_plain_and_spaced() -> None:
    assert has_full_card_number("card 4111111111111111")
    assert has_full_card_number("card 4111 1111 1111 1111")
    assert not has_full_card_number("card 4111111111111112")
    assert not has_full_card_number("card •••• 1234")


def test_exceeds_masked_tail_allows_only_last_four() -> None:
    assert exceeds_masked_tail("account 12345678901234")
    assert not exceeds_masked_tail("account •••• 1234")


def test_has_nric_validates_checksum() -> None:
    assert has_nric("S1234567D")
    assert not has_nric("S1234567A")


def test_has_dob_requires_dob_shape_or_context() -> None:
    assert has_dob("Date of birth: 01/01/1990")
    assert has_dob("born on 1990-01-01")
    assert not has_dob("2026-06-25")


def test_has_home_address_detects_common_address_shapes() -> None:
    assert has_home_address("123 Orchard Road")
    assert has_home_address("Blk 456 Jurong West")
    assert not has_home_address("hello world")


def test_is_content_sensitive_combines_detectors() -> None:
    assert is_content_sensitive("card 4111111111111111")
    assert not is_content_sensitive("clean text with no private identifiers")
