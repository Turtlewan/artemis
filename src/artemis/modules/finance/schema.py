"""Locked Finance ledger schema.

Finance is always-local owner-private data. Money is represented as
``Decimal`` in Python and stored as TEXT decimal strings in SQLite.
"""

from __future__ import annotations

import sqlite3
from enum import StrEnum

from artemis.memory.schema import now_iso

SCHEMA_VERSION = "1"

SG_SEED_CATEGORIES = (
    "Food & Dining",
    "Groceries",
    "Transport",
    "Shopping",
    "Bills & Utilities",
    "Subscriptions",
    "Health",
    "Entertainment",
    "Travel",
    "Transfers",
    "Income",
    "Education",
    "Insurance",
    "Other",
)


class TransactionType(StrEnum):
    """Transaction types stored in the ledger."""

    PURCHASE = "purchase"
    REFUND = "refund"
    TRANSFER = "transfer"
    SETTLEMENT = "settlement"


class TransactionSource(StrEnum):
    """Sources allowed to write ledger transactions."""

    EMAIL = "email"
    MANUAL = "manual"
    CSV = "csv"


class BillStatus(StrEnum):
    """Bill lifecycle states."""

    OPEN = "open"
    PAID = "paid"
    OVERDUE = "overdue"


class SubscriptionCadence(StrEnum):
    """Subscription recurrence cadences."""

    MONTHLY = "monthly"
    YEARLY = "yearly"
    WEEKLY = "weekly"
    QUARTERLY = "quarterly"


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the Finance schema idempotently."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            account_type TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'SGD',
            institution TEXT,
            current_balance TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "transaction" (
            id TEXT PRIMARY KEY,
            txn_date TEXT NOT NULL,
            amount TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'SGD',
            amount_original TEXT,
            currency_original TEXT,
            merchant TEXT,
            category_id TEXT REFERENCES category(id),
            txn_type TEXT NOT NULL DEFAULT 'purchase'
                CHECK(txn_type IN ('purchase','refund','transfer','settlement')),
            source TEXT NOT NULL CHECK(source IN ('email','manual','csv')),
            instrument_account_id TEXT REFERENCES account(id),
            raw_ref TEXT,
            confidence REAL,
            notes TEXT,
            settles_period TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute('CREATE INDEX IF NOT EXISTS idx_txn_date ON "transaction"(txn_date)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_txn_category ON "transaction"(category_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_txn_merchant ON "transaction"(merchant)')
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_txn_instrument ON "transaction"(instrument_account_id)'
    )
    conn.execute('CREATE INDEX IF NOT EXISTS idx_txn_type ON "transaction"(txn_type)')
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_txn_raw_ref
        ON "transaction"(raw_ref)
        WHERE raw_ref IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription (
            id TEXT PRIMARY KEY,
            merchant TEXT NOT NULL,
            cadence TEXT NOT NULL CHECK(cadence IN ('monthly','yearly','weekly','quarterly')),
            amount TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'SGD',
            next_renewal TEXT,
            last_seen_price TEXT,
            last_seen_date TEXT,
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_subscription_merchant ON subscription(merchant)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_renewal ON subscription(next_renewal)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bill (
            id TEXT PRIMARY KEY,
            payee TEXT NOT NULL,
            due_date TEXT NOT NULL,
            amount TEXT,
            currency TEXT NOT NULL DEFAULT 'SGD',
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','paid','overdue')),
            linked_task_ref TEXT,
            raw_ref TEXT,
            paid_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bill_due ON bill(due_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bill_status ON bill(status)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS category (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            is_seed INTEGER NOT NULL DEFAULT 0 CHECK(is_seed IN (0,1)),
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS csv_profile (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            mapping_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    created_at = now_iso()
    conn.executemany(
        """
        INSERT OR IGNORE INTO category (id, name, is_seed, created_at)
        VALUES (?, ?, 1, ?)
        """,
        [(f"seed:{name}", name, created_at) for name in SG_SEED_CATEGORIES],
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ("schema_version", SCHEMA_VERSION),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ("created_at", created_at),
    )
    conn.commit()
