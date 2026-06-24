from __future__ import annotations

import base64
import importlib
import inspect
import json
import sqlite3
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.finance.extraction import EXTRACT_SCHEMA, FinanceExtractor
from artemis.modules.finance.repository import FinanceRepository
from artemis.modules.finance.schema import TransactionSource, TransactionType, create_schema
from artemis.modules.finance.store import FinanceStore
from artemis.modules.finance.tools import (
    FinSuggestionAcceptArgs,
    fin_suggestion_accept,
    init_finance_tools,
)
from artemis.modules.gmail.cache import CachedMessage
from artemis.modules.gmail.client import FakeGmailApi, MailCategory
from artemis.ports.model import ModelPort, ModelResponse
from artemis.ports.types import Message, Scope, Vector
from artemis.untrusted.quarantine import Extract, QuarantinedReader


class FakeKeyProvider:
    def __init__(self, *, owner_unlocked: bool) -> None:
        self.owner_unlocked = owner_unlocked

    def dek_for_scope(self, scope: Scope) -> SecretKey:
        if scope != OWNER_PRIVATE or not self.owner_unlocked:
            raise ScopeLockedError(f"Scope is locked: {scope}")
        return SecretKey(b"f" * 32)

    def is_owner_unlocked(self) -> bool:
        return self.owner_unlocked


class FakeQuarantinedReader:
    def __init__(
        self,
        *,
        fixed_summary: str,
        parse_failed: bool = False,
        flagged_injection: bool = False,
    ) -> None:
        self.fixed_summary = fixed_summary
        self.parse_failed = parse_failed
        self.flagged_injection = flagged_injection
        self.last_raw_content: str | None = None

    async def read(
        self,
        *,
        raw_content: str,
        source_url: str,
        source_domain: str,
        query: str,
        max_tokens: int = 1024,
    ) -> Extract:
        self.last_raw_content = raw_content
        return Extract(
            source_url=source_url,
            source_domain=source_domain,
            summary=self.fixed_summary,
            claims=(),
            flagged_injection=self.flagged_injection,
            parse_failed=self.parse_failed,
            tokens_used=max_tokens,
        )


class FakeModelPort:
    def __init__(
        self,
        transactions: Sequence[Mapping[str, object]],
        *,
        raw_response: str | None = None,
    ) -> None:
        self.transactions = [dict(item) for item in transactions]
        self.raw_response = raw_response
        self.complete_calls = 0
        self.last_user_content: str | None = None
        self.last_response_schema: dict[str, object] | None = None

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del role, temperature, max_tokens
        self.complete_calls += 1
        self.last_user_content = messages[-1].content
        self.last_response_schema = response_schema
        if self.raw_response is not None:
            return ModelResponse(text=self.raw_response)
        return ModelResponse(text=json.dumps({"transactions": self.transactions}))

    async def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature
        if False:
            yield ""

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role, texts
        return []


def _store(tmp_path: Path) -> FinanceStore:
    return FinanceStore(Settings(data_root=tmp_path), FakeKeyProvider(owner_unlocked=True))


def _message(message_id: str, *, sender: str, subject: str) -> CachedMessage:
    return CachedMessage(
        message_id=message_id,
        thread_id=f"thread-{message_id}",
        history_id="1",
        sender=sender,
        subject=subject,
        internal_date_ms=1,
        category=MailCategory.PRIMARY,
        snippet="",
        label_ids=(),
        has_attachments=False,
        unread=True,
        important=True,
        body_ingested=False,
    )


def _gmail_api(message_id: str, body: str) -> FakeGmailApi:
    encoded = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
    return FakeGmailApi(
        messages={
            message_id: {
                "id": message_id,
                "payload": {
                    "mimeType": "text/plain",
                    "body": {"data": encoded},
                    "filename": "",
                },
            }
        }
    )


