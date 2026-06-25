"""Deterministic sensitivity detectors for the Ground Rules v1 content layer.

These detectors run BEFORE the local classifier and catch the highest-value
items (full card numbers, government IDs, DOB, home address) with code that
cannot be prompt-injected. The classifier is the backstop for nuance.

All functions accept a plain str and return bool (True = sensitive signal found).
"""

from __future__ import annotations

import re


def _luhn_check(digits: str) -> bool:
    """Return True if the digit string passes the Luhn checksum."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


_CARD_STRIP_RE = re.compile(r"[\s\-]")
_CARD_DIGITS_RE = re.compile(r"\d{13,19}")


def has_full_card_number(text: str) -> bool:
    """True if text contains a Luhn-valid card-length digit sequence."""
    stripped = _CARD_STRIP_RE.sub("", text)
    for match in _CARD_DIGITS_RE.finditer(stripped):
        if _luhn_check(match.group()):
            return True
    return False


_MASKED_TAIL_RE = re.compile(r"[•*Xx]{2,}\s*(\d{4})")
_BARE_ACCT_RE = re.compile(r"\b\d{5,}\b")


def exceeds_masked_tail(text: str) -> bool:
    """True if text exposes more than the last-4 digits of an account/card number."""
    masked_spans = [match.span(1) for match in _MASKED_TAIL_RE.finditer(text)]
    for match in _BARE_ACCT_RE.finditer(text):
        if not any(start <= match.start() and match.end() <= end for start, end in masked_spans):
            return True
    return False


_NRIC_RE = re.compile(r"\b([STFGM])(\d{7})([A-Z])\b", re.IGNORECASE)
_NRIC_ST_WEIGHTS = (2, 7, 6, 5, 4, 3, 2)
_NRIC_ST_LETTERS = "JZIHGFEDCBA"
_NRIC_FG_LETTERS = "XWUTRQPNMLK"
_NRIC_M_LETTERS = "XWUTRQPNMLK"


def _nric_valid(prefix: str, digits: str, check: str) -> bool:
    prefix = prefix.upper()
    check = check.upper()
    total = sum(int(digit) * weight for digit, weight in zip(digits, _NRIC_ST_WEIGHTS))
    if prefix in ("S", "T"):
        if prefix == "T":
            total += 4
        letters = _NRIC_ST_LETTERS
    elif prefix in ("F", "G"):
        if prefix == "G":
            total += 4
        letters = _NRIC_FG_LETTERS
    elif prefix == "M":
        total += 3
        letters = _NRIC_M_LETTERS
    else:
        return False
    return letters[total % 11] == check


def has_nric(text: str) -> bool:
    """True if text contains a structurally valid Singapore NRIC/FIN number."""
    for match in _NRIC_RE.finditer(text):
        if _nric_valid(match.group(1), match.group(2), match.group(3)):
            return True
    return False


_DOB_RE = re.compile(
    r"\b(?:"
    r"(?:date of birth|dob|born on|birthday)[:\s]*"
    r"(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{2}[/\-\.]\d{2})"
    r"|"
    r"(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})"
    r")\b",
    re.IGNORECASE,
)


def has_dob(text: str) -> bool:
    """True if text contains a date-of-birth pattern."""
    return bool(_DOB_RE.search(text))


_ADDRESS_RE = re.compile(
    r"\b(?:"
    r"\d{1,5}\s+\w[\w\s]{1,30}(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|"
    r"close|crescent|place|pl|way|blvd|boulevard|terrace|terr|court|ct)"
    r"|"
    r"(?:blk|block)\s*\d{1,5}[a-z]?\s+\w[\w\s]{1,40}"
    r")\b",
    re.IGNORECASE,
)


def has_home_address(text: str) -> bool:
    """True if text contains a home address pattern."""
    return bool(_ADDRESS_RE.search(text))


def is_content_sensitive(text: str) -> bool:
    """True if any deterministic detector fires on the text."""
    return (
        has_full_card_number(text)
        or exceeds_masked_tail(text)
        or has_nric(text)
        or has_dob(text)
        or has_home_address(text)
    )
