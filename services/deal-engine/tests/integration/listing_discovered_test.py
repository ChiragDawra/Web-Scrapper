"""`LISTING_DISCOVERED` end to end — Sprint 3 Task 3.5.

Definition of Done: "End-to-end published `LISTING_DISCOVERED` produces
`DEAL_SCORED` with correct `marketplace`."
`test_a_published_listing_produces_a_deal_scored_event` is that: a real
connector-shaped event goes onto a real Redis stream, the Deal Engine's own
consumer reads it, and the resulting `DEAL_SCORED` is read back off the bus.

Needs both Redis (logical DB 15, flushed per test — never DB 0) and Postgres
with `alembic upgrade head` applied; skipped, not failed, without either.

These tests commit, because the handler does: `process_once` writes the dedup
mark in the same transaction as the deal, and a test that rolled back would be
testing a code path that never runs. Everything written is deleted afterwards,
keyed by the per-test listing.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest
from redis import Redis
from redis.exceptions import RedisError
from src.config import PRODUCER_SERVICE
from src.handlers.event_handlers import DEAL_SCORED, LISTING_DISCOVERED
from src.main import handle_event
from src.services.scorer import DEFAULT_CONFIG

from libs.canonical_models import CanonicalProduct
from libs.enums import EventProducerService, MarketplaceCode
from libs.event_bus.consumer import EventConsumer
from libs.event_bus.envelope import Envelope
from libs.event_bus.publisher import EventPublisher

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://127.0.0.1:6379/15")
POSTGRES_TEST_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://businessscrapper:businessscrapper@127.0.0.1:5432/businessscrapper",
)


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    client = Redis.from_url(REDIS_TEST_URL)
    try:
        client.ping()
    except RedisError as exc:
        pytest.skip(f"Redis unavailable at {REDIS_TEST_URL}: {exc}")
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()
        client.close()


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    try:
        connection = psycopg.connect(POSTGRES_TEST_URL, connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"Postgres unavailable at {POSTGRES_TEST_URL}: {exc}")
    with connection:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('public.deals')")
            if cur.fetchone()[0] is None:  # type: ignore[index]
                pytest.skip("run `alembic upgrade head` in infra/postgres first")
            _seed_marketplace(cur)
        connection.commit()
        try:
            yield connection
        finally:
            connection.rollback()


def _seed_marketplace(cur: psycopg.Cursor) -> None:
    """§2 says marketplaces are seeded; no seed migration exists yet, so do it here."""
    cur.execute(
        """
        INSERT INTO marketplaces (code, display_name, base_url)
        VALUES (%s, %s, %s) ON CONFLICT (code) DO NOTHING
        """,
        (str(MarketplaceCode.AMAZON), "Amazon India", "https://www.amazon.in"),
    )


@pytest.fixture
def asin() -> Iterator[str]:
    """A unique external listing id, with every row it produces removed afterwards."""
    external_id = f"B0E2E{uuid4().hex[:8].upper()}"
    yield external_id

    conn = psycopg.connect(POSTGRES_TEST_URL, connect_timeout=3)
    with conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, product_id FROM listings WHERE external_listing_id = %s", (external_id,)
        )
        rows = cur.fetchall()
        for listing_id, product_id in rows:
            cur.execute("DELETE FROM deals WHERE listing_id = %s", (listing_id,))
            cur.execute("DELETE FROM price_history WHERE listing_id = %s", (listing_id,))
            cur.execute("DELETE FROM listings WHERE id = %s", (listing_id,))
            cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
    conn.close()


def product(asin: str, **overrides: object) -> CanonicalProduct:
    """A listing that clears the default thresholds: 50% off, well reviewed."""
    base: dict[str, object] = {
        "canonical_title": "Sony WH-1000XM5 Wireless Headphones",
        "marketplace": MarketplaceCode.AMAZON,
        "external_listing_id": asin,
        "url": f"https://www.amazon.in/dp/{asin}",
        "price": 100000,
        "mrp": 200000,
        "in_stock": True,
        "rating": 4.6,
        "review_count": 1200,
        "brand_name": "Sony",
    }
    base.update(overrides)
    return CanonicalProduct(**base)  # type: ignore[arg-type]


def listing_event(product: CanonicalProduct) -> Envelope:
    """What the marketplace-connector publishes (`EVENT_SCHEMAS.md` §2)."""
    return Envelope.new(
        event_type=LISTING_DISCOVERED,
        producer_service=EventProducerService.MARKETPLACE_CONNECTOR,
        payload={"product": product.to_dict()},
    )


def drain(conn: psycopg.Connection, redis: Redis, *, max_batches: int = 1) -> list[object]:
    """Consume whatever is on `LISTING_DISCOVERED` through the real handler path."""
    publisher = EventPublisher(redis)
    consumer = EventConsumer(
        redis,
        consumer_service=PRODUCER_SERVICE,
        event_types=[LISTING_DISCOVERED],
        consumer_name="test-worker",
        block_ms=200,
    )
    consumer.ensure_groups()
    results: list[object] = []
    consumer.consume(
        lambda event: results.append(
            handle_event(conn, publisher, event, scoring_config=DEFAULT_CONFIG)
        ),
        max_batches=max_batches,
    )
    return results


def published_deals(redis: Redis) -> list[dict[str, object]]:
    reader = EventConsumer(
        redis,
        consumer_service=EventProducerService.TELEGRAM_BOT,
        event_types=[DEAL_SCORED],
        consumer_name="test-reader",
        block_ms=200,
    )
    reader.ensure_groups()
    return [dict(event.envelope.payload) for event in reader.read()]


def test_a_published_listing_produces_a_deal_scored_event(
    conn: psycopg.Connection, redis_client: Redis, asin: str
) -> None:
    EventPublisher(redis_client).publish(listing_event(product(asin)))

    drain(conn, redis_client)

    deals = published_deals(redis_client)
    assert len(deals) == 1
    payload = deals[0]
    assert payload["marketplace"] == str(MarketplaceCode.AMAZON)
    assert payload["detected_price"] == 100000
    assert payload["reference_price"] == 200000
    assert UUID(str(payload["deal_id"]))
    assert UUID(str(payload["listing_id"]))


def test_the_listing_and_its_price_are_persisted(
    conn: psycopg.Connection, redis_client: Redis, asin: str
) -> None:
    EventPublisher(redis_client).publish(listing_event(product(asin)))

    drain(conn, redis_client)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, current_price, in_stock FROM listings WHERE external_listing_id = %s",
            (asin,),
        )
        listing = cur.fetchone()
        assert listing is not None
        cur.execute("SELECT count(*) FROM price_history WHERE listing_id = %s", (listing[0],))
        observations = cur.fetchone()

    assert listing[1] == 100000
    assert listing[2] is True
    assert observations is not None
    assert observations[0] == 1


def test_a_below_threshold_listing_emits_nothing(
    conn: psycopg.Connection, redis_client: Redis, asin: str
) -> None:
    """`VALIDATION_RULES.md` §2: silent skip — ingested, scored, not announced."""
    EventPublisher(redis_client).publish(listing_event(product(asin, price=195000)))

    drain(conn, redis_client)

    assert published_deals(redis_client) == []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM listings WHERE external_listing_id = %s",
            (asin,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 1, "the listing is still ingested; only the deal is skipped"


def test_a_redelivered_event_is_not_scored_twice(
    conn: psycopg.Connection, redis_client: Redis, asin: str
) -> None:
    """`processed_events` dedup, committed with the deal it produced."""
    envelope = listing_event(product(asin))
    publisher = EventPublisher(redis_client)
    publisher.publish(envelope)
    publisher.publish(envelope)  # same event_id: a redelivery, not a new listing

    drain(conn, redis_client)

    assert len(published_deals(redis_client)) == 1


def test_a_second_scan_of_the_same_listing_does_not_open_a_second_deal(
    conn: psycopg.Connection, redis_client: Redis, asin: str
) -> None:
    """Two poll cycles, two events, one open deal (`DATABASE_SCHEMA.md` §6)."""
    publisher = EventPublisher(redis_client)
    publisher.publish(listing_event(product(asin)))
    publisher.publish(listing_event(product(asin, price=99000)))

    drain(conn, redis_client, max_batches=2)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM deals d
            JOIN listings l ON l.id = d.listing_id
            WHERE l.external_listing_id = %s
            """,
            (asin,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 1
    assert len(published_deals(redis_client)) == 1
