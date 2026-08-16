"""`DEAL_REVALIDATION_REQUEST` to `DEAL_REVALIDATED` end to end — Sprint 5 Task 5.2.

Definition of Done: "Request-to-response completes within 30s budget locally."
`test_a_request_is_answered_inside_the_budget` is that, measured on a real Redis
stream through this service's own consumer, with the elapsed wall-clock asserted
rather than assumed.

Needs both Redis (logical DB 15, flushed per test — never DB 0) and Postgres with
`alembic upgrade head` applied; skipped, not failed, without either. Postgres is
here only for `processed_events` — this service owns no tables of its own.

These tests commit, because the handler does: `process_once` writes the dedup
mark, and a test that rolled back would be testing a code path that never runs.
The marks written are deleted afterwards, keyed by the events this test
published.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from redis import Redis
from redis.exceptions import RedisError
from src.config import PRODUCER_SERVICE
from src.handlers.event_handlers import (
    DEAL_REVALIDATED,
    DEAL_REVALIDATION_REQUEST,
    DEAL_SCORED,
)
from src.main import handle_event
from src.services.deal_reference import DealReferenceStore
from src.services.listing_source import ListingSnapshot

from libs.enums import EventProducerService
from libs.event_bus.consumer import EventConsumer
from libs.event_bus.envelope import Envelope
from libs.event_bus.publisher import EventPublisher
from libs.validation_rules import REVALIDATION_TIMEOUT_SECONDS

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://127.0.0.1:6379/15")
POSTGRES_TEST_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://businessscrapper:businessscrapper@127.0.0.1:5432/businessscrapper",
)

SCORED_PRICE = 799_900


class StubSource:
    """A live read that always answers. The transport is out of scope here."""

    def __init__(self, *, current_price: int = SCORED_PRICE, in_stock: bool = True) -> None:
        self.current_price = current_price
        self.in_stock = in_stock

    def read(self, listing_id: UUID) -> ListingSnapshot:
        return ListingSnapshot(
            listing_id=listing_id,
            current_price=self.current_price,
            in_stock=self.in_stock,
            observed_at=datetime.now(UTC),
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
            cur.execute("SELECT to_regclass('public.processed_events')")
            if cur.fetchone()[0] is None:  # type: ignore[index]
                pytest.skip("run `alembic upgrade head` in infra/postgres first")
        connection.commit()
        try:
            yield connection
        finally:
            with connection.cursor() as cur:
                cur.execute(
                    "DELETE FROM processed_events WHERE consumer_service = %s",
                    (str(PRODUCER_SERVICE),),
                )
            connection.commit()


def scored_payload(deal_id: UUID, listing_id: UUID) -> dict[str, object]:
    return {
        "deal_id": str(deal_id),
        "listing_id": str(listing_id),
        "marketplace": "AMAZON",
        "score": 88.0,
        "score_breakdown": {
            "discount_score": 40.0,
            "brand_score": 20.0,
            "rating_score": 15.0,
            "velocity_score": 13.0,
            "weights_version": "builtin-v1",
        },
        "detected_price": SCORED_PRICE,
        "reference_price": SCORED_PRICE * 2,
        "discount_pct": 50.0,
        "expires_at": "2026-06-02T12:00:00+00:00",
    }


def publish_flow(publisher: EventPublisher, deal_id: UUID, listing_id: UUID) -> None:
    """The two upstream events, in the order the system produces them."""
    publisher.publish(
        Envelope.new(
            event_type=DEAL_SCORED,
            producer_service=EventProducerService.DEAL_ENGINE,
            payload=scored_payload(deal_id, listing_id),
        )
    )
    publisher.publish(
        Envelope.new(
            event_type=DEAL_REVALIDATION_REQUEST,
            producer_service=EventProducerService.TELEGRAM_BOT,
            payload={
                "deal_id": str(deal_id),
                "listing_id": str(listing_id),
                # Q15: the request's correlation_id is the deal_id.
                "correlation_id": str(deal_id),
            },
            correlation_id=deal_id,
        )
    )


def drain(
    conn: psycopg.Connection,
    redis_client: Redis,
    publisher: EventPublisher,
    source: StubSource,
    *,
    batches: int = 2,
) -> int:
    """Run this service's own consumer over whatever is on the streams."""
    consumer = EventConsumer(
        redis_client,
        consumer_service=PRODUCER_SERVICE,
        event_types=[DEAL_SCORED, DEAL_REVALIDATION_REQUEST],
        consumer_name="revalidation-service-itest",
        block_ms=200,
    )
    consumer.ensure_groups()
    return consumer.consume(
        lambda event: handle_event(
            conn,
            publisher,
            event,
            references=references,
            source=source,
            budget_seconds=REVALIDATION_TIMEOUT_SECONDS,
        ),
        max_batches=batches,
    )


