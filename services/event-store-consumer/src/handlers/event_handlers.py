"""`persist(envelope) -> void` — `SERVICE_INTERFACES.md` §9, Sprint 1 Task 1.8.

§9: "validates the envelope + payload against its JSON Schema before insert,
rejecting with `SYS_EVENT_SCHEMA_INVALID` on mismatch — this is the enforcement
point for `EVENT_SCHEMAS.md`, not a per-producer client-side check alone."

So the validation here is not redundant with the publisher's, and not redundant
with the consumer's either: it is the one that the contract names as
authoritative, and it must hold even for an entry written to a stream by
something that never went through `EventPublisher`.
"""

from __future__ import annotations

import logging
from typing import Final

from psycopg import Connection

from libs.error_codes.error_codes import SYS_DUPLICATE_EVENT
from libs.event_bus.envelope import Envelope
from libs.event_bus.payloads import validate_event
from src.repositories.event_repo import EventRepository

__all__ = ["EventStoreHandler"]

logger: Final = logging.getLogger(__name__)


class EventStoreHandler:
    """Validates and appends every event this service receives."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._events = EventRepository(conn)

    def persist(self, envelope: Envelope) -> int | None:
        """Validate then append. Returns the new `seq`, or `None` for an event already stored.

        Raises `EventSchemaInvalidError` (`SYS_EVENT_SCHEMA_INVALID`) on a
        malformed envelope or payload, leaving nothing written — a rejected
        event is not a stored event.

        Commits, because a stored-but-uncommitted event that is then acked on
        the bus is a lost event. The commit is per event rather than per batch
        for the same reason: batching would widen the window in which an ack has
        outrun its durable write.
        """
        validate_event(envelope.to_dict())
        seq = self._events.insert(envelope)
        self._conn.commit()

        if seq is None:
            logger.info(
                "%s: %s already stored, not reinserted",
                SYS_DUPLICATE_EVENT.code,
                envelope.event_id,
            )
        return seq
