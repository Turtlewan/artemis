---
spec: fin-b-email-extraction
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- Wave S · NEW · second in FIN-a→b→c→d. Implements email→transaction extraction (F-D4/F-D7):
     bank sender-allowlist + receipt-classifier fallback, quarantine-FIRST (DR-a), local-only
     sensitive_reasoner extraction over the Extract (never raw mail), type inference = model + bank-
     phrase post-rules, ambiguous → inert L3 owner-review. Idempotent via FIN-a raw_ref UNIQUE.
     cross_model_review: true (untrusted email input + owner-private sensitive ledger writes). -->

# Spec: FIN-b — Email→transaction extraction (quarantine-first, local-only, allowlist + receipt fallback)

**Identity:** The Finance email-extraction path — classify candidate emails (bank sender-allowlist ∪ receipt-classifier fallback), read each through the DR-a `QuarantinedReader` boundary, run a LOCAL `sensitive_reasoner` extraction over the `Extract` (never raw mail) into a `TransactionExtract`, infer `txn_type` via model + deterministic bank-phrase post-rules, route ambiguous extracts to an inert owner-review suggestion, and write confident extracts into the FIN-a ledger idempotently via `raw_ref`.
→ why: see docs/technical/modules/finance.md (Data sources / Data flow / Transfers & settlements) · docs/findings/cluster-decisions/finance.md (F-D4 allowlist+receipt, F-D7 type-infer+ask) · docs/technical/adr/ADR-009-untrusted-content-and-deep-research.md (quarantine) · docs/technical/adr/ADR-022 (always-local).

## Assumptions

- **FIN-a** complete: `FinanceStore` / `FinanceRepository` over `finance.db` (OWNER_PRIVATE); `repo.add_transaction(*, txn_date, amount: Decimal, merchant=None, category_id=None, txn_type="purchase", source, instrument_account_id=None, currency="SGD", amount_original=None, currency_original=None, raw_ref=None, confidence=None, notes=None) -> str` is **L0-idempotent** on `raw_ref` (UNIQUE partial index → re-processing the same email line returns the existing id, never double-inserts); `TransactionType` (`purchase`/`refund`/`transfer`/`settlement`), `TransactionSource` (`email`/`manual`/`csv`); `repo.list_accounts()` / `repo.get_category_by_name(name)` for instrument/category resolution. → impact: Stop (the writer + idempotency wall come from FIN-a; FIN-b never re-implements dedup at L0).
- **M8-b1** complete: the Gmail connector exposes `GmailApiPort.get_message(message_id, fmt="full")`, the MIME `extract_body_text(msg)` helper, `CachedMessage` (`message_id`, `sender`, `subject`, `snippet`, `category`, `internal_date_ms`), and the ingest path that lets FIN-b consume already-mirrored emails. The sender domain is parsed from `CachedMessage.sender` via `email.utils.parseaddr`. → impact: Stop (FIN-b reads candidate emails from the M8-b1 cache + fetches full bodies via `GmailApiPort`; it adds no new Gmail I/O surface).
- **DR-a** complete: `QuarantinedReader(model, role).read(*, raw_content, source_url, source_domain, query, max_tokens) -> Extract` (async, toolless, schema-bounded); `Extract{source_url, source_domain, summary, claims, flagged_injection, parse_failed}`. The privileged extraction runs ONLY over `Extract.summary` / `Extract.claims` — **never raw mail body** (Seam 7 invariant; identical to M8-b2 / CAL-d). → impact: Stop (load-bearing: raw bank-alert text never reaches the extraction model directly).
- **Local model (ADR-022/F-D13 — always-local):** both the `QuarantinedReader` read AND the `TransactionExtract` constrained-decode run on the LOCAL `sensitive_reasoner` role at the loopback endpoint. **No Codex/cloud port is imported anywhere in the finance package.** The acceptance criteria assert no cloud import. → impact: Stop (the always-local wall is structural — ledger data must never reach the cloud, here or downstream).
- **X3 runtime-config** complete: `get_runtime_config().finance.bank_sender_allowlist` (default `("uob.com.sg","scb.com","standardchartered.com","dbs.com","dbs.com.sg")`) is the allowlist read at composition time. → impact: Caution (the allowlist is a tunable; read it once at extractor construction, not per-email).
- **M2-stub on dev:** `FakeKeyProvider(owner_unlocked=True)` + plain-sqlite fallback for the FIN-a store; `FakeQuarantinedReader` (canned `Extract`) + `FakeModelPort` (deterministic `TransactionExtract` JSON) for the extraction. Real served model + real keyed SQLCipher are Mac-gated. → impact: Low.
- **Suggestion / owner-review surface:** FIN-b's L3 ambiguous-route writes an **inert** finance suggestion (a `finance_suggestion` row in the FIN-a store, or — if FIN-a did not define one — a thin `fin_suggestion` table added here). It is NEVER silently counted toward spend. The owner confirms via a tool. → impact: Caution (FIN-a froze 7 tables without a finance-suggestion table; this spec ADDS a small `fin_suggestion` table for L3 review items — see Task 1 schema-add note; this is additive, no FIN-a re-freeze).

