"""Envelope model + schema tests — Sprint 1 Task 1.2.

Covers the task's Definition of Done directly: "Envelope missing nullable
`correlation_id` validates; one missing `event_id` fails with
`SYS_EVENT_SCHEMA_INVALID`." The remaining cases guard the parts of
`EVENT_SCHEMAS.md` §1 that a single happy-path test would not notice breaking:
the fixed field set, the producer enum, and the `seq`/`stored_at` exclusion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from libs.enums import EventProducerService
from libs.error_codes.error_codes import SYS_EVENT_SCHEMA_INVALID
from libs.event_bus import (
    Envelope,
    EventSchemaInvalidError,
    load_envelope_schema,
    validate_envelope,
)


def _valid() -> dict[str, Any]:
    return {
        "event_id": str(uuid4()),
        "event_type": "DEAL_SCORED",
        "version": 1,
        "correlation_id": str(uuid4()),
        "producer_service": "deal-engine",
        "produced_at": "2026-01-01T12:00:00+00:00",
        "payload": {"deal_id": str(uuid4())},
    }


def test_valid_envelope_passes() -> None:
    validate_envelope(_valid())


def test_missing_correlation_id_validates() -> None:
    """Nullable per §1 — both absent and explicitly null are well-formed."""
    absent = _valid()
    del absent["correlation_id"]
    validate_envelope(absent)

    explicit_null = _valid() | {"correlation_id": None}
    validate_envelope(explicit_null)


def test_missing_event_id_fails_with_schema_invalid() -> None:
    broken = _valid()
    del broken["event_id"]

    with pytest.raises(EventSchemaInvalidError) as excinfo:
        validate_envelope(broken)

    assert excinfo.value.error_code is SYS_EVENT_SCHEMA_INVALID
    assert excinfo.value.error_code.code == "SYS_EVENT_SCHEMA_INVALID"
    assert "event_id" in excinfo.value.reason


@pytest.mark.parametrize(
    "field",
    ["event_type", "version", "producer_service", "produced_at", "payload"],
)
def test_every_required_field_is_required(field: str) -> None:
    broken = _valid()
    del broken[field]
    with pytest.raises(EventSchemaInvalidError):
        validate_envelope(broken)


def test_unknown_producer_service_rejected() -> None:
    with pytest.raises(EventSchemaInvalidError):
        validate_envelope(_valid() | {"producer_service": "not-a-service"})


def test_version_below_one_rejected() -> None:
    """§1: "starts at 1"."""
    with pytest.raises(EventSchemaInvalidError):
        validate_envelope(_valid() | {"version": 0})


def test_seq_and_stored_at_are_not_envelope_fields() -> None:
    """§1: both are assigned by the Event Store Consumer, never set by producers."""
    for producer_set in ({"seq": 1}, {"stored_at": "2026-01-01T12:00:00+00:00"}):
        with pytest.raises(EventSchemaInvalidError):
            validate_envelope(_valid() | producer_set)


def test_schema_producer_enum_matches_enums_registry() -> None:
    """The schema's enum list and `EventProducerService` must not drift apart."""
    schema_values = load_envelope_schema()["properties"]["producer_service"]["enum"]
    assert schema_values == [member.value for member in EventProducerService]


def test_new_assigns_event_id_and_produced_at() -> None:
    envelope = Envelope.new(
        event_type="LISTING_DISCOVERED",
        producer_service=EventProducerService.MARKETPLACE_CONNECTOR,
        payload={"product": {}},
    )

    assert isinstance(envelope.event_id, UUID)
    assert envelope.produced_at.tzinfo is not None
    assert envelope.version == 1
    assert envelope.correlation_id is None
    envelope.validate()


def test_round_trip_through_dict() -> None:
    original = Envelope(
        event_id=uuid4(),
        event_type="PURCHASE_REQUESTED",
        version=1,
        producer_service=EventProducerService.TELEGRAM_BOT,
        produced_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        payload={"order_id": str(uuid4())},
        correlation_id=uuid4(),
    )

    assert Envelope.from_dict(original.to_dict()) == original


def test_naive_produced_at_rejected() -> None:
    """§1 types `produced_at` timestamptz; a naive timestamp is ambiguous on the wire."""
    with pytest.raises(EventSchemaInvalidError):
        Envelope.from_dict(_valid() | {"produced_at": "2026-01-01T12:00:00"})
