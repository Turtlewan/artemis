---
spec: fin-a-ledger-core
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- Wave S · NEW · serial head of FIN-a→b→c→d. Implements the LOCKED Finance ledger core:
     end-state 4-table schema (F-D1=B, one schema no migration), instrument=account FK (F-D11),
     fixed SG seed categories + owner add/rename flat (F-D3), manual + generic column-mapped CSV
     importer (F-D5), no bank link ever (F-b=A). Always-local (ADR-022/F-D13 — no cloud touches ledger).
     Owner-private SQLCipher (M2-stub on dev). cross_model_review: true (owned-data schema freeze). -->

# Spec: FIN-a — Finance ledger core: end-state 4-table SQLCipher schema + manual entry + column-mapped CSV importer

**Identity:** The Finance module's owned SQLCipher data layer designed for the end-state (`account`/`transaction`/`subscription`/`bill`) with the v1 awareness slice active — schema, repository, manual single-entry, a generic column-mapped CSV importer with saved profiles, SG seed categories, and a read/awareness `ModuleManifest` (OWNER_PRIVATE, no external-effect surface, no GATE).
→ why: see docs/technical/modules/finance.md (DESIGNED 2026-06-09) · docs/findings/cluster-decisions/cluster-decisions/finance.md (F-D1/D3/D5/D11/b) · docs/technical/adr/ADR-011-spoke-source-of-truth.md (own) · docs/technical/adr/ADR-022 (always-local).

## Assumptions

- **M0-a** complete: `Settings`, `get_settings()`, `paths.scope_dir(settings, OWNER_PRIVATE)`, the `relational/` subdir convention. → impact: Stop (DB path = `paths.scope_dir(settings, OWNER_PRIVATE) / "relational" / "finance.db"`).
- **M1-a** complete: `ModuleManifest`, `ToolSpec`, `ActionRisk`, `DataScope`, `Permissions`, `UiSurface` from `artemis.manifest`. → impact: Stop.
- **M2-b/M2-c** complete (STUB on dev): `KeyProvider`, `ScopeLockedError`, `OWNER_PRIVATE`, `sqlcipher_open`, `FakeKeyProvider` — the exact owned-store pattern proven at M4-a / M8-a / M8-d-a (`_connect()` seam, `key.as_hex()` local-only, plain-sqlite fallback off-hardware). → impact: Stop (real keyed SQLCipher round-trip is the Mac-gated tail).
- **M4-d-1** complete: `EntityRepository`, `EntityType`, `EntityRef`, `person_fact_key` (contracts.md Seam 6) — Finance MAY link merchants/payees to PLACE/PERSON entities later (FIN-d); FIN-a does NOT create entities (no eager-entity for finance v1). → impact: Low.
- **X3-runtime-config** complete: `get_runtime_config().finance.*` exposes `bank_sender_allowlist`, `recurring_min_occurrences`, `reconcile_date_window_days`, `reconcile_amount_exact`, `unusual_spend_sigma` — FIN-a reads NONE of these (they belong to FIN-b/c); the SG seed categories are a FIN-a structural constant in code (the *fixed* SG seed list is not a runtime tunable — owner add/rename happens at the data layer, not via policy.json). → impact: Low (FIN-a defines the seed-category constant; per-owner additions live in a `category` table row, not config).
- **Always-local invariant (ADR-022/F-D13):** NO code path in FIN-a (or any FIN-*) may route ledger data to Codex/cloud. FIN-a has no model calls at all (pure CRUD + CSV parse), so the invariant holds trivially here; the manifest declares the module owner-private and the acceptance criteria assert no cloud port import. → impact: Stop (the always-local wall is structural: FIN-a imports no `ModelPort`).
- **No external-effect surface (finance.md "Permissions & effects" LOCKED):** all writes are internal local-ledger edits — no `ActionStagingService`/GATE. Manual edits, categorize, mark-bill-paid are AUTO `ActionRisk.WRITE`. → impact: Stop (no `HIGH_STAKES`, no staging; the S$500 fraud figure is a FIN-c notification threshold, NOT a FIN-a gate).
- **End-state schema, awareness slice (F-D1=B):** freeze ALL FOUR tables now with the full end-state column set; v1 only WRITES/READS the awareness subset; net-worth/investment/budget columns exist but are unused-in-v1 (no migration later). → impact: Stop (this is the irreversible-ish freeze — pin it once, correctly).
- Off-hardware: plain-sqlite fallback + `FakeKeyProvider(owner_unlocked=True)`. → impact: Low.

