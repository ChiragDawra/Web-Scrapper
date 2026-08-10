"""Shared event fixtures — one valid payload per `EVENT_SCHEMAS.md` event type.

Lives in `libs/testing` rather than in one test module because more than one
suite needs the same fixtures (the Task 1.3 schema tests and the Task 1.8 Event
Store Consumer tests, which run as separate pytest sessions from different
roots). Two hand-maintained copies of thirteen payloads would drift.

Every payload here is valid against its schema; a contract test asserts the set
of keys still matches `EVENT_PAYLOAD_SCHEMA_FILES` exactly, so a new event type
cannot be added without a fixture.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

__all__ = [
    "CANONICAL_PRODUCT",
    "PURCHASE_OUTCOME",
    "SCORE_BREAKDOWN",
    "TS",
    "UUID_A",
    "UUID_B",
    "UUID_C",
    "VALID_PAYLOADS",
    "envelope_for",
]

UUID_A = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
UUID_B = "3f2504e0-4f89-41d3-9a0c-0305e82c3302"
UUID_C = "3f2504e0-4f89-41d3-9a0c-0305e82c3303"
TS = "2026-01-01T12:00:00+00:00"

CANONICAL_PRODUCT: dict[str, Any] = {
    "canonical_title": "Nike Air Zoom Pegasus 40",
    "brand_name": "Nike",
    "category": "Footwear",
    "subcategory": "Running",
    "attributes": {"size": "9", "color": "Black", "variant": "Regular"},
    "image_url": "https://example.com/p.jpg",
    "marketplace": "AMAZON",
    "external_listing_id": "B0BXYZ1234",
    "url": "https://www.amazon.in/dp/B0BXYZ1234",
    "price": 799900,
    "mrp": 1299500,
    "currency": "INR",
    "rating": 4.4,
    "review_count": 1820,
    "in_stock": True,
}

SCORE_BREAKDOWN: dict[str, Any] = {
    "discount_score": 38.5,
    "brand_score": 20.0,
    "rating_score": 12.5,
    "velocity_score": 9.0,
    "weights_version": "v1",
}

PURCHASE_OUTCOME: dict[str, Any] = {
    "purchase_task_id": UUID_A,
    "listing_id": UUID_B,
    "quantity": 2,
    "success": True,
    "marketplace_order_ref": "406-1234567-8901234",
    "actual_price_paid": 1599800,
    "error_code": None,
    "attempt_count": 1,
}

VALID_PAYLOADS: dict[str, dict[str, Any]] = {
    "LISTING_DISCOVERED": {"product": CANONICAL_PRODUCT},
    "DEAL_SCORED": {
        "deal_id": UUID_A,
        "listing_id": UUID_B,
        "marketplace": "AMAZON",
        "score": 80.0,
        "score_breakdown": SCORE_BREAKDOWN,
        "detected_price": 799900,
        "reference_price": 1299500,
        "discount_pct": 0.3845,
        "expires_at": TS,
    },
    "USER_INTERESTED": {"deal_id": UUID_A, "telegram_user_id": UUID_B},
    "DEAL_REVALIDATION_REQUEST": {
        "deal_id": UUID_A,
        "listing_id": UUID_B,
        "correlation_id": UUID_A,
    },
    "DEAL_REVALIDATED": {
        "deal_id": UUID_A,
        "listing_id": UUID_B,
        "current_price": 809900,
        "in_stock": True,
        "changed": False,
        "checked_at": TS,
    },
    "PURCHASE_REQUESTED": {
        "order_id": UUID_A,
        "deal_id": UUID_B,
        "listing_id": UUID_C,
        "marketplace": "FLIPKART",
        "telegram_user_id": UUID_A,
        "requested_quantity": 2,
        "unit_price": 799900,
    },
    "ACCOUNT_ALLOCATION_REQUEST": {
        "order_id": UUID_A,
        "marketplace": "FLIPKART",
        "requested_quantity": 2,
        "correlation_id": UUID_A,
    },
    "ACCOUNT_ALLOCATION_RESPONSE": {
        "allocation_plan": {
            "order_id": UUID_A,
            "requested_quantity": 2,
            "allocations": [{"account_id": UUID_B, "quantity": 2}],
            "fully_satisfied": True,
        }
    },
    "PURCHASE_TASK_CREATED": {
        "purchase_task_id": UUID_A,
        "order_id": UUID_B,
        "account_id": UUID_C,
        "listing_id": UUID_A,
        "marketplace": "MYNTRA",
        "quantity": 2,
        "max_price": 799900,
    },
    "PURCHASE_COMPLETED": {"outcome": PURCHASE_OUTCOME},
    "PURCHASE_FAILED": {
        "outcome": PURCHASE_OUTCOME
        | {
            "success": False,
            "marketplace_order_ref": None,
            "actual_price_paid": None,
            "error_code": "PURCH_PRICE_MISMATCH",
            "attempt_count": 3,
        }
    },
    "ACCOUNT_HEALTH_CHANGED": {
        "account_id": UUID_A,
        "previous_status": "ACTIVE",
        "new_status": "COOLDOWN",
        "previous_health_score": 85,
        "new_health_score": 60,
        "reason": "PURCHASE_FAILED delta",
    },
    "EVENT_DEAD_LETTERED": {
        "original_event_id": UUID_A,
        "original_event_type": "PURCHASE_TASK_CREATED",
        "consumer_service": "purchase-agent",
        "error_code": "SYS_DEAD_LETTERED",
        "attempt_count": 3,
    },
}


def envelope_for(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a payload in a valid envelope (`EVENT_SCHEMAS.md` §1) with a fresh `event_id`."""
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "version": 1,
        "correlation_id": None,
        "producer_service": "deal-engine",
        "produced_at": TS,
        "payload": payload,
    }