Simplicity check: considered per-bank parsers (UOB/SCB/DBS each its own regex extractor) — rejected; F-D5/F-b mean no canonical bank format and no bank link, so a single model-extraction-over-quarantined-summary path + a small deterministic post-rule table for the three banks' phrasings is the minimum. Considered classifying at the cloud — rejected outright (always-local invariant). Considered eagerly inserting ambiguous extracts and back-correcting — rejected; precision-first means ambiguous → inert suggestion, never a silent spend count.

## Prerequisites

- Specs complete: **FIN-a** (ledger + idempotent writer), **M8-b1** (Gmail cache + `GmailApiPort` + `extract_body_text`), **DR-a** (`QuarantinedReader`/`Extract`), **X3-runtime-config** (`finance.bank_sender_allowlist`), local `sensitive_reasoner` role.
- Environment: no new PyPI deps (reuses `email`, `decimal`, the M8-b1 + DR-a surfaces). `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/finance/schema.py` | modify | additive: add a small `fin_suggestion` table (L3 owner-review items) — does NOT alter the frozen 4-table awareness schema |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/repository.py` | modify | additive: `create_fin_suggestion` / `list_fin_suggestions` / `accept_fin_suggestion` / `reject_fin_suggestion` |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/extraction.py` | create | `TransactionExtract` schema + `EXTRACT_SCHEMA` + `FinanceExtractor` (allowlist/receipt classify → quarantine → local extract → type post-rules → write-or-suggest) |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py` | modify | add `transaction_extract_email` (trigger) + `fin_suggestion_list`/`fin_suggestion_accept`/`fin_suggestion_reject` callables |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` | modify | add the new ToolSpecs (still no hooks in FIN-b; hooks are FIN-c) |
| `/Users/artemis-build/artemis/tests/test_finance_extraction.py` | create | allowlist+receipt classify, quarantine-first (raw never to model), extract→write idempotent, type post-rules, ambiguous→suggestion, degrade paths |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: `fin_suggestion` table (additive) + repository methods** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/schema.py`, `/Users/artemis-build/artemis/src/artemis/modules/finance/repository.py` (modify) —

  Add ONE table to `create_schema` (additive — the frozen `account`/`transaction`/`subscription`/`bill`/`category`/`csv_profile`/`meta` are untouched; bump no `SCHEMA_VERSION` if FIN-a's `meta` already gates creation via `IF NOT EXISTS` — document that this table is created idempotently alongside the others):

  **`fin_suggestion`**: `id TEXT PRIMARY KEY, kind TEXT NOT NULL` (`"ambiguous_type"|"possible_duplicate"` — the second is used by FIN-c's L3), `payload_json TEXT NOT NULL` (the inert proposed `TransactionExtract` + the reason — counts/IDs/values only; NEVER raw email body), `raw_ref TEXT, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL`.
  Index `idx_fin_suggestion_status` on `(status)`.

  Repository methods:
  - `create_fin_suggestion(kind, payload_json, *, raw_ref=None) -> str`
  - `list_fin_suggestions(*, status="pending") -> list[dict]`
  - `accept_fin_suggestion(id, *, txn_type: str) -> str` — sets status accepted; constructs a `transaction` from the inert payload with the owner-chosen `txn_type`; returns the new txn id (idempotent via the payload's `raw_ref`).
  - `reject_fin_suggestion(id) -> None`.

  — done when: `uv run mypy --strict src` passes; `create_schema` now creates `fin_suggestion` (verify via `sqlite_master`); `create_fin_suggestion` + `list_fin_suggestions(status="pending")` round-trip; `accept_fin_suggestion(id, txn_type="purchase")` writes a txn via the idempotent `add_transaction`.

- [ ] **Task 2: `TransactionExtract` schema + `EXTRACT_SCHEMA`** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/extraction.py` —

  ```python
  @dataclass(frozen=True)
  class TransactionExtract:
      txn_date: str            # ISO date (YYYY-MM-DD)
      amount: str              # decimal STRING (parses to Decimal; never float)
      currency: str            # ISO 4217, default "SGD"
      merchant: str | None
      instrument_hint: str | None   # e.g. "UOB card ending 1234" — resolved to an account FK by the writer
      type_hint: str           # one of purchase/refund/transfer/settlement (model's best guess; refined by post-rules)
      confidence: float        # 0..1
      raw_ref: str             # f"{source_message_id}:{line_index}" — the FIN-a L0 idempotency key
  ```

  `EXTRACT_SCHEMA: dict[str, object]` — a JSON schema for `{"transactions": [{txn_date, amount, currency, merchant?, instrument_hint?, type_hint(enum: purchase|refund|transfer|settlement), confidence(0..1)}]}` (multi-item emails — a single bank statement email can carry several lines; each gets a `line_index`). `additionalProperties: False`. This is the `response_schema` the LOCAL model constrained-decodes against. Amount stays a STRING in the schema (model emits `"19.99"`, the writer parses `Decimal`).

  — done when: `uv run mypy --strict src` passes; `EXTRACT_SCHEMA` is valid JSON Schema (assert via `jsonschema.validate` in tests); a sample `{"transactions":[{...}]}` validates; `TransactionExtract` constructs from a parsed line.

