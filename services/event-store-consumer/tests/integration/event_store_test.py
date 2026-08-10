"""Event Store Consumer end to end — Sprint 1 Task 1.8.

Definition of Done: "Publishing one event of each of the 12 types yields exactly
12 new `events` rows, correct `seq` order; one malformed publish is rejected,
not stored." `test_one_event_of_every_type_is_stored_in_seq_order` is that,
with one correction: `EVENT_SCHEMAS.md` §2-§7 defines **13** event types, not
12, and the roadmap's count is a miscount of the frozen contract rather than a
missing type. The test asserts against the contract.

Needs both compose services (`docker compose up`) and `alembic upgrade head`;
skipped, not failed, when either is missing. Runs on Redis logical DB 15, which
is reserved for tests, and deletes only the `events` rows it inserted.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import psycopg
import pytest
from redis import Redis
from redis.exceptions import RedisError
from src.config import CONSUMER_SERVICE, Config
from src.main import build_consumer, run

from libs.event_bus import EventSchemaInvalidError
from libs.event_bus.consumer import EventConsumer
from libs.event_bus.payloads import EVENT_PAYLOAD_SCHEMA_FILES
from libs.event_bus.publisher import EventPublisher, stream_name
from libs.testing.event_test_helpers import VALID_PAYLOADS, envelope_for

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://127.0.0.1:6379/15")
POSTGRES_TEST_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://businessscrapper:businessscrapper@127.0.0.1:5432/businessscrapper",
)

TEST_CONFIG = Config(
    database_url=POSTGRES_TEST_URL,
    redis_url=REDIS_TEST_URL,
    consumer_name="test-worker",
    log_level="INFO",
    block_ms=200,
    batch_size=20,
)


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    client = Redis.from_url(REDIS_TEST_URL)
    try:
        client.ping()
    except RedisError as exc:
        pytest.skip(f"Redis unavailable at {REDIS_TEST_URL}: {exc}")
    client.flushdb()
    yield client
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
            cur.execute("SELECT to_regclass('public.events')")
            if cur.fetchone()[0] is None:  # type: ignore[index]
                pytest.skip("run `alembic upgrade head` in infra/postgres first")
        yield connection


@pytest.fixture
def stored_event_ids(conn: psycopg.Connection) -> Iterator[list[UUID]]:
    """Track what a test inserted so only those rows are removed afterwards.

    `events` is append-only in production, so the suite tidies up after itself
    rather than truncating a table a developer may have real rows in.
    """
    inserted: list[UUID] = []
    yield inserted
    if inserted:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM events WHERE event_id = ANY(%s)", (inserted,))
        conn.commit()


def _publish_all(redis: Redis, tracker: list[UUID]) -> list[dict[str, Any]]:
    publisher = EventPublisher(redis)
    published = []
    for event_type in sorted(VALID_PAYLOADS):
        event = envelope_for(event_type, VALID_PAYLOADS[event_type])
        publisher.publish_raw(event)
        tracker.append(UUID(event["event_id"]))
        published.append(event)
    return published


def _drain(consumer: EventConsumer, conn: psycopg.Connection, expected: int) -> int:
    stored = 0
    while stored < expected:
        progressed = run(consumer, conn, max_batches=1)
        if progressed == 0:
            break
        stored += progressed
    return stored


def test_one_event_of_every_type_is_stored_in_seq_order(
    redis_client: Redis, conn: psycopg.Connection, stored_event_ids: list[UUID]
) -> None:
    """The task's Definition of Done."""
    published = _publish_all(redis_client, stored_event_ids)
    consumer = build_consumer(redis_client, TEST_CONFIG)

    stored = _drain(consumer, conn, len(published))

    assert stored == len(EVENT_PAYLOAD_SCHEMA_FILES) == len(published)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, event_type, seq FROM events WHERE event_id = ANY(%s) ORDER BY seq",
            (stored_event_ids,),
        )
        rows = cur.fetchall()

    assert len(rows) == len(published)
    assert {row[1] for row in rows} == set(EVENT_PAYLOAD_SCHEMA_FILES)
    assert [row[2] for row in rows] == sorted(row[2] for row in rows), "seq is not monotonic"


def test_stored_row_matches_the_envelope(
    redis_client: Redis, conn: psycopg.Connection, stored_event_ids: list[UUID]
) -> None:
    """§13 maps 1:1 onto the envelope; seq and stored_at are the database's, not a producer's."""
    event = envelope_for("USER_INTERESTED", VALID_PAYLOADS["USER_INTERESTED"])
    EventPublisher(redis_client).publish_raw(event)
    stored_event_ids.append(UUID(event["event_id"]))

    _drain(build_consumer(redis_client, TEST_CONFIG), conn, 1)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_type, version, correlation_id, producer_service, payload, "
            "produced_at, stored_at FROM events WHERE event_id = %s",
            (UUID(event["event_id"]),),
        )
        row = cur.fetchone()

    assert row is not None
    event_type, version, correlation_id, producer_service, payload, produced_at, stored_at = row
    assert event_type == event["event_type"]
    assert version == event["version"]
    assert correlation_id is None
    assert producer_service == event["producer_service"]
    assert payload == event["payload"]
    assert produced_at.isoformat() == event["produced_at"]
    assert stored_at is not None


def test_malformed_publish_is_rejected_and_not_stored(
    redis_client: Redis, conn: psycopg.Connection
) -> None:
    """The publish itself fails, so nothing reaches the bus and no row is written."""
    broken = envelope_for(
        "USER_INTERESTED", {"deal_id": VALID_PAYLOADS["USER_INTERESTED"]["deal_id"]}
    )

    with pytest.raises(EventSchemaInvalidError):
        EventPublisher(redis_client).publish_raw(broken)

    assert redis_client.exists(stream_name("USER_INTERESTED")) == 0
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM events WHERE event_id = %s", (UUID(broken["event_id"]),))
        assert cur.fetchone() == (0,)


def test_replayed_event_is_stored_once(
    redis_client: Redis, conn: psycopg.Connection, stored_event_ids: list[UUID]
) -> None:
    """events.event_id is UNIQUE and doubles as the idempotency key (§13)."""
    event = envelope_for("USER_INTERESTED", VALID_PAYLOADS["USER_INTERESTED"])
    publisher = EventPublisher(redis_client)
    publisher.publish_raw(event)
    publisher.publish_raw(event)  # same event_id, two stream entries
    stored_event_ids.append(UUID(event["event_id"]))

    _drain(build_consumer(redis_client, TEST_CONFIG), conn, 2)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM events WHERE event_id = %s", (UUID(event["event_id"]),))
        assert cur.fetchone() == (1,)


def test_consumer_subscribes_to_every_event_type(redis_client: Redis) -> None:
    """§9: "subscribes to every stream". Derived from the schema registry, never a hand list."""
    consumer = build_consumer(redis_client, TEST_CONFIG)

    assert consumer.group == str(CONSUMER_SERVICE)
    for event_type in EVENT_PAYLOAD_SCHEMA_FILES:
        groups = redis_client.xinfo_groups(stream_name(event_type))
        assert [g["name"].decode() for g in groups] == [str(CONSUMER_SERVICE)]