def _line(
    *,
    txn_date: str = "2026-06-24",
    amount: str = "19.99",
    merchant: str | None = "Kopi",
    instrument_hint: str | None = None,
    type_hint: str = "purchase",
    confidence: float = 0.95,
) -> dict[str, object]:
    return {
        "txn_date": txn_date,
        "amount": amount,
        "currency": "SGD",
        "merchant": merchant,
        "instrument_hint": instrument_hint,
        "type_hint": type_hint,
        "confidence": confidence,
    }


def _extractor(
    tmp_path: Path,
    *,
    message_id: str,
    body: str,
    summary: str,
    transactions: Sequence[Mapping[str, object]],
    parse_failed: bool = False,
    flagged_injection: bool = False,
    raw_response: str | None = None,
) -> tuple[FinanceExtractor, FakeQuarantinedReader, FakeModelPort, FinanceStore]:
    store = _store(tmp_path)
    reader = FakeQuarantinedReader(
        fixed_summary=summary,
        parse_failed=parse_failed,
        flagged_injection=flagged_injection,
    )
    model = FakeModelPort(transactions, raw_response=raw_response)
    extractor = FinanceExtractor(
        store,
        _gmail_api(message_id, body),
        cast(QuarantinedReader, reader),
        cast(ModelPort, model),
        bank_allowlist=frozenset({"uob.com.sg", "dbs.com.sg"}),
    )
    return extractor, reader, model, store


def test_extract_schema_shape() -> None:
    assert EXTRACT_SCHEMA["additionalProperties"] is False
    properties = cast(dict[str, object], EXTRACT_SCHEMA["properties"])
    transactions = cast(dict[str, object], properties["transactions"])
    item = cast(dict[str, object], transactions["items"])
    item_properties = cast(dict[str, object], item["properties"])
    amount_schema = cast(dict[str, object], item_properties["amount"])
    assert amount_schema["type"] == "string"


def test_classify_allowlist_receipt_and_newsletter(tmp_path: Path) -> None:
    extractor, _, _, _ = _extractor(
        tmp_path,
        message_id="m1",
        body="body",
        summary="plain purchase",
        transactions=[_line()],
    )
    assert extractor.is_candidate(_message("m1", sender="alerts@uob.com.sg", subject="Alert"))
    assert extractor.is_candidate(
        _message("m2", sender="receipts@shop.com", subject="Your order confirmation")
    )
    assert not extractor.is_candidate(_message("m3", sender="news@shop.com", subject="Newsletter"))


@pytest.mark.asyncio
async def test_quarantine_first_and_parse_failed(tmp_path: Path) -> None:
    raw_body = "RAW BANK BODY do not send to model"
    extractor, reader, model, store = _extractor(
        tmp_path,
        message_id="mid",
        body=raw_body,
        summary="plain purchase at Kopi",
        transactions=[_line()],
    )
    result = await extractor.extract_email(
        _message("mid", sender="alerts@uob.com.sg", subject="Alert")
    )
    assert result.written
    assert result.suggested == []
    assert reader.last_raw_content == raw_body
    assert model.last_user_content == reader.fixed_summary
    transaction = store.get_transaction(result.written[0])
    assert transaction is not None
    assert raw_body not in json.dumps(transaction, default=str)

    failed, _, failed_model, _ = _extractor(
        tmp_path,
        message_id="failed",
        body=raw_body,
        summary="",
        transactions=[_line()],
        parse_failed=True,
    )
    failed_result = await failed.extract_email(
        _message("failed", sender="alerts@uob.com.sg", subject="")
    )
    assert failed_result.written == []
    assert failed_result.suggested == []
    assert failed_model.last_user_content is None


