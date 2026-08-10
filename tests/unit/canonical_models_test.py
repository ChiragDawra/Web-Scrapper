"""Canonical models vs. CANONICAL_MODELS.md — Sprint 1 Task 1.7.

Definition of Done: "Every field per model in `CANONICAL_MODELS.md` exists with
matching required/nullable-ness."

The models are dataclasses and the wire contract is JSON Schema, so the same
shape is written twice. These tests make the second copy non-authoritative:
every model's field set and required set is asserted against the schema that
already encodes `CANONICAL_MODELS.md`, and each model's `to_dict()` is pushed
through the real publish-path validator. A field added to one side only fails
here rather than at the first cross-service publish.

`ScoredDeal` and `RevalidationResult` have no `$def` of their own — they are
carried flat as the `DEAL_SCORED` and `DEAL_REVALIDATED` payloads — so they are
checked against those schemas instead. `DEAL_SCORED` additionally carries
`deal_id`, which the model does not have: a `ScoredDeal` is the scoring result,
which exists before the row it becomes.
"""

from __future__ import annotations

from dataclasses import MISSING, fields
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from libs.canonical_models import (
    Allocation,
    AllocationPlan,
    CanonicalProduct,
    PurchaseOutcome,
    RevalidationResult,
    ScoreBreakdown,
    ScoredDeal,
)
from libs.enums import CurrencyCode, EventProducerService, MarketplaceCode
from libs.event_bus.envelope import Envelope
from libs.event_bus.payloads import load_schema, validate_event

LISTING_ID = UUID("3f2504e0-4f89-41d3-9a0c-0305e82c3301")
DEAL_ID = UUID("3f2504e0-4f89-41d3-9a0c-0305e82c3302")
ORDER_ID = UUID("3f2504e0-4f89-41d3-9a0c-0305e82c3303")
ACCOUNT_ID = UUID("3f2504e0-4f89-41d3-9a0c-0305e82c3304")
TASK_ID = UUID("3f2504e0-4f89-41d3-9a0c-0305e82c3305")

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _canonical_models_def(name: str) -> dict[str, Any]:
    definition: dict[str, Any] = load_schema("canonical_models.json")["$defs"][name]
    return definition


# model class -> the schema object that fixes its shape, and any keys that
# schema has but the model deliberately does not carry.
SCHEMA_SOURCES: dict[type, tuple[dict[str, Any], set[str]]] = {
    CanonicalProduct: (_canonical_models_def("CanonicalProduct"), set()),
    ScoreBreakdown: (_canonical_models_def("ScoreBreakdown"), set()),
    AllocationPlan: (_canonical_models_def("AllocationPlan"), set()),
    PurchaseOutcome: (_canonical_models_def("PurchaseOutcome"), set()),
    ScoredDeal: (load_schema("deal_scored.json"), {"deal_id"}),
    RevalidationResult: (load_schema("deal_revalidated.json"), set()),
}


@pytest.mark.parametrize("model", SCHEMA_SOURCES, ids=lambda m: m.__name__)
def test_model_has_exactly_the_contracted_fields(model: type) -> None:
    schema, not_on_model = SCHEMA_SOURCES[model]

    assert {f.name for f in fields(model)} == set(schema["properties"]) - not_on_model


@pytest.mark.parametrize("model", SCHEMA_SOURCES, ids=lambda m: m.__name__)
def test_required_fields_are_the_ones_without_defaults(model: type) -> None:
    """Required in the contract == no default on the dataclass, both directions."""
    schema, not_on_model = SCHEMA_SOURCES[model]
    mandatory = {
        f.name for f in fields(model) if f.default is MISSING and f.default_factory is MISSING
    }

    assert mandatory == set(schema["required"]) - not_on_model


def _product() -> CanonicalProduct:
    return CanonicalProduct(
        canonical_title="Running Shoes",
        marketplace=MarketplaceCode.AMAZON,
        external_listing_id="B0TEST1234",
        url="https://www.amazon.in/dp/B0TEST1234",
        price=249_900,
        in_stock=True,
        brand_name="Acme",
        category="Footwear",
        subcategory="Running",
        attributes={"size": "9", "color": "black", "amazon_bullet": "carried opaquely"},
        image_url="https://m.media-amazon.com/images/I/test.jpg",
        mrp=499_900,
        rating=4.3,
        review_count=812,
    )