#: One projection per test module run; each test uses its own deal ids, so they
#: cannot collide. Module-level rather than a fixture because `drain` closes over
#: it, exactly as `run()` closes over the store it builds at startup.
references = DealReferenceStore()


def read_back(redis_client: Redis) -> list[dict[str, object]]:
    """The `DEAL_REVALIDATED` events on the bus, read as the Bot would."""
    consumer = EventConsumer(
        redis_client,
        consumer_service=EventProducerService.TELEGRAM_BOT,
        event_types=[DEAL_REVALIDATED],
        consumer_name="bot-itest",
        block_ms=200,
    )
    consumer.ensure_groups()
    return [event.envelope.to_dict() for event in consumer.read()]


def test_a_request_is_answered_inside_the_budget(
    conn: psycopg.Connection, redis_client: Redis
) -> None:
    """Task 5.2's Definition of Done, with the elapsed time actually measured."""
    publisher = EventPublisher(redis_client)
    deal_id, listing_id = uuid4(), uuid4()
    publish_flow(publisher, deal_id, listing_id)

    started = time.monotonic()
    handled = drain(conn, redis_client, publisher, StubSource(current_price=805_000))
    elapsed = time.monotonic() - started

    assert handled == 2
    assert elapsed < REVALIDATION_TIMEOUT_SECONDS
    [answer] = read_back(redis_client)
    assert answer["payload"]["deal_id"] == str(deal_id)  # type: ignore[index]
    # 805000 against 799900 is 0.64%, inside the 2% tolerance.
    assert answer["payload"]["changed"] is False  # type: ignore[index]
    assert answer["correlation_id"] == str(deal_id)


def test_a_price_move_beyond_tolerance_is_reported_as_changed(
    conn: psycopg.Connection, redis_client: Redis
) -> None:
    publisher = EventPublisher(redis_client)
    deal_id, listing_id = uuid4(), uuid4()
    publish_flow(publisher, deal_id, listing_id)

    drain(conn, redis_client, publisher, StubSource(current_price=899_900))

    [answer] = read_back(redis_client)
    assert answer["payload"]["changed"] is True  # type: ignore[index]
    assert answer["payload"]["current_price"] == 899_900  # type: ignore[index]


def test_the_dedup_mark_is_written_for_this_consumer(
    conn: psycopg.Connection, redis_client: Redis
) -> None:
    """`EVENT_SCHEMAS.md` §1: a redelivered `event_id` must not be answered twice."""
    publisher = EventPublisher(redis_client)
    deal_id, listing_id = uuid4(), uuid4()
    publish_flow(publisher, deal_id, listing_id)

    drain(conn, redis_client, publisher, StubSource())

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM processed_events WHERE consumer_service = %s",
            (str(PRODUCER_SERVICE),),
        )
        row = cur.fetchone()
    assert row is not None and row[0] >= 2


def test_a_slow_read_publishes_nothing(conn: psycopg.Connection, redis_client: Redis) -> None:
    """Task 5.3 on the real bus: past the deadline, the stream stays empty."""
    publisher = EventPublisher(redis_client)
    deal_id, listing_id = uuid4(), uuid4()
    publish_flow(publisher, deal_id, listing_id)

    consumer = EventConsumer(
        redis_client,
        consumer_service=PRODUCER_SERVICE,
        event_types=[DEAL_SCORED, DEAL_REVALIDATION_REQUEST],
        consumer_name="revalidation-service-itest-slow",
        block_ms=200,
    )
    consumer.ensure_groups()
    # A budget of zero seconds is a closed window without a 30s wait: `expired()`
    # is `>=`, so nothing is read and nothing is emitted.
    consumer.consume(
        lambda event: handle_event(
            conn,
            publisher,
            event,
            references=references,
            source=StubSource(),
            budget_seconds=0,
        ),
        max_batches=2,
    )

    assert read_back(redis_client) == []