@pytest.mark.asyncio
async def test_flagged_injection_skips_model(tmp_path: Path) -> None:
    extractor, _, model, _ = _extractor(
        tmp_path,
        message_id="flagged",
        body="RAW BANK BODY do not send to model",
        summary="plain purchase at Kopi",
        transactions=[_line()],
        flagged_injection=True,
    )

    result = await extractor.extract_email(
        _message("flagged", sender="alerts@uob.com.sg", subject="Alert")
    )

    assert result.written == []
    assert result.suggested == []
    assert model.complete_calls == 0
    assert model.last_user_content is None


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_response", ["not json", "{}"])
async def test_malformed_model_output_degrades_without_raising(
    tmp_path: Path,
    raw_response: str,
) -> None:
    extractor, _, model, _ = _extractor(
        tmp_path,
        message_id="bad-model",
        body="body",
        summary="plain purchase at Kopi",
        transactions=[],
        raw_response=raw_response,
    )

    result = await extractor.extract_email(
        _message("bad-model", sender="alerts@uob.com.sg", subject="Alert")
    )

    assert result.written == []
    assert result.suggested == []
    assert model.complete_calls == 1


@pytest.mark.asyncio
async def test_malformed_transaction_line_returns_partial(tmp_path: Path) -> None:
    extractor, _, _, store = _extractor(
        tmp_path,
        message_id="partial",
        body="body",
        summary="plain purchase",
        transactions=[
            _line(txn_date="2026-06-24", amount="1.00", merchant="A"),
            {**_line(txn_date="2026-06-25", amount="2.00", merchant="B"), "confidence": {}},
        ],
    )

    result = await extractor.extract_email(
        _message("partial", sender="alerts@uob.com.sg", subject="")
    )

    assert len(result.written) == 1
    assert result.suggested == []
    assert len(store.list_transactions()) == 1


@pytest.mark.asyncio
async def test_extract_write_idempotent(tmp_path: Path) -> None:
    extractor, _, _, store = _extractor(
        tmp_path,
        message_id="mid",
        body="body",
        summary="plain purchase",
        transactions=[_line()],
    )
    msg = _message("mid", sender="alerts@uob.com.sg", subject="Alert")
    first = await extractor.extract_email(msg)
    second = await extractor.extract_email(msg)

    assert second == first
    transactions = store.list_transactions()
    assert len(transactions) == 1
    assert transactions[0]["raw_ref"] == "mid:0"
    assert transactions[0]["source"] == TransactionSource.EMAIL.value


@pytest.mark.asyncio
async def test_multi_line_email_uses_line_raw_refs(tmp_path: Path) -> None:
    extractor, _, _, store = _extractor(
        tmp_path,
        message_id="multi",
        body="body",
        summary="plain purchases",
        transactions=[
            _line(txn_date="2026-06-24", amount="1.00", merchant="A"),
            _line(txn_date="2026-06-25", amount="2.00", merchant="B"),
        ],
    )
    result = await extractor.extract_email(
        _message("multi", sender="alerts@uob.com.sg", subject="")
    )

    assert len(result.written) == 2
    assert result.suggested == []
    raw_refs = {transaction["raw_ref"] for transaction in store.list_transactions()}
    assert raw_refs == {"multi:0", "multi:1"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("summary", "type_hint", "expected"),
    [
        ("UOB bill payment received", "settlement", TransactionType.SETTLEMENT.value),
        ("FAST transfer to savings", "transfer", TransactionType.TRANSFER.value),
        ("Refund from merchant", "refund", TransactionType.REFUND.value),
        ("Coffee purchase", "purchase", TransactionType.PURCHASE.value),
    ],
)
async def test_type_post_rules(
    tmp_path: Path,
    summary: str,
    type_hint: str,
    expected: str,
) -> None:
    extractor, _, _, store = _extractor(
        tmp_path,
        message_id=f"msg-{expected}",
        body="body",
        summary=summary,
        transactions=[_line(type_hint=type_hint)],
    )
    result = await extractor.extract_email(
        _message(f"msg-{expected}", sender="alerts@uob.com.sg", subject="")
    )

    transaction = store.get_transaction(result.written[0])
    assert transaction is not None
    assert transaction["txn_type"] == expected


