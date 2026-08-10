"""Redis Streams consumer, consumer-group based.

Implements `ZIP_13_ENGINEERING_CONTRACTS/EVENT_SCHEMAS.md` (bus = Redis Streams,
ADR-006/ADR-010) — Sprint 1 Task 1.4.

One consumer group per `consumer_service` per stream, which is what gives the
"each event is handled by exactly one worker of a service, and every service
sees every event" fan-out the contract assumes. The group name is the
`event_producer_service` value (`ENUMS.md`) — the same string written to
`processed_events.consumer_service` and into the DLQ stream name
`{event_type}.dlq.{consumer_service}` (§7), so the spelling is load-bearing.

Dedup is deliberately *not* here: `processed_events` check-before-act is
Task 1.5 (`dedup.py`), and consumer groups only guarantee one delivery per
group per read, not exactly-once across restarts and reclaims.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from redis import Redis
from redis.exceptions import ResponseError

from libs.enums import EventProducerService
from libs.error_codes.error_codes import SYS_EVENT_SCHEMA_INVALID
from libs.event_bus.envelope import Envelope, EventSchemaInvalidError
from libs.event_bus.payloads import validate_event
from libs.event_bus.publisher import ENVELOPE_FIELD, stream_name

__all__ = ["EventConsumer", "ReceivedEvent"]

logger: Final = logging.getLogger(__name__)

# Start each new group at 0, not $: a group created after a producer has already
# published must still see the backlog Redis is retaining. `$` would silently
# drop everything published before the consumer first booted.
_GROUP_START_ID: Final = "0"

_BUSYGROUP: Final = "BUSYGROUP"

# One XREADGROUP response: per stream, a list of (entry_id, field map) pairs.
type _StreamBatches = list[tuple[Any, list[tuple[Any, dict[Any, Any]]]]]


@dataclass(frozen=True, slots=True)
class ReceivedEvent:
    """One delivered, validated event plus what is needed to acknowledge it."""

    stream: str
    entry_id: str
    envelope: Envelope


class EventConsumer:
    """Reads events for one service from one or more event-type streams.

    The `Redis` client is injected; this class owns no connection state, so a
    service controls its own pool and tests can point it at any instance.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        consumer_service: EventProducerService,
        event_types: Sequence[str],
        consumer_name: str,
        block_ms: int = 5_000,
        batch_size: int = 10,
    ) -> None:
        self._redis = redis
        self._consumer_service = consumer_service
        self._streams = [stream_name(event_type) for event_type in event_types]
        self._consumer_name = consumer_name
        self._block_ms = block_ms
        self._batch_size = batch_size

    @property
    def group(self) -> str:
        return str(self._consumer_service)

    @property
    def consumer_name(self) -> str:
        return self._consumer_name

    def ensure_groups(self) -> None:
        """Create the consumer group on each stream, creating the stream if absent.

        Idempotent: an existing group is a `BUSYGROUP` error from Redis, which is
        the normal case on every restart and every additional worker, not a
        failure.
        """
        for stream in self._streams:
            try:
                self._redis.xgroup_create(
                    name=stream, groupname=self.group, id=_GROUP_START_ID, mkstream=True
                )
            except ResponseError as exc:
                if _BUSYGROUP not in str(exc):
                    raise

    def read(self, *, block: bool = True) -> list[ReceivedEvent]:
        """Read one batch of new-to-this-group entries.

        Malformed entries are logged as `SYS_EVENT_SCHEMA_INVALID`, acknowledged
        and dropped rather than returned: that code is non-retryable (a message
        that fails schema validation cannot become valid on redelivery), so
        leaving it unacknowledged would only pin it in the pending list forever.
        """
        # redis-py types this as Any/ResponseT; under RESP2 it is
        # [(stream, [(entry_id, {field: value}), ...]), ...] or None when the
        # blocking read times out.
        response = cast(
            "_StreamBatches | None",
            self._redis.xreadgroup(
                groupname=self.group,
                consumername=self._consumer_name,
                streams=dict.fromkeys(self._streams, ">"),
                count=self._batch_size,
                block=self._block_ms if block else None,
            ),
        )
        events: list[ReceivedEvent] = []
        for raw_stream, entries in response or []:
            stream = _as_str(raw_stream)
            for raw_entry_id, fields in entries:
                entry_id = _as_str(raw_entry_id)
                envelope = self._parse(stream, entry_id, fields)
                if envelope is not None:
                    events.append(
                        ReceivedEvent(stream=stream, entry_id=entry_id, envelope=envelope)
                    )
        return events

    def ack(self, event: ReceivedEvent) -> None:
        """Acknowledge one handled event. Until this runs it stays in the group's pending list."""
        self._redis.xack(event.stream, self.group, event.entry_id)

    def consume(
        self,
        handler: Callable[[ReceivedEvent], None],
        *,
        max_batches: int | None = None,
    ) -> int:
        """Read-handle-ack loop. Returns the number of events handled.

        A handler raising is not acknowledged — the entry stays pending for that
        consumer so a reclaim can retry it, and the exception propagates rather
        than being swallowed into a silent data-loss path. `max_batches` bounds
        the loop for tests and one-shot scripts; `None` runs until interrupted.
        """
        handled = 0
        batches = 0
        while max_batches is None or batches < max_batches:
            batches += 1
            for event in self.read():
                handler(event)
                self.ack(event)
                handled += 1
        return handled

    def __iter__(self) -> Iterator[ReceivedEvent]:
        """Yield events forever. The caller acknowledges each one via `ack()`."""
        while True:
            yield from self.read()

    def _parse(self, stream: str, entry_id: str, fields: dict[Any, Any]) -> Envelope | None:
        raw = fields.get(ENVELOPE_FIELD) or fields.get(ENVELOPE_FIELD.encode())
        try:
            if raw is None:
                raise EventSchemaInvalidError(f"missing stream field {ENVELOPE_FIELD!r}")
            data = json.loads(_as_str(raw))
            validate_event(data)
            return Envelope.from_dict(data)
        except (EventSchemaInvalidError, json.JSONDecodeError) as exc:
            logger.error(
                "%s: dropping malformed entry %s on %s: %s",
                SYS_EVENT_SCHEMA_INVALID.code,
                entry_id,
                stream,
                exc,
            )
            self._redis.xack(stream, self.group, entry_id)
            return None


def _as_str(value: Any) -> str:
    """Redis returns bytes unless the client was built with `decode_responses=True`."""
    return value.decode() if isinstance(value, bytes) else str(value)