Simplicity check: considered separate `accounts.db` / `transactions.db` — rejected; one owned `finance.db` with 4 tables + FK linkage is the M8-d-a precedent. No ORM (raw parameterised SQL). No migration framework (`CREATE TABLE IF NOT EXISTS` + `meta` schema-version, designed-for-end-state so no v1→v2 migration). The CSV importer is a generic column-mapper (owner maps their bank's columns once, saves a profile) — not per-bank parsers (F-D5=C; no bank link means no canonical format).

## Prerequisites

- Specs complete: **M0-a**, **M1-a**, **M2-b/c** (stub on dev), **M4-d-1** (entity backbone, not used in FIN-a), **X3-runtime-config**.
- Environment: no new PyPI deps (stdlib `csv` for import; `sqlite3` fallback; SQLCipher via M2-c). `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/finance/__init__.py` | create | package marker + re-exports (`FinanceStore`, `finance_manifest`, `TransactionType`, `TransactionSource`) |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/schema.py` | create | DDL (`account`/`transaction`/`subscription`/`bill`/`category`/`csv_profile`/`meta`), `create_schema`, `SCHEMA_VERSION`, enums, SG seed categories |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/repository.py` | create | `FinanceRepository` — CRUD for accounts/transactions/categories/csv-profiles; spend aggregation (excl. transfer/settlement); CSV import |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/store.py` | create | `FinanceStore` — `_connect()` (keyed SQLCipher, local `key.as_hex()`), lazy-open, thin delegation |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/csv_import.py` | create | `CsvColumnMapping`, `import_csv(rows, mapping, *, account_id) -> ImportResult` — generic column-mapped importer |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py` | create | awareness-phase `ToolSpec` callables (query spend, list/add/edit/recategorize txn, accounts, CSV import) |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` | create | `finance_manifest(store)` → `ModuleManifest` (OWNER_PRIVATE, no hooks in FIN-a, card surface) |
| `/Users/artemis-build/artemis/tests/test_finance_core.py` | create | schema round-trip, CRUD, spend-excludes-transfers, CSV import + saved profile, ScopeLockedError, manifest shape, no-cloud-import assertion |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Schema DDL (end-state 4-table + support tables)** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/schema.py`, `/Users/artemis-build/artemis/src/artemis/modules/finance/__init__.py` —

  Python `StrEnum` constants (stored as TEXT + CHECK):
  - `TransactionType`: `PURCHASE="purchase"`, `REFUND="refund"`, `TRANSFER="transfer"`, `SETTLEMENT="settlement"`. **Only `purchase`/`refund` count toward spend** (finance.md "Transfers & settlements — NOT expenses").
  - `TransactionSource`: `EMAIL="email"`, `MANUAL="manual"`, `CSV="csv"`.
  - `BillStatus`: `OPEN="open"`, `PAID="paid"`, `OVERDUE="overdue"`.
  - `SubscriptionCadence`: `MONTHLY="monthly"`, `YEARLY="yearly"`, `WEEKLY="weekly"`, `QUARTERLY="quarterly"`.

  `SCHEMA_VERSION = "1"`. `def create_schema(conn) -> None` idempotent. `PRAGMA foreign_keys = ON`.

  **`account`** (end-state: net-worth grouping — v1 stores name/type/currency; balance is end-state-unused-in-v1): `id TEXT PRIMARY KEY, name TEXT NOT NULL, account_type TEXT NOT NULL` (`"bank"|"card"|"cash"|"investment"|"paynow"` — the 5 SG channels seeded; free TEXT), `currency TEXT NOT NULL DEFAULT 'SGD', institution TEXT, current_balance TEXT` (nullable, end-state net-worth — unused in v1), `created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1))`.

  **`transaction`** (the core awareness table): `id TEXT PRIMARY KEY, txn_date TEXT NOT NULL` (ISO date), `amount TEXT NOT NULL` (SGD-equivalent decimal-as-text — store money as TEXT decimal strings, never float, to avoid FP error), `currency TEXT NOT NULL DEFAULT 'SGD', amount_original TEXT, currency_original TEXT` (multi-currency: original-currency amount + code; SGD-equivalent in `amount`), `merchant TEXT, category_id TEXT REFERENCES category(id), txn_type TEXT NOT NULL DEFAULT 'purchase' CHECK(txn_type IN ('purchase','refund','transfer','settlement')), source TEXT NOT NULL CHECK(source IN ('email','manual','csv')), instrument_account_id TEXT REFERENCES account(id)` (**F-D11=A: `instrument` is an FK to `account`** — the card/bank/cash channel the txn went through), `raw_ref TEXT` (→ the FIN-b quarantined Extract id; `source_message_id:line_index`; UNIQUE for L0 idempotency — see index), `confidence REAL, notes TEXT, settles_period TEXT` (end-state: a settlement maps to the statement period it clears — nullable, used by FIN-c), `created_at TEXT NOT NULL, updated_at TEXT NOT NULL`.
  Indexes: `idx_txn_date` on `(txn_date)`, `idx_txn_category` on `(category_id)`, `idx_txn_merchant` on `(merchant)`, `idx_txn_instrument` on `(instrument_account_id)`, `idx_txn_type` on `(txn_type)`, **`UNIQUE idx_txn_raw_ref` on `(raw_ref)` WHERE `raw_ref IS NOT NULL`** (L0 ingest idempotency — re-processing the same email line never double-inserts).

  **`subscription`** (derived by FIN-c from recurring txns): `id TEXT PRIMARY KEY, merchant TEXT NOT NULL, cadence TEXT NOT NULL CHECK(cadence IN ('monthly','yearly','weekly','quarterly')), amount TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'SGD', next_renewal TEXT, last_seen_price TEXT, last_seen_date TEXT, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL`.
  Index: `idx_subscription_merchant` on `(merchant)`, `idx_subscription_renewal` on `(next_renewal)`.

  **`bill`** (derived from email; reminder-only; lifecycle for FIN-c/Wave-R): `id TEXT PRIMARY KEY, payee TEXT NOT NULL, due_date TEXT NOT NULL, amount TEXT, currency TEXT NOT NULL DEFAULT 'SGD', status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','paid','overdue')), linked_task_ref TEXT` (logical `{module}:{id}` ref to a Productivity task — the bill→task handling, written by Wave-R reactions, nullable here), `raw_ref TEXT, paid_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL`.
  Index: `idx_bill_due` on `(due_date)`, `idx_bill_status` on `(status)`.

  **`category`** (fixed SG seed + owner add/rename, FLAT — F-D3=C): `id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, is_seed INTEGER NOT NULL DEFAULT 0 CHECK(is_seed IN (0,1)), created_at TEXT NOT NULL`.
  On first `create_schema`, seed the fixed SG categories via `INSERT OR IGNORE` (flat, no hierarchy): `Food & Dining`, `Groceries`, `Transport`, `Shopping`, `Bills & Utilities`, `Subscriptions`, `Health`, `Entertainment`, `Travel`, `Transfers`, `Income`, `Education`, `Insurance`, `Other`. Each seeded with `is_seed=1`. Owner can `add_category`/`rename_category` (creates `is_seed=0` rows / updates name).

  **`csv_profile`** (saved column-mapping profiles — F-D5): `id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, mapping_json TEXT NOT NULL` (serialised `CsvColumnMapping`), `created_at TEXT NOT NULL`.

  **`meta`**: `key TEXT PRIMARY KEY, value TEXT NOT NULL` — `schema_version`, `created_at` via `INSERT OR IGNORE`.

  — done when: `uv run mypy --strict src` passes; `create_schema` on a fresh connection creates all 7 tables + indexes + the 14 seed categories (`is_seed=1`); idempotent re-call adds no duplicate seeds; `amount` columns are TEXT (verified via `PRAGMA table_info`); the `raw_ref` UNIQUE partial index exists.