def _scored_deal() -> ScoredDeal:
    return ScoredDeal(
        listing_id=LISTING_ID,
        marketplace=MarketplaceCode.AMAZON,
        score=87.5,
        score_breakdown=ScoreBreakdown(
            discount_score=40.0,
            brand_score=20.0,
            rating_score=17.5,
            velocity_score=10.0,
            weights_version="v1",
        ),
        detected_price=249_900,
        reference_price=499_900,
        discount_pct=50.0,
        expires_at=NOW,
    )


def _allocation_plan() -> AllocationPlan:
    return AllocationPlan(
        order_id=ORDER_ID,
        requested_quantity=3,
        allocations=[Allocation(account_id=ACCOUNT_ID, quantity=3)],
        fully_satisfied=True,
    )


def _outcome() -> PurchaseOutcome:
    return PurchaseOutcome(
        purchase_task_id=TASK_ID,
        listing_id=LISTING_ID,
        quantity=2,
        success=True,
        attempt_count=1,
        marketplace_order_ref="402-1234567-0000001",
        actual_price_paid=499_800,
    )


def _revalidation_result() -> RevalidationResult:
    return RevalidationResult(
        deal_id=DEAL_ID,
        listing_id=LISTING_ID,
        current_price=249_900,
        in_stock=True,
        changed=False,
        checked_at=NOW,
    )


ROUND_TRIPS = [
    _product(),
    _scored_deal(),
    _allocation_plan(),
    _outcome(),
    _revalidation_result(),
    ScoreBreakdown(1.0, 2.0, 3.0, 4.0, "v1"),
    Allocation(account_id=ACCOUNT_ID, quantity=1),
]


@pytest.mark.parametrize("model", ROUND_TRIPS, ids=lambda m: type(m).__name__)
def test_to_dict_from_dict_round_trip(model: Any) -> None:
    assert type(model).from_dict(model.to_dict()) == model


def _publish_shape(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return Envelope.new(
        event_type=event_type,
        producer_service=EventProducerService.DEAL_ENGINE,
        payload=payload,
    ).to_dict()


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("LISTING_DISCOVERED", {"product": _product().to_dict()}),
        ("DEAL_SCORED", {"deal_id": str(DEAL_ID), **_scored_deal().to_dict()}),
        ("DEAL_REVALIDATED", _revalidation_result().to_dict()),
        ("ACCOUNT_ALLOCATION_RESPONSE", {"allocation_plan": _allocation_plan().to_dict()}),
        ("PURCHASE_COMPLETED", {"outcome": _outcome().to_dict()}),
    ],
)
def test_serialized_model_passes_the_real_publish_validator(
    event_type: str, payload: dict[str, Any]
) -> None:
    """`to_dict()` must survive the same validation an actual publish applies."""
    validate_event(_publish_shape(event_type, payload))


def test_optional_fields_default_to_the_contracted_values() -> None:
    """The connector-nullable half of CanonicalProduct, plus currency's INR default."""
    minimal = CanonicalProduct(
        canonical_title="Bare listing",
        marketplace=MarketplaceCode.FLIPKART,
        external_listing_id="FSN123",
        url="https://www.flipkart.com/p/FSN123",
        price=100,
        in_stock=False,
    )

    assert minimal.currency is CurrencyCode.INR
    assert minimal.attributes == {}
    assert (minimal.brand_name, minimal.mrp, minimal.rating, minimal.review_count) == (
        None,
        None,
        None,
        None,
    )


def test_attributes_carries_unknown_keys_opaquely() -> None:
    """Only size/color/variant are read downstream; anything else must survive untouched."""
    product = _product()

    assert product.to_dict()["attributes"]["amazon_bullet"] == "carried opaquely"


def test_allocated_quantity_is_derived_not_trusted_from_the_flag() -> None:
    """An under-allocation is a valid response, and drives PLANNING_FAILED."""
    partial = AllocationPlan(
        order_id=ORDER_ID,
        requested_quantity=5,
        allocations=[Allocation(account_id=ACCOUNT_ID, quantity=2)],
        fully_satisfied=False,
    )

    assert partial.allocated_quantity == 2


def test_empty_allocation_is_valid() -> None:
    empty = AllocationPlan(
        order_id=uuid4(), requested_quantity=1, allocations=[], fully_satisfied=False
    )

    assert empty.allocated_quantity == 0
    assert AllocationPlan.from_dict(empty.to_dict()) == empty
