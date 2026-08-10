"""`CANONICAL_MODELS.md` §RevalidationResult — Sprint 1 Task 1.7.

Produced by the Revalidation Service, consumed by the Telegram Bot. Carried
flat as the `DEAL_REVALIDATED` payload (`EVENT_SCHEMAS.md` §3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from libs.event_bus.envelope import parse_timestamp, parse_uuid

__all__ = ["RevalidationResult"]


@dataclass(frozen=True, slots=True)
class RevalidationResult:
    """A live re-read of a listing at confirmation time."""

    deal_id: UUID
    listing_id: UUID
    current_price: int
    in_stock: bool
    # True if the price delta exceeded the tolerance or `in_stock` flipped. The
    # tolerance itself (2%) belongs to VALIDATION_RULES.md §5 and is applied by
    # the Revalidation Service — this model only carries the verdict, so a
    # consumer never re-derives it against a stale threshold.
    changed: bool
    checked_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "deal_id": str(self.deal_id),
            "listing_id": str(self.listing_id),
            "current_price": self.current_price,
            "in_stock": self.in_stock,
            "changed": self.changed,
            "checked_at": self.checked_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RevalidationResult:
        return cls(
            deal_id=parse_uuid(data["deal_id"], "deal_id"),
            listing_id=parse_uuid(data["listing_id"], "listing_id"),
            current_price=data["current_price"],
            in_stock=data["in_stock"],
            changed=data["changed"],
            checked_at=parse_timestamp(data["checked_at"], "checked_at"),
        )