- [ ] **Task 2: Repository** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/repository.py` —

  `class FinanceRepository(conn)`. All SQL parameterised. Money handled as `decimal.Decimal` in Python, stored/read as TEXT (`str(Decimal)`); never `float`. IDs `uuid4().hex`. Timestamps ISO-8601 UTC (`now_iso()`).

  **Accounts:** `create_account(name, account_type, *, currency="SGD", institution=None) -> str`, `get_account(id)`, `list_accounts(*, include_archived=False)`, `update_account(id, *, name=None, institution=None, current_balance=None)`, `archive_account(id)`.

  **Categories:** `list_categories()`, `add_category(name) -> str` (is_seed=0), `rename_category(id, name)`, `get_category_by_name(name) -> dict | None`.

  **Transactions:**
  - `add_transaction(*, txn_date, amount: Decimal, merchant=None, category_id=None, txn_type="purchase", source, instrument_account_id=None, currency="SGD", amount_original=None, currency_original=None, raw_ref=None, confidence=None, notes=None) -> str` — INSERT; on `raw_ref` UNIQUE collision (L0 idempotency) return the EXISTING txn id (no double-insert; `INSERT ... ON CONFLICT(raw_ref) DO NOTHING` then SELECT by raw_ref).
  - `get_transaction(id)`, `list_transactions(*, start=None, end=None, category_id=None, txn_type=None, limit=200)`, `update_transaction(id, *, merchant=None, category_id=None, txn_type=None, notes=None, amount=None)`, `recategorize(id, category_id)`, `delete_transaction(id)`.
  - **`spend_summary(*, start, end, group_by: Literal["category","day","merchant"]) -> list[dict]`** — aggregate `SUM(amount)` over txns in `[start,end)` **WHERE `txn_type IN ('purchase','refund')`** (transfers/settlements EXCLUDED from spend — the load-bearing finance.md rule; refunds subtract). Grouped per `group_by`. Returns `[{key, total}]`. (Refund handling: refunds are negative-to-spend — either store refund amounts as negative or subtract in the SUM; document the chosen convention. Recommend: `amount` is always positive; `spend = SUM(CASE WHEN txn_type='refund' THEN -amount ELSE amount END)` over `('purchase','refund')`.)
  - `total_spend(*, start, end) -> Decimal` — the MTD headline number (excl. transfers — for the glance card).

  — done when: `uv run mypy --strict src` passes; account/category/txn CRUD round-trip; `add_transaction` twice with the same `raw_ref` inserts ONCE (returns same id); `spend_summary` over a set with a transfer + a settlement EXCLUDES them and a refund SUBTRACTS; money round-trips as `Decimal` with no FP drift (e.g. `Decimal("19.99")` survives).

- [ ] **Task 3: CSV importer (generic column-mapped + saved profiles)** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/csv_import.py` —

  ```python
  @dataclass(frozen=True)
  class CsvColumnMapping:
      date_col: str
      amount_col: str
      merchant_col: str | None = None
      currency_col: str | None = None
      type_col: str | None = None          # if the bank export has a debit/credit or type column
      date_format: str = "%Y-%m-%d"        # strptime format for the bank's date column
      amount_is_negative_spend: bool = False  # some exports use negative for spend; normalise

  @dataclass(frozen=True)
  class ImportResult:
      imported: int
      skipped_duplicates: int             # raw_ref collisions (L0)
      errors: list[str]                   # per-row parse failures (row index + reason); import continues
  ```

  `def import_csv(rows: Iterable[Mapping[str, str]], mapping: CsvColumnMapping, *, account_id: str, repo: FinanceRepository) -> ImportResult`:
  - For each row: parse `date` via `mapping.date_format`; parse `amount` to `Decimal` (strip currency symbols/commas; respect `amount_is_negative_spend`); read merchant/currency/type per the mapping (defaults: currency=`"SGD"`, type inferred — positive→`purchase`, explicit-negative-with-flag→`refund` or per `type_col`).
  - Build a stable `raw_ref = f"csv:{account_id}:{sha1(date|amount|merchant)}"` so re-importing the same file is idempotent (L0).
  - Call `repo.add_transaction(..., source="csv", instrument_account_id=account_id, raw_ref=raw_ref)`; a UNIQUE collision → `skipped_duplicates += 1`.
  - A row that fails to parse → append to `errors` (with row index + reason) and CONTINUE (one bad row never aborts the import).
  - Return `ImportResult`.

  Saved profiles: the repository's `csv_profile` table stores a named `CsvColumnMapping` (JSON). `save_csv_profile(name, mapping)` / `get_csv_profile(name) -> CsvColumnMapping | None` on the repository (serialise via `dataclasses.asdict` + `json`).

  — done when: `uv run mypy --strict src` passes; `import_csv` over a 3-row fixture imports 3 txns; a re-import of the same rows yields `imported=0, skipped_duplicates=3`; a malformed-date row is counted in `errors` and the other rows still import; a saved profile round-trips (`save_csv_profile` → `get_csv_profile` returns an equal `CsvColumnMapping`).