- [ ] **Task 3: `FinanceExtractor` — classify → quarantine → local extract → type post-rules → write/suggest** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/extraction.py` —

  `class FinanceExtractor` constructed with `(store: FinanceStore, api: GmailApiPort, reader: QuarantinedReader, model: ModelPort, *, bank_allowlist: frozenset[str], role: str = "sensitive_reasoner")` — `model` is the LOCAL `ModelPort` (loopback `sensitive_reasoner` role — the SAME local port the `QuarantinedReader` uses; NEVER a cloud port), assigned `self.model`. `bank_allowlist` read from `get_runtime_config().finance.bank_sender_allowlist` at composition. (Task 4's `init_finance_extractor`/composition wiring passes this local `model`.)

  - **`def is_candidate(self, msg: CachedMessage) -> bool`** (classify, F-D4): `domain = email.utils.parseaddr(msg.sender)[1].split("@")[-1].lower()`; if `domain` ends with any allowlist entry → candidate. ELSE receipt-classifier fallback: a deterministic keyword pass (`"receipt"`, `"order confirmation"`, `"payment of"`, `"transaction alert"`, `"you paid"`, `"charged"`) on `msg.subject` (LOCAL substring check — LLM-free; the subject is read for a boolean only and never stored). Returns the OR. (Pure deterministic — no model.)

  - **`async def extract_email(self, msg: CachedMessage) -> list[str]`** (the quarantine-first extraction; returns the written/suggested txn ids):
    1. Fetch the full body: `full = self.api.get_message(msg.message_id, fmt="full")`; `body = extract_body_text(full)`; if empty → return `[]` (no extraction on empty body).
    2. **Quarantine FIRST:** `extract = await self.reader.read(raw_content=body, source_url=f"gmail:{msg.message_id}", source_domain="mail.google.com", query="bank/card transaction: date, amount, merchant, type", max_tokens=512)`. If `extract.parse_failed` → log a WARNING (no body) and return `[]` (degrade-don't-crash).
    3. **Local extract over the Extract (NEVER raw body):** `resp = await self.model.complete(role=self.role, messages=[{"role":"system","content":<finance extraction prompt>}, {"role":"user","content":extract.summary}], response_schema=EXTRACT_SCHEMA)`. Parse `resp.text` JSON → list of line dicts. **The model input is `extract.summary` (and/or `extract.claims`), never `body`** — the Seam 7 invariant. (`self.model` is the LOCAL `ModelPort` injected at construction — same local port the QuarantinedReader uses; do NOT import a cloud port.)
    4. For each line (with its `line_index`): build `raw_ref = f"{msg.message_id}:{line_index}"`; build a `TransactionExtract`.
    5. **Type inference (F-D7):** start from the model's `type_hint`; apply deterministic bank-phrase POST-RULES over `extract.summary` (LLM-free refinement): e.g. UOB/SCB/DBS "card payment received" / "bill payment" → `settlement`; "transfer to"/"PayNow to"/"FAST transfer" → `transfer`; "refund"/"reversal" → `refund`; default → `purchase`. The post-rules table is a small `dict[str, TransactionType]` of normalized phrases keyed per bank; document it.
    6. **Ambiguity gate:** if the type is ambiguous (model `type_hint` disagrees with a post-rule, OR confidence `< 0.6`, OR a PayNow/transfer-vs-purchase conflict) → **do NOT write a transaction**; instead `store.create_fin_suggestion(kind="ambiguous_type", payload_json=<TransactionExtract as JSON + the conflict reason>, raw_ref=raw_ref)` (inert; owner confirms the type later). Collect the suggestion id.
    7. Else (confident): `txn_id = store.add_transaction(txn_date=..., amount=Decimal(extract.amount), merchant=..., txn_type=<resolved>, source="email", instrument_account_id=<resolved from instrument_hint, or None>, currency=..., raw_ref=raw_ref, confidence=...)` — the FIN-a L0 idempotency means a re-run returns the existing id. Collect the txn id.
    Return all collected ids.

    **Instrument resolution:** match `instrument_hint` against `store.list_accounts()` by a normalized substring (e.g. "UOB" + last-4) → the `instrument_account_id` FK (F-D11); if no match, leave `None` (the txn still records; the owner can assign the account later). Never auto-create an account from an email (precision-first).

  **Security invariant (inline comment):** `# SECURITY: raw email body is NEVER passed to the extraction model or stored. Only Extract.summary/claims reach the model. raw_ref carries an id, not content.`

  — done when: `uv run mypy --strict src` passes; `is_candidate` admits an allowlist-domain sender AND a receipt-keyword non-bank sender, rejects an unrelated newsletter; `await extract_email(msg)` with a `FakeQuarantinedReader` + `FakeModelPort` writes a txn whose `raw_ref` is `"<mid>:0"`; a second `extract_email` on the same msg returns the SAME txn id (L0 idempotency); an ambiguous extract creates a `fin_suggestion` (no txn); a `parse_failed` Extract returns `[]` without raising; the `FakeModelPort` received `extract.summary`, NOT the raw body (assert).

