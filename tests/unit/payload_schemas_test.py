"""Per-event-type payload schema tests — Sprint 1 Task 1.3.

Definition of Done: "One valid fixture per event type passes; one malformed
fixture per event type fails." `VALID_PAYLOADS` holds the former; the malformed
case is derived from it per event type by dropping one required field, so the
two fixtures can never drift apart the way two hand-written ones would.

The three fields Task 1.3 calls out by name — `marketplace` on `DEAL_SCORED`/
`PURCHASE_REQUESTED`/`PURCHASE_TASK_CREATED`, and `listing_id`/`quantity` on
`PurchaseOutcome` — get their own explicit tests, since a dropped-field sweep
would still pass if they were absent from a schema's `required` list entirely.
"""

from __future__ import annotations

import pytest

from libs.enums import EventProducerService, MarketplaceCode
from libs.error_codes.error_codes import SYS_EVENT_SCHEMA_INVALID
from libs.event_bus import (
    EVENT_PAYLOAD_SCHEMA_FILES,
    EventSchemaInvalidError,
    load_schema,
    validate_event,
    validate_payload,
)
from libs.testing.event_test_helpers import (
    CANONICAL_PRODUCT,
    UUID_A,
    VALID_PAYLOADS,
    envelope_for,
)


def test_every_event_type_has_a_fixture() -> None:
    """A new schema file without a fixture would otherwise go untested."""
    assert set(VALID_PAYLOADS) == set(EVENT_PAYLOAD_SCHEMA_FILES)


@pytest.mark.parametrize("event_type", sorted(VALID_PAYLOADS))
def test_valid_fixture_passes(event_type: str) -> None:
    validate_payload(event_type, VALID_PAYLOADS[event_type])


@pytest.mark.parametrize("event_type", sorted(VALID_PAYLOADS))
def test_malformed_fixture_fails(event_type: str) -> None:
    """Drop the first required field — every payload here has at least one."""
    payload = dict(VALID_PAYLOADS[event_type])
    dropped = load_schema(EVENT_PAYLOAD_SCHEMA_FILES[event_type])["required"][0]
    del payload[dropped]

    with pytest.raises(EventSchemaInvalidError) as excinfo:
        validate_payload(event_type, payload)

    assert excinfo.value.error_code is SYS_EVENT_SCHEMA_INVALID


@pytest.mark.parametrize("event_type", sorted(VALID_PAYLOADS))
def test_unknown_field_rejected(event_type: str) -> None:
    """No invented fields: every payload schema is closed (IMPLEMENTATION_ROADMAP.md §5)."""
    with pytest.raises(EventSchemaInvalidError):
        validate_payload(event_type, VALID_PAYLOADS[event_type] | {"extra_field": 1})


@pytest.mark.parametrize(
    "event_type",
    ["DEAL_SCORED", "PURCHASE_REQUESTED", "PURCHASE_TASK_CREATED"],
)
def test_marketplace_is_required_and_enum_bound(event_type: str) -> None:
    """Task 1.3 names these three explicitly — the carried-not-re-derived field."""
    payload = dict(VALID_PAYLOADS[event_type])
    assert payload["marketplace"] in set(MarketplaceCode)

    del payload["marketplace"]
    with pytest.raises(EventSchemaInvalidError):
        validate_payload(event_type, payload)

    with pytest.raises(EventSchemaInvalidError):
        validate_payload(event_type, VALID_PAYLOADS[event_type] | {"marketplace": "EBAY"})


@pytest.mark.parametrize("field", ["listing_id", "quantity"])
@pytest.mark.parametrize("event_type", ["PURCHASE_COMPLETED", "PURCHASE_FAILED"])
def test_purchase_outcome_echoed_fields_required(event_type: str, field: str) -> None:
    """PurchaseOutcome.listing_id/quantity — Inventory Service has no other source for them."""
    outcome = dict(VALID_PAYLOADS[event_type]["outcome"])
    del outcome[field]

    with pytest.raises(EventSchemaInvalidError):
        validate_payload(event_type, {"outcome": outcome})


def test_purchase_completed_requires_success_true() -> None:
    outcome = VALID_PAYLOADS["PURCHASE_COMPLETED"]["outcome"] | {"success": False}
    with pytest.raises(EventSchemaInvalidError):
        validate_payload("PURCHASE_COMPLETED", {"outcome": outcome})


def test_purchase_failed_requires_success_false() -> None:
    outcome = VALID_PAYLOADS["PURCHASE_FAILED"]["outcome"] | {"success": True}
    with pytest.raises(EventSchemaInvalidError):
        validate_payload("PURCHASE_FAILED", {"outcome": outcome})


def test_dead_lettered_error_code_is_fixed() -> None:
    """§7 types this field as the literal SYS_DEAD_LETTERED, not a free code."""
    payload = VALID_PAYLOADS["EVENT_DEAD_LETTERED"] | {"error_code": "PURCH_CHECKOUT_FAILED"}
    with pytest.raises(EventSchemaInvalidError):
        validate_payload("EVENT_DEAD_LETTERED", payload)


def test_unknown_event_type_rejected() -> None:
    with pytest.raises(EventSchemaInvalidError) as excinfo:
        validate_payload("NOT_AN_EVENT", {})
    assert excinfo.value.error_code is SYS_EVENT_SCHEMA_INVALID


@pytest.mark.parametrize("event_type", sorted(VALID_PAYLOADS))
def test_validate_event_accepts_full_wire_event(event_type: str) -> None:
    validate_event(envelope_for(event_type, VALID_PAYLOADS[event_type]))


def test_validate_event_rejects_unhandled_version() -> None:
    """VALIDATION_RULES.md §5: a known event_type at an unknown version is rejected."""
    event = envelope_for("USER_INTERESTED", VALID_PAYLOADS["USER_INTERESTED"]) | {"version": 2}
    with pytest.raises(EventSchemaInvalidError):
        validate_event(event)


def test_common_schema_enums_match_the_registry() -> None:
    """common.json is transcribed from ENUMS.md; assert it has not drifted."""
    defs = load_schema("common.json")["$defs"]
    assert defs["marketplace_code"]["enum"] == [m.value for m in MarketplaceCode]
    assert defs["event_producer_service"]["enum"] == [s.value for s in EventProducerService]


def test_canonical_product_rules_from_validation_rules() -> None:
    """Spot-check the VALIDATION_RULES.md §1 constraints the schema can express."""
    for bad in (
        {"price": 0},
        {"canonical_title": ""},
        {"rating": 5.5},
        {"review_count": -1},
        {"in_stock": None},
        {"marketplace": "EBAY"},
    ):
        with pytest.raises(EventSchemaInvalidError):
            validate_payload("LISTING_DISCOVERED", {"product": CANONICAL_PRODUCT | bad})


def test_canonical_product_nullable_fields_may_be_null() -> None:
    nullable = dict.fromkeys(
        ["brand_name", "category", "subcategory", "image_url", "mrp", "rating", "review_count"]
    )
    validate_payload("LISTING_DISCOVERED", {"product": CANONICAL_PRODUCT | nullable})


def test_allocation_plan_may_be_empty() -> None:
    """CANONICAL_MODELS.md: an empty allocations array with fully_satisfied=false is valid."""
    validate_payload(
        "ACCOUNT_ALLOCATION_RESPONSE",
        {
            "allocation_plan": {
                "order_id": UUID_A,
                "requested_quantity": 2,
                "allocations": [],
                "fully_satisfied": False,
            }
        },
    )