- [ ] **Task 4: FinanceStore** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/store.py` —

  `class FinanceStore(settings, key_provider)`. `_db_path()` = `paths.scope_dir(settings, OWNER_PRIVATE) / "relational" / "finance.db"`. `_connect()` = M8-d-a pattern exactly: `key = key_provider.dek_for_scope(OWNER_PRIVATE)` (raises `ScopeLockedError`), `key_hex = key.as_hex()` (local var only), `sqlcipher_open(db_path, key_hex)`, `PRAGMA foreign_keys = ON`, `create_schema(conn)`. Off-hardware fallback: `sqlite3.connect` on `ImportError` (annotated `# FALLBACK: no encryption — CI/dev only`). Lazy-open `_conn`; `close()`. Thin delegation to `FinanceRepository`.

  — done when: `uv run mypy --strict src` passes; `FinanceStore(settings, FakeKeyProvider(owner_unlocked=False))` raises `ScopeLockedError` on first access; `FakeKeyProvider(owner_unlocked=True)` round-trips `create_account` + `get_account` on the fallback sqlite.

- [ ] **Task 5: Tools + manifest (awareness phase, OWNER_PRIVATE, no hooks, no GATE)** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py`, `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py`, `/Users/artemis-build/artemis/src/artemis/modules/finance/__init__.py` —

  Tool callables (ADR-016: every `callable_ref` is `async def`; store calls stay sync inside). Pydantic args/return models. ALL `ActionRisk.READ`/`WRITE`, ALL auto (no gating — finance.md: internal local-ledger edits only). Module-level `_store` + `init_finance_tools(store)`.

  Awareness tools (~10):
  | name (bare) | args | return | risk |
  |---|---|---|---|
  | `spend_summary` | `start: str, end: str, group_by: str = "category"` | `SpendSummaryResult(rows: list[dict])` | READ |
  | `spend_total` | `start: str, end: str` | `SpendTotalResult(total: str)` | READ |
  | `transaction_list` | `start: str \| None, end: str \| None, category_id: str \| None, txn_type: str \| None` | `TxnListResult(transactions: list[dict])` | READ |
  | `transaction_get` | `id: str` | `TxnResult(transaction: dict \| None)` | READ |
  | `transaction_add` | `txn_date: str, amount: str, merchant: str \| None, category_id: str \| None, txn_type: str = "purchase", instrument_account_id: str \| None` | `TxnCreatedResult(transaction_id: str)` | WRITE |
  | `transaction_update` | `id: str, merchant: str \| None, category_id: str \| None, txn_type: str \| None, amount: str \| None, notes: str \| None` | `OkResult` | WRITE |
  | `transaction_recategorize` | `id: str, category_id: str` | `OkResult` | WRITE |
  | `category_list` | _(none)_ | `CategoryListResult(categories: list[dict])` | READ |
  | `category_add` | `name: str` | `CategoryCreatedResult(category_id: str)` | WRITE |
  | `account_list` | `include_archived: bool = False` | `AccountListResult(accounts: list[dict])` | READ |
  | `account_add` | `name: str, account_type: str, currency: str = "SGD"` | `AccountCreatedResult(account_id: str)` | WRITE |
  | `csv_import` | `account_id: str, profile_name: str, rows_json: str` | `CsvImportResult(imported: int, skipped_duplicates: int, errors: list[str])` | WRITE |

  (`amount` crosses the tool boundary as a decimal STRING — Pydantic validates it parses to `Decimal`; never a float field.)

  `finance_manifest(store) -> ModuleManifest`: `name="finance"`, `data_scope=DataScope.OWNER_PRIVATE`, `permissions=Permissions(owner=True, guest=False)` (**guest sees NOTHING financial** — finance.md), `proactive_hooks=[]` (hooks are FIN-c), `ui=UiSurface(kind="card")` (Self-cluster glance card per UI lock; if `kind="card"` invalid in M1-a, use the existing valid value + FLAG for Wave U).

  — done when: `uv run mypy --strict src` passes; `finance_manifest(store).name == "finance"`; `data_scope == OWNER_PRIVATE`; `permissions.guest is False`; `proactive_hooks == []`; all tool callables are coroutine functions; `amount` args reject a non-decimal string.

- [ ] **Task 6 (GATED — on-hardware):** Real keyed SQLCipher open of `finance.db` on the Mini (broker vault mounted, owner unlocked): `FinanceStore(get_settings(), BrokerKeyProvider(...)).add_transaction(...)` succeeds; wrong key fails; `finance.db` not plaintext-readable; `PRAGMA foreign_keys = ON` active. — done when: recorded in handoff.

- [ ] **Task 7: Tests** — files: `/Users/artemis-build/artemis/tests/test_finance_core.py` — typed pytest, `FakeKeyProvider(owner_unlocked=True)` + `Settings(data_root=tmp_path)` + plain-sqlite fallback.

  - **Schema:** 7 tables created; 14 seed categories present with `is_seed=1`; idempotent re-call no dup; `amount` columns TEXT; `raw_ref` UNIQUE partial index present.
  - **Account/category/txn CRUD** round-trips.
  - **Spend excludes transfers/settlements:** add a purchase $20, a refund $5, a transfer $1000, a settlement $1200 → `total_spend == Decimal("15.00")` (20 − 5; transfer + settlement excluded); `spend_summary(group_by="category")` reflects only purchase/refund.
  - **Money fidelity:** `add_transaction(amount=Decimal("19.99"))` → `get_transaction` returns `Decimal("19.99")` (no FP drift; stored as TEXT).
  - **L0 idempotency:** `add_transaction(..., raw_ref="x:1")` twice → one row, same id returned.
  - **CSV import:** 3-row fixture imports 3; re-import → 0 imported / 3 skipped; bad-date row counted in `errors`, others import; saved profile round-trips.
  - **ScopeLockedError** on locked provider.
  - **Manifest shape:** `name="finance"`, OWNER_PRIVATE, guest=False, no hooks, tool callables async.
  - **No-cloud-import guard:** assert `artemis.modules.finance` imports no `ModelPort`/cloud adapter (the always-local structural wall) — e.g. inspect the module's imports or assert `ModelPort` not referenced.

  — done when: `uv run pytest -q tests/test_finance_core.py` passes AND `uv run mypy --strict src tests/test_finance_core.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/__init__.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/schema.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/repository.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/store.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/csv_import.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` |
| Create | `/Users/artemis-build/artemis/tests/test_finance_core.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_finance_core.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_finance_core.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/finance/**`, `tests/test_finance_core.py` |
| `git commit` | `"feat: FIN-a finance ledger core — end-state SQLCipher schema, manual + CSV import, awareness manifest"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir resolution |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure CRUD + CSV parse; no model, no network (always-local) |

## Specialist Context

### Security

- **Owner-private at rest:** `finance.db` opens via M2-c `sqlcipher_open` with the broker DEK; `ScopeLockedError` propagates; `key.as_hex()` is a local var inside `_connect()` only (never `self`/module/log). Guest mode sees nothing (manifest `guest=False`).
- **Always-local (ADR-022/F-D13):** FIN-a imports no model/cloud port — the structural wall. The acceptance criteria assert no `ModelPort` import. Ledger data NEVER reaches Codex/cloud, here or downstream.
- **Money as Decimal-text:** amounts are `Decimal` in Python, TEXT in SQLite — no float (avoids FP error in financial totals). Tool-boundary amounts are strings validated to parse as `Decimal`.
- **Parameterised SQL + FK-on + CHECK constraints:** the injection surface is closed; `txn_type`/`source`/`status`/`cadence` validated against StrEnum + CHECK before INSERT.
- **No external-effect surface:** all writes are internal local-ledger edits — no GATE/staging. The S$500 fraud figure is a FIN-c notification threshold, NOT a FIN-a gate (finance.md confirms).
- **`raw_ref` UNIQUE** is the L0 ingest-idempotency wall (re-processing the same email/CSV line never double-inserts) — load-bearing for FIN-b's extraction dedup.

[apex-security/apex-data review (cross_model_review): confirm the end-state schema freeze is complete (no v1→v2 migration needed); confirm `instrument_account_id` FK to `account` (F-D11); confirm money is never float anywhere; confirm no model/cloud import in the finance package.]

### Performance

- Personal-finance scale = thousands of txns. Plain parameterised SQL + the date/category/merchant indexes are right; no vector/FTS. `spend_summary` is an indexed GROUP BY over a date range — sub-ms at scale. One `FinanceRepository(conn)` per call (M8-d-a precedent) — negligible.

### Accessibility

(none — no frontend in FIN-a; the Self-cluster finance card + dashboard is Wave U / CLIENT)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/finance/*.py` | Docstring all exports; document the end-state-schema-awareness-slice split, the transfer/settlement-excluded-from-spend rule, the money-as-Decimal-text convention, the `raw_ref` L0 idempotency, the always-local wall |
| Data model | `docs/technical/architecture/data-model.md` | Add the Finance entities (account/transaction/subscription/bill/category/csv_profile) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_finance_core.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_finance_core.py` → verify: 7 tables + 14 seed categories; account/category/txn CRUD; spend excludes transfers+settlements and subtracts refunds; money round-trips as Decimal (no FP drift); `raw_ref` L0 idempotency; CSV import + re-import-skips + bad-row-continues + saved-profile round-trip; ScopeLockedError on locked provider; manifest OWNER_PRIVATE/guest=False/no-hooks; no model/cloud import.
- [ ] `uv run python -c "from artemis.modules.finance import finance_manifest, FinanceStore, TransactionType; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) real keyed SQLCipher open; wrong key fails; not plaintext-readable; FK-on → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
