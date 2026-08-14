"""Deal Engine entry point — Sprint 3 Tasks 3.5 and 3.6.

Consumes `LISTING_DISCOVERED` and `USER_INTERESTED`, emits `DEAL_SCORED`
(`SERVICE_INTERFACES.md` §2).

One event is one transaction and one dedup mark. `process_once` writes the
`processed_events` row inside that same transaction as the deal it produced
(`DATABASE_SCHEMA.md` §18), so the two cannot disagree: either both landed or
neither did. A handler that raises leaves the event unmarked *and*
unacknowledged, and Redis redelivers it — which is the whole reason the mark is
not a separate commit.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Mapping
from typing import Any, Final

import psycopg
from psycopg import Connection
from redis import Redis

from libs.event_bus.consumer import EventConsumer, ReceivedEvent
from libs.event_bus.dedup import process_once
from libs.event_bus.publisher import EventPublisher
from src.config import CONSUMED_EVENT_TYPES, PRODUCER_SERVICE, Config
from src.handlers.event_handlers import (
    LISTING_DISCOVERED,
    USER_INTERESTED,
    handle_listing_discovered,
    handle_user_interested,
)
from src.services.scorer import ScoringConfig, load_scoring_config

__all__ = ["HANDLERS", "handle_event", "main", "run"]

logger: Final = logging.getLogger(__name__)

#: One handler per consumed event type. An event type reaching the loop without
#: an entry here is a wiring bug, not a data problem, so it raises rather than
#: being acknowledged away.
type Handler = Callable[[Connection, EventPublisher, ReceivedEvent, ScoringConfig], Any]

HANDLERS: Final[Mapping[str, Handler]] = {
    LISTING_DISCOVERED: lambda conn, publisher, event, config: handle_listing_discovered(
        conn, publisher, event, scoring_config=config
    ),
    USER_INTERESTED: lambda conn, publisher, event, config: handle_user_interested(
        conn, publisher, event, scoring_config=config
    ),
}


def handle_event(
    conn: Connection,
    publisher: EventPublisher,
    event: ReceivedEvent,
    *,
    scoring_config: ScoringConfig,
) -> Any:
    """Run one event's handler in one transaction, marking it processed on success.

    Commits on the way out and rolls back on any exception, so a half-written
    deal never survives — and because the dedup mark is part of the same
    transaction, a rolled-back event is genuinely unprocessed and will be
    retried rather than skipped as a duplicate.
    """
    handler = HANDLERS.get(event.envelope.event_type)
    if handler is None:
        raise KeyError(f"no handler registered for {event.envelope.event_type}")

    try:
        result = process_once(
            conn,
            PRODUCER_SERVICE,
            event,
            lambda received: handler(conn, publisher, received, scoring_config),
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def run(config: Config, *, max_batches: int | None = None) -> int:
    """Connect, subscribe, and consume until interrupted. Returns events handled.

    `max_batches` bounds the loop for tests and one-shot runs; `None` is the
    container's behavior.
    """
    scoring_config = load_scoring_config(config.scoring_config_url)
    logger.info("scoring with weights_version=%s", scoring_config.weights_version)

    redis = Redis.from_url(config.redis_url)
    publisher = EventPublisher(redis)
    consumer = EventConsumer(
        redis,
        consumer_service=PRODUCER_SERVICE,
        event_types=[event_type for event_type in CONSUMED_EVENT_TYPES if event_type in HANDLERS],
        consumer_name=config.consumer_name,
    )
    consumer.ensure_groups()

    with psycopg.connect(config.database_url) as conn:
        return consumer.consume(
            lambda event: handle_event(conn, publisher, event, scoring_config=scoring_config),
            max_batches=max_batches,
        )


def main() -> int:
    config = Config.from_env()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info(
        "deal-engine starting as %s on %s",
        config.consumer_name,
        ", ".join(event_type for event_type in CONSUMED_EVENT_TYPES if event_type in HANDLERS),
    )
    try:
        run(config)
    except KeyboardInterrupt:
        logger.info("interrupted; shutting down")
    return 0


if __name__ == "__main__":
    # `os.environ` is read in `Config.from_env`; a missing DATABASE_URL is a
    # startup failure with a readable message, not a traceback at first event.
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is required", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main())