- [ ] **Task 4: Tools + manifest wiring** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py`, `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` (modify) —

  Add callables (ADR-016 async; store calls sync inside):
  | name (bare) | args | return | risk |
  |---|---|---|---|
  | `transaction_extract_email` | `message_id: str` | `ExtractResult(written: list[str], suggested: list[str])` | WRITE |
  | `fin_suggestion_list` | `status: str = "pending"` | `FinSuggestionListResult(suggestions: list[dict])` | READ |
  | `fin_suggestion_accept` | `id: str, txn_type: str` | `TxnCreatedResult(transaction_id: str)` | WRITE |
  | `fin_suggestion_reject` | `id: str` | `OkResult` | WRITE |

  `transaction_extract_email` resolves the `CachedMessage` from the M8-b1 cache by `message_id` then calls `extractor.extract_email`. Wire a module-level `_extractor` + `init_finance_extractor(extractor)` (set by `finance_manifest`). Add the 4 ToolSpecs (all AUTO, no GATE — finance is internal local-ledger). No hooks added in FIN-b.

  — done when: `uv run mypy --strict src` passes; the 4 callables are coroutine functions; `finance_manifest(store, extractor=...)` includes the 4 new tools; `transaction_extract_email` raises `RuntimeError` if `_extractor` unset.

- [ ] **Task 5 (GATED — on-hardware):** real served `sensitive_reasoner` + real `QuarantinedReader` + real Gmail: extract a real UOB/SCB/DBS alert → a confident txn lands in `finance.db`; a PayNow ambiguous case → a `fin_suggestion`; re-running the same email writes nothing new (L0). Confirm no cloud egress (the extraction model endpoint is loopback). — done when: recorded in handoff.

- [ ] **Task 6: Tests** — files: `/Users/artemis-build/artemis/tests/test_finance_extraction.py` — typed pytest, FIN-a store via plain-sqlite fallback, `FakeQuarantinedReader` (canned `Extract`), `FakeModelPort` (deterministic `EXTRACT_SCHEMA` JSON), `FakeGmailApi`.

  - **classify:** allowlist domain (`alerts@uob.com.sg`) → candidate; receipt-keyword non-bank (`receipts@shop.com`, subject "Your order confirmation") → candidate; newsletter → not.
  - **quarantine-first (Seam 7):** `extract_email` passes `Extract.summary` to the `FakeModelPort`, NOT the raw body (assert `FakeModelPort.last_user_content == reader.fixed_summary`); `parse_failed` Extract → `[]`, no raise; assert the written txn carries no raw body.
  - **extract → write idempotent:** confident extract writes one txn with `raw_ref="<mid>:0"`, `source="email"`; second call returns same id, one row.
  - **multi-line email:** an Extract producing 2 transaction lines → 2 txns with `raw_ref` `:0` and `:1`.
  - **type post-rules:** a "bill payment received" UOB phrasing → `settlement` (excluded from spend); a "FAST transfer to" → `transfer`; a "refund" → `refund`; plain purchase → `purchase`.
  - **ambiguous → suggestion:** a PayNow/low-confidence case → no txn, one `fin_suggestion(kind="ambiguous_type")`; `fin_suggestion_accept(id, txn_type="transfer")` then writes the txn.
  - **always-local guard:** assert `artemis.modules.finance.extraction` imports no cloud/Codex port (only the local `ModelPort` + DR-a).

  — done when: `uv run pytest -q tests/test_finance_extraction.py` passes AND `uv run mypy --strict src tests/test_finance_extraction.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/finance/schema.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/finance/repository.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/extraction.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` |
| Create | `/Users/artemis-build/artemis/tests/test_finance_extraction.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_finance_extraction.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_finance_extraction.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/finance/{schema,repository,extraction,tools,manifest}.py`, `tests/test_finance_extraction.py` |
| `git commit` | `"feat: FIN-b email→transaction extraction — quarantine-first, local-only, allowlist + receipt fallback"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir resolution |

