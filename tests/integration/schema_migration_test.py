"""Migrated schema vs. the contract — Sprint 1 Task 1.6.

Runs against the compose Postgres (`docker compose up postgres`) after
`alembic upgrade head`. Skipped, not failed, when Postgres is unreachable or
the migration has not been applied, so a lint-and-unit-test-only CI job stays
green.

Asserts the *shape* the contract fixes and that a review diff cannot catch by
eye: the exact table set (`DATABASE_SCHEMA.md` §1-§18), the exact enum type set
with their exact members (`ENUMS.md`), and that every enum type agrees member
for member with the Python `StrEnum` of the same name in `libs.enums`. A column
added to one side only still needs the line-by-line read; a table or enum value
drifting does not.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from libs import enums

POSTGRES_TEST_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://businessscrapper:businessscrapper@127.0.0.1:5432/businessscrapper",
)

# DATABASE_SCHEMA.md §1-§18, in document order.
EXPECTED_TABLES = {
    "brands",
    "marketplaces",
    "products",
    "listings",
    "price_history",
    "deals",
    "telegram_users",
    "user_interests",
    "accounts",
    "orders",
    "order_items",
    "purchase_tasks",
    "events",
    "inventory_items",
    "bot_conversations",
    "bot_messages",
    "bot_audit_log",
    "processed_events",
}

# ENUMS.md — Postgres type name -> the `libs.enums` class carrying its members.
ENUM_TYPE_TO_PYTHON = {
    "marketplace_code": enums.MarketplaceCode,
    "deal_status": enums.DealStatus,
    "order_status": enums.OrderStatus,
    "order_item_status": enums.OrderItemStatus,
    "purchase_task_status": enums.PurchaseTaskStatus,
    "account_status": enums.AccountStatus,
    "account_health_band": enums.AccountHealthBand,
    "conversation_state": enums.ConversationState,
    "user_interest_action": enums.UserInterestAction,
    "inventory_item_status": enums.InventoryItemStatus,
    "event_producer_service": enums.EventProducerService,
    "currency_code": enums.CurrencyCode,
    "error_severity": enums.ErrorSeverity,
    "brand_tier": enums.BrandTier,
}


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection]:
    try:
        conn = psycopg.connect(POSTGRES_TEST_URL, connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"Postgres unavailable at {POSTGRES_TEST_URL}: {exc}")
    with conn:
        if _current_revision(conn) != "0002_full_schema":
            pytest.skip("run `alembic upgrade head` in infra/postgres first")
        yield conn


def _current_revision(conn: psycopg.Connection) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.alembic_version')")
        if cur.fetchone()[0] is None:  # type: ignore[index]
            return None
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
    return row[0] if row else None


def test_exactly_the_contracted_tables_exist(connection: psycopg.Connection) -> None:
    """No missing table, and no table this repo invented on the side."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        tables = {row[0] for row in cur.fetchall()}

    assert tables - {"alembic_version"} == EXPECTED_TABLES


def test_exactly_the_contracted_enum_types_exist(connection: psycopg.Connection) -> None:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT t.typname FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid"
        )
        types = {row[0] for row in cur.fetchall()}

    assert types == set(ENUM_TYPE_TO_PYTHON)


@pytest.mark.parametrize("type_name", sorted(ENUM_TYPE_TO_PYTHON))
def test_enum_members_match_libs_enums(connection: psycopg.Connection, type_name: str) -> None:
    """One registry, two renderings: the Postgres type and the `StrEnum` cannot drift apart."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = %s ORDER BY e.enumsortorder",
            (type_name,),
        )
        labels = [row[0] for row in cur.fetchall()]

    assert labels == [member.value for member in ENUM_TYPE_TO_PYTHON[type_name]]
