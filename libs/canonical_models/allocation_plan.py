"""`CANONICAL_MODELS.md` §AllocationPlan — Sprint 1 Task 1.7.

Produced by the Account Service answering `ACCOUNT_ALLOCATION_REQUEST`,
consumed by the Order Planner.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from libs.event_bus.envelope import parse_uuid

__all__ = ["Allocation", "AllocationPlan"]


@dataclass(frozen=True, slots=True)
class Allocation:
    """One account's share of a requested quantity."""

    account_id: UUID
    quantity: int

    def to_dict(self) -> dict[str, Any]:
        return {"account_id": str(self.account_id), "quantity": self.quantity}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Allocation:
        return cls(
            account_id=parse_uuid(data["account_id"], "account_id"),
            quantity=data["quantity"],
        )


@dataclass(frozen=True, slots=True)
class AllocationPlan:
    """How an order's quantity is split across accounts.

    An empty `allocations` with `fully_satisfied=False` is a valid response, not
    an error — it is what drives `PLANNING_FAILED` (`STATE_TRANSITIONS.md` §2).
    """

    order_id: UUID
    requested_quantity: int
    allocations: Sequence[Allocation]
    # True if sum(allocations.quantity) == requested_quantity. Carried as a flag
    # rather than derived on read because VALIDATION_RULES.md §5 has the Order
    # Planner trust it as-is; `allocated_quantity` exists for callers that want
    # the sum for their own reporting, never to second-guess this.
    fully_satisfied: bool

    @property
    def allocated_quantity(self) -> int:
        return sum(allocation.quantity for allocation in self.allocations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": str(self.order_id),
            "requested_quantity": self.requested_quantity,
            "allocations": [allocation.to_dict() for allocation in self.allocations],
            "fully_satisfied": self.fully_satisfied,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AllocationPlan:
        return cls(
            order_id=parse_uuid(data["order_id"], "order_id"),
            requested_quantity=data["requested_quantity"],
            allocations=[Allocation.from_dict(item) for item in data["allocations"]],
            fully_satisfied=data["fully_satisfied"],
        )
