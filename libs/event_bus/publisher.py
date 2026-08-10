"""Redis Streams publisher.

Implements `ZIP_13_ENGINEERING_CONTRACTS/EVENT_SCHEMAS.md` (bus = Redis Streams,
ADR-006/ADR-010) — Sprint 1 Task 1.4.

Every publish validates the envelope (§1) and the payload (§2-§7) *before* the
`XADD`; a failure raises `EventSchemaInvalidError` (`SYS_EVENT_SCHEMA_INVALID`)
and nothing reaches the bus. §1 is explicit that validation gates the publish,
not the consume.

Stream naming: one stream per `event_type`, named exactly after it. §7 fixes the
DLQ stream as `{event_type}.dlq.{consumer_service}`, which only reads as a
derivative of a main stream named `{event_type}` — so that is the convention,
not an invented one.

Wire format: the whole envelope as one JSON string under a single stream field.
Redis Stream entries are flat field/value maps and the envelope is nested
(`payload` is an object), so a field-per-key encoding cannot round-trip it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from redis import Redis

from libs.event_bus.envelope import Envelope
from libs.event_bus.payloads import validate_event

__all__ = ["ENVELOPE_FIELD", "EventPublisher", "stream_name"]

# Single stream field holding the JSON-encoded envelope.
ENVELOPE_FIELD: Final = "envelope"


def stream_name(event_type: str) -> str:
    """Stream for an event type. See the module docstring on why this is 1:1."""
    return event_type


class EventPublisher:
    """Publishes envelopes to their event type's stream.

    Holds no connection state of its own — the `Redis` client is injected, so a
    service owns its own connection pool and this stays testable without one.
    """

    def __init__(self, redis: Redis, *, maxlen: int | None = None) -> None:
        """`maxlen` caps stream length approximately (`XADD ... MAXLEN ~`).

        Retention is bounded on Redis by design (ADR-006's consequence: the
        Event Store Consumer persisting to Postgres is what makes replay
        possible), but no ZIP_13 document fixes a number — so the default is
        `None` (uncapped) and choosing a cap is a deployment decision, not one
        made here.
        """
        self._redis = redis
        self._maxlen = maxlen

    def publish(self, envelope: Envelope) -> str:
        """Validate and `XADD` one envelope. Returns the Redis stream entry ID."""
        return self.publish_raw(envelope.to_dict())

    def publish_raw(self, event: Mapping[str, Any]) -> str:
        """Validate and `XADD` an already-serialized envelope dict."""
        validate_event(event)
        entry_id: bytes | str = self._redis.xadd(
            name=stream_name(event["event_type"]),
            fields={ENVELOPE_FIELD: json.dumps(event)},
            maxlen=self._maxlen,
            approximate=True,
        )
        return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
