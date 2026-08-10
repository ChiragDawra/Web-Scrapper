"""Event Store Consumer entry point — Sprint 1 Task 1.8.

Subscribes to every event-type stream (`SERVICE_INTERFACES.md` §9: "every event
type"), validates each envelope and payload, and appends it to `events` — the
sole write path into that table (ADR-010).

The stream list is `EVENT_PAYLOAD_SCHEMA_FILES`, so "every event type" stays
true by construction: a new event type added to `EVENT_SCHEMAS.md` and given a
schema is subscribed to here without this file changing.
"""

from __future__ import annotations

import logging
from typing import Final

import psycopg
from psycopg import Connection
from redis import Redis

from libs.event_bus.consumer import EventConsumer, ReceivedEvent
from libs.event_bus.payloads import EVENT_PAYLOAD_SCHEMA_FILES
from src.config import CONSUMER_SERVICE, Config
from src.handlers.event_handlers import EventStoreHandler

__all__ = ["build_consumer", "main", "run"]

logger: Final = logging.getLogger(__name__)


def build_consumer(redis: Redis, config: Config) -> EventConsumer:
    """Consumer group over every event type, with the groups created up front."""
    consumer = EventConsumer(
        redis,
        consumer_service=CONSUMER_SERVICE,
        event_types=sorted(EVENT_PAYLOAD_SCHEMA_FILES),
        consumer_name=config.consumer_name,
        block_ms=config.block_ms,
        batch_size=config.batch_size,
    )
    consumer.ensure_groups()
    return consumer


def run(consumer: EventConsumer, conn: Connection, *, max_batches: int | None = None) -> int:
    """Read-persist-ack until interrupted. Returns the number of events stored.

    A failing `persist` propagates and the event is left unacknowledged, so it
    stays in the group's pending list for a retry rather than being silently
    dropped — losing an event here would lose it from the only durable record
    the system has. `max_batches` bounds the loop for tests and one-shot runs.
    """
    handler = EventStoreHandler(conn)

    def handle(event: ReceivedEvent) -> None:
        handler.persist(event.envelope)

    return consumer.consume(handle, max_batches=max_batches)


def main() -> None:
    config = Config.from_env()
    logging.basicConfig(level=config.log_level)
    logger.info(
        "event-store-consumer starting as %s over %d event types",
        config.consumer_name,
        len(EVENT_PAYLOAD_SCHEMA_FILES),
    )

    redis = Redis.from_url(config.redis_url)
    with psycopg.connect(config.database_url) as conn:
        run(build_consumer(redis, config), conn)


if __name__ == "__main__":
    main()