@pytest.mark.asyncio
async def test_ambiguous_suggestion_accepts_to_transaction(tmp_path: Path) -> None:
    raw_body = "RAW BANK BODY with card numbers must not be stored"
    extractor, _, _, store = _extractor(
        tmp_path,
        message_id="paynow",
        body=raw_body,
        summary="PayNow to Alex",
        transactions=[_line(merchant="PayNow", type_hint="purchase", confidence=0.5)],
    )
    result = await extractor.extract_email(
        _message("paynow", sender="alerts@uob.com.sg", subject="")
    )

    assert store.list_transactions() == []
    suggestions = store.list_fin_suggestions()
    assert result.written == []
    assert len(result.suggested) == len(suggestions) == 1
    assert suggestions[0]["id"] == result.suggested[0]
    assert suggestions[0]["kind"] == "ambiguous_type"
    assert raw_body not in str(suggestions[0]["payload_json"])

    transaction_id = store.accept_fin_suggestion(
        str(result.suggested[0]), txn_type=TransactionType.TRANSFER.value
    )
    transaction = store.get_transaction(transaction_id)
    assert transaction is not None
    assert transaction["txn_type"] == TransactionType.TRANSFER.value
    assert transaction["raw_ref"] == "paynow:0"


def test_fin_suggestion_schema_and_repository_round_trip() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    repo = FinanceRepository(conn)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert "fin_suggestion" in tables

    suggestion_id = repo.create_fin_suggestion(
        "ambiguous_type",
        json.dumps({"transaction": {**_line(), "raw_ref": "raw:0"}}),
        raw_ref="raw:0",
    )
    suggestions = repo.list_fin_suggestions()
    assert len(suggestions) == 1
    assert suggestions[0]["id"] == suggestion_id
    txn_id = repo.accept_fin_suggestion(suggestion_id, txn_type=TransactionType.PURCHASE.value)
    transaction = repo.get_transaction(txn_id)
    assert transaction is not None
    assert transaction["raw_ref"] == "raw:0"


def test_double_accept_rejected_with_clear_error() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    repo = FinanceRepository(conn)
    suggestion_id = repo.create_fin_suggestion(
        "ambiguous_type",
        json.dumps({"transaction": {**_line(), "raw_ref": "raw:0"}}),
        raw_ref="raw:0",
    )

    repo.accept_fin_suggestion(suggestion_id, txn_type=TransactionType.PURCHASE.value)

    with pytest.raises(ValueError, match=f"suggestion {suggestion_id} is already accepted"):
        repo.accept_fin_suggestion(suggestion_id, txn_type=TransactionType.TRANSFER.value)


@pytest.mark.asyncio
async def test_ambiguous_suggestion_accept_preserves_resolved_instrument(tmp_path: Path) -> None:
    extractor, _, _, store = _extractor(
        tmp_path,
        message_id="instrument",
        body="body",
        summary="PayNow to Alex",
        transactions=[
            _line(
                merchant="PayNow",
                instrument_hint="DBS Multiplier",
                type_hint="purchase",
                confidence=0.5,
            )
        ],
    )
    account_id = store.create_account("DBS Multiplier", "bank", institution="DBS")
    init_finance_tools(store)

    result = await extractor.extract_email(
        _message("instrument", sender="alerts@dbs.com.sg", subject="")
    )
    accepted = await fin_suggestion_accept(
        FinSuggestionAcceptArgs(id=result.suggested[0], txn_type=TransactionType.TRANSFER.value)
    )

    transaction = store.get_transaction(accepted.transaction_id)
    assert transaction is not None
    assert transaction["instrument_account_id"] == account_id


def test_extraction_imports_no_cloud_or_codex_port() -> None:
    modules = (
        importlib.import_module("artemis.modules.finance.extraction"),
        importlib.import_module("artemis.modules.finance.tools"),
        importlib.import_module("artemis.modules.finance.manifest"),
    )
    for module in modules:
        source = inspect.getsource(module)
        assert "model_adapters" not in source
        assert "Codex" not in source
        assert "responder_cloud" not in source
