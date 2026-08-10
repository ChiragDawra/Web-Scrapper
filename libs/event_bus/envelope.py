"""Event envelope model + JSON Schema validation.

Implements `ZIP_13_ENGINEERING_CONTRACTS/EVENT_SCHEMAS.md` §1 — Sprint 1 Task 1.2.

Every event on the bus is wrapped in this envelope and validated against
`schema/envelope.json` before publish; a failure rejects the publish with
`SYS_EVENT_SCHEMA_INVALID` (`ERROR_CODES.md`). The envelope maps 1:1 onto the
`events` table (`DATABASE_SCHEMA.md` §13) except for `seq` and `stored_at`,
which the Event Store Consumer assigns on write and no producer ever sets —
so neither is a field here.

Payload validation is deliberately *not* done here: §1 types `payload` as a bare
object and defers its shape to the per-event-type schemas in §2-§7 (Task 1.3).
This module answers one question only — is this a well-formed envelope.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Final
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from libs.enums import EventProducerService
from libs.error_codes import ErrorCode
from libs.error_codes.error_codes import SYS_EVENT_SCHEMA_INVALID

__all__ = [
    "ENVELOPE_SCHEMA_PATH",
    "SCHEMA_DIR",
    "Envelope",
    "EventSchemaInvalidError",
    "format_schema_errors",
    "load_envelope_schema",
    "parse_timestamp",
    "parse_uuid",
    "validate_envelope",
]

SCHEMA_DIR: Final = Path(__file__).parent / "schema"
ENVELOPE_SCHEMA_PATH: Final = SCHEMA_DIR / "envelope.json"


class EventSchemaInvalidError(Exception):
    """An envelope (or payload) failed schema validation.

    Carries the `ERROR_CODES.md` entry rather than a bare string so error paths
    emit only defined codes with their documented severity/retryable values
    (`IMPLEMENTATION_ROADMAP.md` §5).
    """

    error_code: ClassVar[ErrorCode] = SYS_EVENT_SCHEMA_INVALID

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"{SYS_EVENT_SCHEMA_INVALID.code}: {reason}")


@lru_cache(maxsize=1)
def load_envelope_schema() -> dict[str, Any]:
    """Return the parsed `schema/envelope.json`. Cached — the file never changes at runtime."""
    with ENVELOPE_SCHEMA_PATH.open(encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)
    return schema


@lru_cache(maxsize=1)
def _envelope_validator() -> Draft202012Validator:
    return Draft202012Validator(load_envelope_schema(), format_checker=FormatChecker())


def format_schema_errors(errors: Iterable[ValidationError]) -> str:
    """Render validation errors as `field/path: message`, joined, deepest path last.

    Reports every failure, not just the first, so a producer fixing a malformed
    event doesn't have to discover its problems one publish at a time.
    """
    ordered = sorted(errors, key=lambda e: list(map(str, e.absolute_path)))
    return "; ".join(
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in ordered
    )


def validate_envelope(data: Mapping[str, Any]) -> None:
    """Validate a raw envelope dict. Raises `EventSchemaInvalidError` if it is malformed."""
    reason = format_schema_errors(_envelope_validator().iter_errors(data))
    if reason:
        raise EventSchemaInvalidError(reason)


def parse_uuid(value: Any, field: str) -> UUID:
    """Parse one wire UUID field. Public because `libs.canonical_models` parses the same shapes."""
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise EventSchemaInvalidError(f"{field}: not a valid UUID") from exc


def parse_timestamp(value: Any, field: str) -> datetime:
    """Parse one wire timestamptz field. Public for the same reason as `parse_uuid`."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (ValueError, TypeError) as exc:
        raise EventSchemaInvalidError(f"{field}: not a valid ISO-8601 timestamp") from exc
    # timestamptz, per §1 — a naive timestamp is ambiguous on the wire, so it is
    # rejected rather than silently assumed to be UTC.
    if parsed.tzinfo is None:
        raise EventSchemaInvalidError(f"{field}: missing timezone offset (timestamptz required)")
    return parsed


@dataclass(frozen=True, slots=True)
class Envelope:
    """One event envelope, `EVENT_SCHEMAS.md` §1. Immutable once produced."""

    event_id: UUID
    event_type: str
    version: int
    producer_service: EventProducerService
    produced_at: datetime
    payload: Mapping[str, Any]
    correlation_id: UUID | None = None

    @classmethod
    def new(
        cls,
        *,
        event_type: str,
        producer_service: EventProducerService,
        payload: Mapping[str, Any],
        correlation_id: UUID | None = None,
        version: int = 1,
    ) -> Envelope:
        """Build a fresh envelope, assigning `event_id` and `produced_at`.

        `version` defaults to 1 — §1: "schema version of this event_type, starts
        at 1". A caller bumps it only when that event type's payload has had a
        breaking change recorded in `EVENT_SCHEMAS.md`.
        """
        return cls(
            event_id=uuid4(),
            event_type=event_type,
            version=version,
            producer_service=producer_service,
            produced_at=datetime.now(UTC),
            payload=payload,
            correlation_id=correlation_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire shape. `correlation_id` is always present, null when unset."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "version": self.version,
            "correlation_id": str(self.correlation_id) if self.correlation_id else None,
            "producer_service": str(self.producer_service),
            "produced_at": self.produced_at.isoformat(),
            "payload": dict(self.payload),
        }

    def validate(self) -> None:
        """Validate this envelope's own wire form. Raises `EventSchemaInvalidError`."""
        validate_envelope(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Envelope:
        """Validate a raw envelope dict and parse it. Raises `EventSchemaInvalidError`.

        An absent `correlation_id` and an explicit `null` are the same thing —
        §1 types it nullable, and the schema does not require the key.
        """
        validate_envelope(data)
        raw_correlation = data.get("correlation_id")
        return cls(
            event_id=parse_uuid(data["event_id"], "event_id"),
            event_type=data["event_type"],
            version=data["version"],
            producer_service=EventProducerService(data["producer_service"]),
            produced_at=parse_timestamp(data["produced_at"], "produced_at"),
            payload=data["payload"],
            correlation_id=(
                parse_uuid(raw_correlation, "correlation_id")
                if raw_correlation is not None
                else None
            ),
        )
