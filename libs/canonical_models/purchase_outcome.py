"""`CANONICAL_MODELS.md` §PurchaseOutcome — Sprint 1 Task 1.7.

Produced by a Purchase Agent on task completion or failure; consumed by the
Order Planner, Inventory Service, Account Service and ML Service.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from libs.event_bus.envelope import parse_uuid

__all__ = ["PurchaseOutcome"]


@dataclass(frozen=True, slots=True)
class PurchaseOutcome:
    """The result of one purchase task attempt sequence."""

    purchase_task_id: UUID
    # listing_id and quantity are echoed from PURCHASE_TASK_CREATED: the
    # Inventory Service's recordAcquisition (SERVICE_INTERFACES.md §8) needs
    # both and, owning only inventory_items, has no other source for them
    # (ADR-009 forbids reading another service's tables).
    listing_id: UUID
    quantity: int
    success: bool
    attempt_count: int
    # Set only when success=true.
    marketplace_order_ref: str | None = None
    actual_price_paid: int | None = None
    # One of ERROR_CODES.md, set only when success=false. The success/field
    # coupling is enforced by the producing Purchase Agent, not by this type —
    # expressing it here would mean two variant classes for one documented model.
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "purchase_task_id": str(self.purchase_task_id),
            "listing_id": str(self.listing_id),
            "quantity": self.quantity,
            "success": self.success,
            "marketplace_order_ref": self.marketplace_order_ref,
            "actual_price_paid": self.actual_price_paid,
            "error_code": self.error_code,
            "attempt_count": self.attempt_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PurchaseOutcome:
        return cls(
            purchase_task_id=parse_uuid(data["purchase_task_id"], "purchase_task_id"),
            listing_id=parse_uuid(data["listing_id"], "listing_id"),
            quantity=data["quantity"],
            success=data["success"],
            attempt_count=data["attempt_count"],
            marketplace_order_ref=data.get("marketplace_order_ref"),
            actual_price_paid=data.get("actual_price_paid"),
            error_code=data.get("error_code"),
        )
