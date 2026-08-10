"""`events` table writer — Sprint 1 Task 1.8.

This service is the sole writer to `events` (ADR-010, `DATABASE_SCHEMA.md` §13,
`SERVICE_INTERFACES.md` §9). No other service inserts here, and this repository
touches no other table.

`seq` and `stored_at` are assigned by the database, never by a producer:
`EVENT_SCHEMAS.md` §1 says so explicitly, and `seq` being a `BIGSERIAL` is what
makes the stream order recoverable at all.
"""

from __future__ import annotations

from psycopg import Connection
from psycopg.types.json import Json

from libs.event_bus.envelope import Envelope

__all__ = ["EventRepository"]

_INSERT = """
INSERT INTO events (
    event_id, event_type, version, correlation_id, producer_service, payload, produced_at
) VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (event_id) DO NOTHING
RETURNING seq
"""


class EventRepository:
    """Append-only access to `events`. The connection is injected; transactions are the caller's."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(self, envelope: Envelope) -> int | None:
        """Append one event. Returns its `seq`, or `None` if it was already stored.

        `ON CONFLICT (event_id) DO NOTHING` is this consumer's idempotency, and
        it is why it does not also write `processed_events`: `events.event_id`
        is already `UNIQUE` and doubles as the idempotency key (§13), so the
        dedup ledger would be a second write buying the same guarantee. Other
        consumers, whose effects are not a single insert into a uniquely-keyed
        table, still need `libs.event_bus.dedup`.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                _INSERT,
                (
                    envelope.event_id,
                    envelope.event_type,
                    envelope.version,
                    envelope.correlation_id,
                    str(envelope.producer_service),
                    Json(dict(envelope.payload)),
                    envelope.produced_at,
                ),
            )
            row = cur.fetchone()
        return int(row[0]) if row else None
