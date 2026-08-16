"""Revalidation Service entry point — Sprint 5 Tasks 5.2 and 5.4.

Consumes `DEAL_REVALIDATION_REQUEST`, emits `DEAL_REVALIDATED`
(`SERVICE_INTERFACES.md` §3), and reads `DEAL_SCORED` to keep the reference-price
projection warm (`deal_reference.py`).

The 30s budget starts here, at delivery, not inside `revalidate()`: everything
between the Bot's emit and the publish is spent out of the same window, so the
`TimeoutBudget` is constructed once per event before any lookup happens.

Dedup is `process_once` against `processed_events` (`EVENT_SCHEMAS.md` §1), and
unlike the Deal Engine this service has no writes of its own to enclose — the one
side effect is an `XADD`, which is not transactional. So the transaction wraps
the mark alone, and the ordering is deliberate: publish first, mark second. A
crash in that window redelivers a request whose answer already went out, and the
Bot's own `event_id` dedup absorbs the duplicate; marking first would drop a
request whose answer never went out, and silence there costs the user their
confirmation.
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
    DEAL_REVALIDATION_REQUEST,
    DEAL_SCORED,
    handle_deal_revalidation_request,
    handle_deal_scored,
)
from src.services.deal_reference import DealReferenceStore
from src.services.listing_source import FixtureListingSource, ListingSource
from src.services.revalidator import TimeoutBudget

__all__ = ["HANDLERS", "handle_event", "main", "run"]

logger: Final = logging.getLogger(__name__)

#: One handler per consumed event type. An event type reaching the loop without
#: an entry here is a wiring bug, not a data problem, so it raises rather than
#: being acknowledged away.
type Handler = Callable[
    [EventPublisher, ReceivedEvent, DealReferenceStore, ListingSource, int], Any
]

HANDLERS: Final[Mapping[str, Handler]] = {
    DEAL_SCORED: lambda publisher, event, references, source, budget_seconds: handle_deal_scored(
        event, references=references
    ),
    DEAL_REVALIDATION_REQUEST: (
        lambda publisher, event, references, source, budget_seconds: (
            handle_deal_revalidation_request(
                publisher,
                event,
                references=references,
                source=source,
                budget=TimeoutBudget(budget_seconds=budget_seconds),
            )
        )
    ),
}


def handle_event(
    conn: Connection,
    publisher: EventPublisher,
    event: ReceivedEvent,
    *,
    references: DealReferenceStore,
    source: ListingSource,
    budget_seconds: int,
) -> Any:
    """Run one event's handler, marking it processed on success.

    Commits on the way out and rolls back on any exception. A raising handler
    leaves the event unmarked *and* unacknowledged — which is what makes an
    `UnknownDealError` from a cold projection retry instead of vanishing.
    """
    handler = HANDLERS.get(event.envelope.event_type)
    if handler is None:
        raise KeyError(f"no handler registered for {event.envelope.event_type}")

    try:
        result = process_once(
            conn,
            PRODUCER_SERVICE,
            event,
            lambda received: handler(publisher, received, references, source, budget_seconds),
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def run(
    config: Config,
    *,
    max_batches: int | None = None,
    source: ListingSource | None = None,
) -> int:
    """Connect, subscribe, and consume until interrupted. Returns events handled.

    `source` is injected for tests and for the eventual live read path
    (`INPUTS_NEEDED.md` item 1); the default is the recorded-fixture stub.
    `max_batches` bounds the loop for tests and one-shot runs; `None` is the
    container's behavior.
    """
    listing_source = source or FixtureListingSource(config.fixture_dir)
    references = DealReferenceStore()

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
            lambda event: handle_event(
                conn,
                publisher,
                event,
                references=references,
                source=listing_source,
                budget_seconds=config.timeout_budget_seconds,
            ),
            max_batches=max_batches,
        )


def main() -> int:
    config = Config.from_env()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info(
        "revalidation-service starting as %s on %s, %ds budget",
        config.consumer_name,
        ", ".join(event_type for event_type in CONSUMED_EVENT_TYPES if event_type in HANDLERS),
        config.timeout_budget_seconds,
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
