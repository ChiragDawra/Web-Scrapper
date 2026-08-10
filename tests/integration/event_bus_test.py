"""Publisher/consumer integration tests against a real Redis — Sprint 1 Task 1.4.

Definition of Done: "A local script publishes N events; a 2-worker consumer
group processes all N exactly once between them." `test_two_workers_split_the_
backlog_exactly_once` is that script, as a test.

Runs against the compose Redis (`docker compose up redis`) on logical DB 15,
which is reserved for tests and flushed before each one — never DB 0, where a
running stack keeps its real streams. Skipped, not failed, when Redis is
unreachable, so a lint-and-unit-test-only CI job stays green.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from redis import Redis
from redis.exceptions import RedisError

from libs.enums import EventProducerService
from libs.event_bus import Envelope, EventSchemaInvalidError
from libs.event_bus.consumer import EventConsumer, ReceivedEvent
from libs.event_bus.publisher import EventPublisher, stream_name

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://127.0.0.1:6379/15")

EVENT_TYPE = "USER_INTERESTED"
DEAL_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
USER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3302"


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


def _envelope(payload: dict[str, Any] | None = None) -> Envelope:
    return Envelope.new(
        event_type=EVENT_TYPE,
        producer_service=EventProducerService.TELEGRAM_BOT,
        payload=payload or {"deal_id": DEAL_ID, "telegram_user_id": USER_ID},
    )


def test_publish_then_consume_round_trip(redis_client: Redis) -> None:
    publisher = EventPublisher(redis_client)
    sent = _envelope()
    publisher.publish(sent)

    consumer = EventConsumer(
        redis_client,
        consumer_service=EventProducerService.DEAL_ENGINE,
        event_types=[EVENT_TYPE],
        consumer_name="worker-1",
        block_ms=200,
    )
    consumer.ensure_groups()

    received = consumer.read()

    assert [event.envelope.event_id for event in received] == [sent.event_id]
    assert received[0].envelope.payload == dict(sent.payload)
    assert received[0].stream == stream_name(EVENT_TYPE)


def test_invalid_payload_is_rejected_before_publish(redis_client: Redis) -> None:
    """§1: validation gates the publish. Nothing malformed reaches the bus."""
    publisher = EventPublisher(redis_client)

    with pytest.raises(EventSchemaInvalidError):
        publisher.publish(_envelope(payload={"deal_id": DEAL_ID}))  # telegram_user_id missing

    assert redis_client.exists(stream_name(EVENT_TYPE)) == 0


def test_group_created_after_publish_still_sees_the_backlog(redis_client: Redis) -> None:
    """Groups start at 0, not $ — a consumer booting late must not lose retained events."""
    EventPublisher(redis_client).publish(_envelope())

    consumer = EventConsumer(
        redis_client,
        consumer_service=EventProducerService.DEAL_ENGINE,
        event_types=[EVENT_TYPE],
        consumer_name="late-worker",
        block_ms=200,
    )
    consumer.ensure_groups()

    assert len(consumer.read()) == 1


def test_ensure_groups_is_idempotent(redis_client: Redis) -> None:
    """Every worker calls this on boot; an existing group is BUSYGROUP, not a failure."""
    consumer = EventConsumer(
        redis_client,
        consumer_service=EventProducerService.DEAL_ENGINE,
        event_types=[EVENT_TYPE],
        consumer_name="worker-1",
        block_ms=200,
    )
    consumer.ensure_groups()
    consumer.ensure_groups()


def test_two_workers_split_the_backlog_exactly_once(redis_client: Redis) -> None:
    """The task's Definition of Done, verbatim: N published, 2 workers, each event once."""
    n = 20
    publisher = EventPublisher(redis_client)
    published = [_envelope() for _ in range(n)]
    for envelope in published:
        publisher.publish(envelope)

    workers = [
        EventConsumer(
            redis_client,
            consumer_service=EventProducerService.DEAL_ENGINE,
            event_types=[EVENT_TYPE],
            consumer_name=f"worker-{index}",
            block_ms=200,
            batch_size=3,
        )
        for index in range(1, 3)
    ]
    workers[0].ensure_groups()

    handled: dict[str, list[str]] = {worker.consumer_name: [] for worker in workers}

    def drain(worker: EventConsumer) -> int:
        def handle(event: ReceivedEvent) -> None:
            handled[worker.consumer_name].append(str(event.envelope.event_id))

        return worker.consume(handle, max_batches=1)

    # Alternate the two workers until the backlog is exhausted, so the split is
    # driven by Redis's group semantics rather than by one worker winning a race.
    while sum(len(ids) for ids in handled.values()) < n:
        progressed = sum(drain(worker) for worker in workers)
        if progressed == 0:
            break

    all_handled = [event_id for ids in handled.values() for event_id in ids]
    assert sorted(all_handled) == sorted(str(envelope.event_id) for envelope in published)
    assert len(all_handled) == len(set(all_handled)), "an event was delivered twice"
    assert all(len(ids) > 0 for ids in handled.values()), "one worker did no work"

    pending = redis_client.xpending(stream_name(EVENT_TYPE), workers[0].group)
    assert pending["pending"] == 0


def test_malformed_stream_entry_is_dropped_not_returned(redis_client: Redis) -> None:
    """A hand-written entry that bypassed the publisher is logged, acked and skipped."""
    stream = stream_name(EVENT_TYPE)
    consumer = EventConsumer(
        redis_client,
        consumer_service=EventProducerService.DEAL_ENGINE,
        event_types=[EVENT_TYPE],
        consumer_name="worker-1",
        block_ms=200,
    )
    consumer.ensure_groups()
    redis_client.xadd(stream, {"envelope": "not json"})

    assert consumer.read() == []
    assert redis_client.xpending(stream, consumer.group)["pending"] == 0
