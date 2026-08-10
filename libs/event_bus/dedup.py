"""Consumer-side idempotency against `processed_events` — Sprint 1 Task 1.5.

`EVENT_SCHEMAS.md` §1: "Consumers dedup via `processed_events
(consumer_service, event_id)` (`DATABASE_SCHEMA.md` §18) — an event with an
`event_id` already present for that consumer is skipped
(`SYS_DUPLICATE_EVENT`), not reprocessed."

Check-before-act, write-after-act, in that order: the mark is written only
after the handler returned, so a crash mid-handler leaves no row and the
redelivery reprocesses instead of silently dropping the work. The cost of that
ordering is that a crash *between* the handler committing and the mark being
written re-runs the handler once — at-least-once, which is what the bus
promises anyway. Marking first would convert that into at-most-once and lose
events outright, which the contract does not allow.

Redis Streams consumer-group `XACK` alone is not enough (§18): at-least-once
delivery can redeliver after a consumer crashes with the entry already
handled but still pending. This table is the durable backstop, so the handler
and `mark_processed` should run in one transaction wherever the handler's own
writes are transactional.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final
from uuid import UUID

from psycopg import Connection

from libs.enums import EventProducerService
from libs.error_codes.error_codes import SYS_DUPLICATE_EVENT
from libs.event_bus.consumer import ReceivedEvent

__all__ = [
    "PROCESSED_EVENTS_RETENTION_DAYS",
    "is_processed",
    "mark_processed",
    "process_once",
    "purge_processed_events",
]

logger: Final = logging.getLogger(__name__)

# DATABASE_SCHEMA.md §18: "rows older than 7 days are purged by a daily job".
PROCESSED_EVENTS_RETENTION_DAYS: Final = 7


def is_processed(conn: Connection, consumer_service: EventProducerService, event_id: UUID) -> bool:
    """The check half: has this consumer already handled this `event_id`?"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM processed_events WHERE consumer_service = %s AND event_id = %s",
            (str(consumer_service), event_id),
        )
        return cur.fetchone() is not None


def mark_processed(
    conn: Connection, consumer_service: EventProducerService, event_id: UUID
) -> bool:
    """The write half. Returns False if the row was already there.

    `ON CONFLICT DO NOTHING` rather than a bare insert: two workers of the same
    service can race past `is_processed` on the same redelivered event, and the
    loser of that race must not crash the consumer with a primary-key violation
    over work that did get done.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO processed_events (consumer_service, event_id) VALUES (%s, %s) "
            "ON CONFLICT (consumer_service, event_id) DO NOTHING",
            (str(consumer_service), event_id),
        )
        return cur.rowcount == 1


def process_once[T](
    conn: Connection,
    consumer_service: EventProducerService,
    event: ReceivedEvent,
    handler: Callable[[ReceivedEvent], T],
) -> T | None:
    """Run `handler` unless this event was already handled by this consumer.

    Returns the handler's result, or `None` when the event was skipped as a
    duplicate — so a handler that itself returns `None` is indistinguishable
    from a skip by return value alone. Callers that need to tell them apart
    should use `is_processed` and `mark_processed` directly.

    A raising handler propagates and is *not* marked: the event stays
    unprocessed and unacknowledged, which is what makes the redelivery retry it.
    """
    event_id = event.envelope.event_id
    if is_processed(conn, consumer_service, event_id):
        logger.info(
            "%s: %s already processed %s (%s), skipping",
            SYS_DUPLICATE_EVENT.code,
            consumer_service,
            event_id,
            event.envelope.event_type,
        )
        return None

    result = handler(event)
    mark_processed(conn, consumer_service, event_id)
    return result


def purge_processed_events(
    conn: Connection, *, retention_days: int = PROCESSED_EVENTS_RETENTION_DAYS
) -> int:
    """Delete marks older than the retention window. Returns rows deleted.

    §18 fixes the 7-day TTL and says a daily job applies it; this is the
    statement that job runs. Scheduling it is a deployment concern, not this
    module's.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM processed_events WHERE processed_at < now() - make_interval(days => %s)",
            (retention_days,),
        )
        return cur.rowcount
