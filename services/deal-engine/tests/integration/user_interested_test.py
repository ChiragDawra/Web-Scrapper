"""`USER_INTERESTED` against Postgres — Sprint 3 Task 3.6.

The unit suite covers which taps are legal. This covers what the unit suite
cannot: that the row really moves, that a rejected tap leaves it alone, and
that two taps racing on one deal produce one transition — which is the point
of reading the deal `FOR UPDATE`.

Skipped, not failed, without Postgres. These tests commit and delete their own
rows in foreign-key order, because the row lock they exercise only means
anything across two real transactions.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Json
from src.handlers.event_handlers import USER_INTERESTED, handle_user_interested
from src.repositories.deal_repo import DealRepository

from libs.enums import DealStatus, EventProducerService, MarketplaceCode
from libs.event_bus.consumer import ReceivedEvent
from libs.event_bus.envelope import Envelope

POSTGRES_TEST_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://businessscrapper:businessscrapper@127.0.0.1:5432/businessscrapper",
)

BREAKDOWN = {
    "discount_score": 31.25,
    "brand_score": 18.75,
    "rating_score": 14.06,
    "velocity_score": 25.0,
    "weights_version": "builtin-v1",
}


def connect() -> psycopg.Connection:
    return psycopg.connect(POSTGRES_TEST_URL, connect_timeout=3)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    try:
        connection = connect()
    except psycopg.Error as exc:
        pytest.skip(f"Postgres unavailable at {POSTGRES_TEST_URL}: {exc}")
    with connection:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('public.deals')")
            if cur.fetchone()[0] is None:  # type: ignore[index]
                pytest.skip("run `alembic upgrade head` in infra/postgres first")
        yield connection


@pytest.fixture
def listing_id(conn: psycopg.Connection) -> Iterator[UUID]:
    """A committed listing (and its product and marketplace) to hang deals off."""
    external_id = f"B0T4P{uuid4().hex[:8].upper()}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO marketplaces (code, display_name, base_url)
            VALUES (%s, %s, %s) ON CONFLICT (code) DO NOTHING
            """,
            (str(MarketplaceCode.AMAZON), "Amazon India", "https://www.amazon.in"),
        )
        cur.execute("SELECT id FROM marketplaces WHERE code = %s", (str(MarketplaceCode.AMAZON),))
        marketplace_id = cur.fetchone()[0]  # type: ignore[index]
        cur.execute(
            "INSERT INTO products (canonical_title) VALUES (%s) RETURNING id",
            ("Sony WH-1000XM5 Wireless Headphones",),
        )
        product_id = cur.fetchone()[0]  # type: ignore[index]
        cur.execute(
            """
            INSERT INTO listings (
              product_id, marketplace_id, external_listing_id, url, current_price, in_stock
            )
            VALUES (%s, %s, %s, %s, %s, true) RETURNING id
            """,
            (
                product_id,
                marketplace_id,
                external_id,
                f"https://www.amazon.in/dp/{external_id}",
                100000,
            ),
        )
        new_listing_id = cur.fetchone()[0]  # type: ignore[index]
    conn.commit()

    yield new_listing_id

    cleanup = connect()
    with cleanup, cleanup.cursor() as cur:
        cur.execute("DELETE FROM deals WHERE listing_id = %s", (new_listing_id,))
        cur.execute("DELETE FROM price_history WHERE listing_id = %s", (new_listing_id,))
        cur.execute("DELETE FROM listings WHERE id = %s", (new_listing_id,))
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
    cleanup.close()


def insert_deal(
    conn: psycopg.Connection,
    listing_id: UUID,
    status: DealStatus,
    *,
    expires_in: timedelta = timedelta(hours=6),
) -> UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO deals (
              listing_id, status, score, score_breakdown,
              detected_price, reference_price, discount_pct, expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (
                listing_id,
                str(status),
                Decimal("89.06"),
                Json(BREAKDOWN),
                100000,
                200000,
                Decimal("50.00"),
                datetime.now(UTC) + expires_in,
            ),
        )
        deal_id = cur.fetchone()[0]  # type: ignore[index]
    conn.commit()
    return deal_id


def tap(deal_id: UUID) -> ReceivedEvent:
    return ReceivedEvent(
        stream=USER_INTERESTED,
        entry_id="1-0",
        envelope=Envelope.new(
            event_type=USER_INTERESTED,
            producer_service=EventProducerService.TELEGRAM_BOT,
            payload={"deal_id": str(deal_id), "telegram_user_id": str(uuid4())},
        ),
    )


def status_of(conn: psycopg.Connection, deal_id: UUID) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM deals WHERE id = %s", (deal_id,))
        row = cur.fetchone()
    assert row is not None
    return str(row[0])


def test_a_tap_moves_the_row_to_interested(conn: psycopg.Connection, listing_id: UUID) -> None:
    deal_id = insert_deal(conn, listing_id, DealStatus.DEAL_SENT)

    result = handle_user_interested(conn, None, tap(deal_id))  # type: ignore[arg-type]
    conn.commit()

    assert result.applied is True
    assert status_of(conn, deal_id) == str(DealStatus.INTERESTED)


def test_a_tap_on_an_expired_deal_leaves_it_expired(
    conn: psycopg.Connection, listing_id: UUID
) -> None:
    """Task 3.6's Definition of Done, against the real row."""
    deal_id = insert_deal(conn, listing_id, DealStatus.EXPIRED)

    result = handle_user_interested(conn, None, tap(deal_id))  # type: ignore[arg-type]
    conn.commit()

    assert result.applied is False
    assert status_of(conn, deal_id) == str(DealStatus.EXPIRED)


def test_a_tap_after_expires_at_expires_the_row(conn: psycopg.Connection, listing_id: UUID) -> None:
    deal_id = insert_deal(conn, listing_id, DealStatus.DEAL_SENT, expires_in=timedelta(seconds=-1))

    result = handle_user_interested(conn, None, tap(deal_id))  # type: ignore[arg-type]
    conn.commit()

    assert result.applied is False
    assert status_of(conn, deal_id) == str(DealStatus.EXPIRED)


def test_concurrent_taps_apply_once(conn: psycopg.Connection, listing_id: UUID) -> None:
    """Two workers, one deal, one transition — the `FOR UPDATE` read is why."""
    deal_id = insert_deal(conn, listing_id, DealStatus.DEAL_SENT)
    start = threading.Barrier(2)
    outcomes: list[Any] = []
    lock = threading.Lock()

    def worker() -> None:
        own = connect()
        try:
            start.wait(timeout=5)
            result = handle_user_interested(own, None, tap(deal_id))  # type: ignore[arg-type]
            own.commit()
            with lock:
                outcomes.append(result)
        finally:
            own.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(outcomes) == 2
    assert sum(1 for outcome in outcomes if outcome.applied) == 1
    assert status_of(conn, deal_id) == str(DealStatus.INTERESTED)


def test_an_unknown_deal_touches_nothing(conn: psycopg.Connection) -> None:
    result = handle_user_interested(conn, None, tap(uuid4()))  # type: ignore[arg-type]
    conn.rollback()

    assert result.applied is False
    assert DealRepository(conn).get_by_id(result.deal_id) is None
