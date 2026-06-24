"""Quarantine-first finance extraction from Gmail messages.

The extractor admits candidate messages via an allowlist or deterministic
receipt-keywords, reads raw email through ``QuarantinedReader`` first, then asks
the local sensitive reasoner to extract bounded transaction facts from the safe
``Extract`` only.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from email.utils import parseaddr
from typing import cast

from artemis.modules.finance.schema import TransactionSource, TransactionType
from artemis.modules.finance.store import FinanceStore
from artemis.modules.gmail.cache import CachedMessage
from artemis.modules.gmail.client import GmailApiPort, extract_body_text
from artemis.ports.model import ModelPort
from artemis.ports.types import Message
from artemis.untrusted.quarantine import QuarantinedReader

logger = logging.getLogger(__name__)

RECEIPT_KEYWORDS = frozenset(
    {"receipt", "order confirmation", "payment of", "transaction alert", "you paid", "charged"}
)

EXTRACT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "txn_date": {"type": "string"},
                    "amount": {"type": "string"},
                    "currency": {"type": "string"},
                    "merchant": {"type": ["string", "null"]},
                    "instrument_hint": {"type": ["string", "null"]},
                    "type_hint": {
                        "type": "string",
                        "enum": ["purchase", "refund", "transfer", "settlement"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "txn_date",
                    "amount",
                    "currency",
                    "merchant",
                    "instrument_hint",
                    "type_hint",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["transactions"],
    "additionalProperties": False,
}

TYPE_POST_RULES: dict[str, TransactionType] = {
    "bill payment received": TransactionType.SETTLEMENT,
    "card payment received": TransactionType.SETTLEMENT,
    "bill payment": TransactionType.SETTLEMENT,
    "transfer to": TransactionType.TRANSFER,
    "paynow to": TransactionType.TRANSFER,
    "fast transfer": TransactionType.TRANSFER,
    "refund": TransactionType.REFUND,
    "reversal": TransactionType.REFUND,
}
"""Normalized bank phrases mapped to ledger transaction types."""

FINANCE_EXTRACT_PROMPT = (
    "Extract bank/card transaction facts from the provided quarantined summary. "
    "Return only JSON matching the response schema. Amount must be a decimal string."
)


@dataclass(frozen=True)
class TransactionExtract:
    """Bounded inert transaction facts extracted from a quarantined email summary."""

    txn_date: str
    amount: str
    currency: str
    merchant: str | None
    instrument_hint: str | None
    type_hint: str
    confidence: float
    raw_ref: str


@dataclass(frozen=True)
class EmailExtractionResult:
    """Committed transaction and inert suggestion ids produced from one email."""

    written: list[str]
    suggested: list[str]


class FinanceExtractor:
    """Extract ledger transactions from Gmail messages through Seam 7 quarantine."""

    def __init__(
        self,
        store: FinanceStore,
        api: GmailApiPort,
        reader: QuarantinedReader,
        model: ModelPort,
        *,
        bank_allowlist: frozenset[str],
        role: str = "sensitive_reasoner",
    ) -> None:
        self.store = store
        self.api = api
        self.reader = reader
        self.model = model
        self.bank_allowlist = frozenset(entry.lower() for entry in bank_allowlist)
        self.role = role

    def is_candidate(self, msg: CachedMessage) -> bool:
        address = parseaddr(msg.sender)[1]
        domain = address.split("@")[-1].lower() if "@" in address else ""
        if domain and any(domain.endswith(entry) for entry in self.bank_allowlist):
            return True
        subject = msg.subject.lower()
        return any(keyword in subject for keyword in RECEIPT_KEYWORDS)

    async def extract_email(self, msg: CachedMessage) -> EmailExtractionResult:
        full = self.api.get_message(msg.message_id, fmt="full")
        body = extract_body_text(full)
        if not body:
            return EmailExtractionResult(written=[], suggested=[])

        extract = await self.reader.read(
            raw_content=body,
            source_url=f"gmail:{msg.message_id}",
            source_domain="mail.google.com",
            query="bank/card transaction: date, amount, merchant, type",
            max_tokens=512,
        )
        if extract.parse_failed:
            logger.warning("Finance email extract parse failed for message_id=%s", msg.message_id)
            return EmailExtractionResult(written=[], suggested=[])
        if extract.flagged_injection:
            logger.warning(
                "finance email flagged injection message_id=%s — skipping",
                msg.message_id,
            )
            return EmailExtractionResult(written=[], suggested=[])

        # SECURITY: raw email body is NEVER passed to the extraction model or stored. Only Extract.summary/claims reach the model. raw_ref carries an id, not content.
        resp = await self.model.complete(
            role=self.role,
            messages=[
                Message(role="system", content=FINANCE_EXTRACT_PROMPT),
                Message(role="user", content=extract.summary),
            ],
            response_schema=EXTRACT_SCHEMA,
        )
        try:
            lines = _transaction_lines(resp.text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "finance email extraction response invalid message_id=%s error=%s",
                msg.message_id,
                exc,
            )
            return EmailExtractionResult(written=[], suggested=[])

        written: list[str] = []
        suggested: list[str] = []
        # Summary-level signal. Mixed-type multi-line emails fall through to the
        # model's per-line type_hint plus ambiguity/suggestion flow below.
        post_rule = _post_rule_type(extract.summary)
        for line_index, line in enumerate(lines):
            raw_ref = f"{msg.message_id}:{line_index}"
            try:
                transaction_extract = _build_transaction_extract(line, raw_ref=raw_ref)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "finance email transaction malformed message_id=%s line_index=%s error=%s",
                    msg.message_id,
                    line_index,
                    exc,
                )
                return EmailExtractionResult(written=written, suggested=suggested)
            instrument_account_id = self._resolve_instrument(transaction_extract.instrument_hint)
            resolved_type = post_rule or _valid_type_or_purchase(transaction_extract.type_hint)
            conflict_reason = _conflict_reason(transaction_extract, resolved_type, post_rule)
            if conflict_reason is not None:
                transaction_payload = asdict(transaction_extract)
                transaction_payload["instrument_account_id"] = instrument_account_id
                payload_json = json.dumps(
                    {
                        "transaction": transaction_payload,
                        "reason": conflict_reason,
                    },
                    sort_keys=True,
                )
                suggestion_id = self.store.create_fin_suggestion(
                    "ambiguous_type",
                    payload_json,
                    raw_ref=raw_ref,
                )
                suggested.append(suggestion_id)
                continue

            transaction_id = self.store.add_transaction(
                txn_date=transaction_extract.txn_date,
                amount=Decimal(transaction_extract.amount),
                merchant=transaction_extract.merchant,
                txn_type=resolved_type.value,
                source=TransactionSource.EMAIL.value,
                instrument_account_id=instrument_account_id,
                currency=transaction_extract.currency,
                raw_ref=raw_ref,
                confidence=transaction_extract.confidence,
            )
            written.append(transaction_id)
        return EmailExtractionResult(written=written, suggested=suggested)

    def _resolve_instrument(self, instrument_hint: str | None) -> str | None:
        if not instrument_hint:
            return None
        normalized_hint = _normalize(instrument_hint)
        for account in self.store.list_accounts():
            candidates = (
                str(account.get("name", "")),
                str(account.get("institution", "")),
                str(account.get("id", "")),
            )
            if any(
                _normalize(candidate) and _normalize(candidate) in normalized_hint
                for candidate in candidates
            ):
                return str(account["id"])
        return None


def _transaction_lines(text: str) -> list[Mapping[str, object]]:
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("finance extraction response must be an object")
    transactions = parsed.get("transactions")
    if not isinstance(transactions, list):
        raise ValueError("finance extraction response missing transactions")
    return [cast(Mapping[str, object], item) for item in transactions if isinstance(item, Mapping)]


def _build_transaction_extract(line: Mapping[str, object], *, raw_ref: str) -> TransactionExtract:
    confidence = line["confidence"]
    if not isinstance(confidence, str | int | float):
        raise ValueError("transaction confidence must be numeric")
    return TransactionExtract(
        txn_date=str(line["txn_date"]),
        amount=str(line["amount"]),
        currency=str(line.get("currency", "SGD")),
        merchant=_optional_str(line.get("merchant")),
        instrument_hint=_optional_str(line.get("instrument_hint")),
        type_hint=str(line["type_hint"]),
        confidence=float(confidence),
        raw_ref=raw_ref,
    )


def _post_rule_type(summary: str) -> TransactionType | None:
    normalized = _normalize(summary)
    for phrase, txn_type in TYPE_POST_RULES.items():
        if phrase in normalized:
            return txn_type
    return None


def _conflict_reason(
    extract: TransactionExtract,
    resolved_type: TransactionType,
    post_rule: TransactionType | None,
) -> str | None:
    model_type = _valid_type_or_purchase(extract.type_hint)
    normalized_hint = _normalize(
        f"{extract.type_hint} {extract.merchant or ''} {extract.instrument_hint or ''}"
    )
    if extract.confidence < 0.6:
        return "low_confidence"
    if "paynow" in normalized_hint and model_type == TransactionType.PURCHASE:
        return "paynow_transfer_purchase_conflict"
    if post_rule is not None and model_type != resolved_type:
        return f"type_disagreement:{model_type.value}:{resolved_type.value}"
    return None


def _valid_type_or_purchase(type_hint: str) -> TransactionType:
    try:
        return TransactionType(type_hint)
    except ValueError:
        return TransactionType.PURCHASE


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