### Network
| Action | Purpose |
|--------|---------|
| HTTPS to `gmail.googleapis.com` (GATED, on-Mini) | full-body fetch for candidate emails |
| local `127.0.0.1` to mlx-openai-server (GATED) | QuarantinedReader + extraction on the LOCAL model (loopback only — never cloud) |

## Specialist Context

### Security

- **Quarantine-first (Seam 7 / ADR-009):** bank-alert bodies are UNTRUSTED. The extraction model ONLY ever sees the DR-a `Extract.summary`/`claims` — NEVER the raw body. Enforced structurally: `extract_email` calls `reader.read` first and passes `extract.summary` to the local model; raw `body` never reaches the model or any stored field. Tested by asserting `FakeModelPort.last_user_content == Extract.summary`.
- **Always-local (ADR-022/F-D13):** the `QuarantinedReader` read AND the extraction constrained-decode run on the LOCAL `sensitive_reasoner` (loopback). No cloud/Codex port is imported in the finance package — asserted in tests. Ledger data never egresses.
- **Precision-first (F-D7):** ambiguous extracts (incl. PayNow) are NEVER silently counted — they become inert `fin_suggestion` rows the owner confirms. No transaction is written on low confidence.
- **L0 idempotency (FIN-a):** `raw_ref` UNIQUE means re-processing the same email line never double-inserts — the dedup wall is in FIN-a, not re-implemented here.
- **No external-effect:** all writes are internal local-ledger edits — no GATE/staging (finance.md).
- **No content in logs:** never log the raw body, `Extract.summary`, merchant, or amount at info level — ids + counts only.

[apex-security/apex-data review (cross_model_review): confirm raw body never reaches the model or DB; confirm no cloud import; confirm the ambiguous-route writes an inert suggestion (no silent spend); confirm money parses to `Decimal` (never float) at the write boundary.]

### Performance

- One `QuarantinedReader` read + one extraction call per candidate email — both local, bounded `max_tokens=512`. The candidate filter (allowlist + receipt keywords) is a deterministic O(1) pass; the heavy model work runs only on candidates, off the interactive turn (the brain schedules extraction). Multi-line emails reuse one Extract → one model call.

### Accessibility

(none — no frontend in FIN-b; the `fin_suggestion` review surface is Wave U / CLIENT)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/finance/extraction.py` | Docstring `TransactionExtract`, the quarantine-first invariant (Extract only — never raw body), the allowlist+receipt classify, the type post-rules table, the ambiguous→inert-suggestion gate, the always-local wall |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_finance_extraction.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_finance_extraction.py` → verify: allowlist+receipt classify; quarantine-first (model gets Extract.summary not raw body; parse_failed → []); extract→write idempotent (same raw_ref → one row); multi-line → 2 raw_refs; type post-rules (settlement/transfer/refund/purchase); ambiguous → fin_suggestion then accept writes txn; no cloud import.
- [ ] `uv run python -c "from artemis.modules.finance.extraction import FinanceExtractor, TransactionExtract; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) real bank alert → confident txn; PayNow → suggestion; re-run writes nothing; loopback-only extraction → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
