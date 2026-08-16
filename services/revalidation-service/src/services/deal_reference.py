"""What price a deal was scored at — Sprint 5 Task 5.1.

`VALIDATION_RULES.md` §5 measures the tolerance against `detected_price`, and
`DEAL_REVALIDATION_REQUEST` (`EVENT_SCHEMAS.md` §3) carries only `deal_id`,
`listing_id` and `correlation_id`. So the reference price has to come from
somewhere, and there are exactly two candidates:

1. `SELECT detected_price FROM deals` — forbidden. `deals` is Deal-Engine-owned
   and ADR-009 is explicit: "Cross-service data needs are satisfied by consuming
   events, never by joining across ownership boundaries."
2. `DEAL_SCORED`, which carries `detected_price` for every deal that exists.

This is (2). The store is in-memory, which is what keeps
`SERVICE_INTERFACES.md` §3's "stateless" true, and it survives a restart for a
structural reason rather than a lucky one: `EventConsumer` creates its group at
id `0`, not `$` (`consumer.py`), so a fresh boot replays every retained
`DEAL_SCORED` before it reaches the first request and the projection warms
itself. What bounds it is Redis stream retention, not this process.

A request for a deal that is not in the projection is answered by *not*
answering — see `event_handlers.py`. Guessing a reference price is the one thing
this module must never do, because the guess decides whether a user's money
moves at a price they were never shown.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from libs.enums import MarketplaceCode
from libs.event_bus.envelope import parse_uuid

__all__ = ["DEFAULT_MAX_DEALS", "DealReference", "DealReferenceStore"]

logger: Final = logging.getLogger(__name__)

#: How many scored deals to remember. Deals expire after 24h
#: (`RESOLVED_QUESTIONS.md` Q36) and only a deal the user taps is ever
#: revalidated, so the working set is far smaller than this; the cap exists so a
#: long-lived process cannot grow without bound on a stream it does not control.
DEFAULT_MAX_DEALS: Final = 50_000


@dataclass(frozen=True, slots=True)
class DealReference:
    """The scored-time facts one revalidation needs.

    `in_stock` is absent on purpose, not overlooked: `DEAL_SCORED` does not carry
    a stock flag, so the baseline for §1's "any change in `in_stock`" is unknown
    here and `revalidation_changed()` is told so explicitly.
    """

    deal_id: UUID
    listing_id: UUID
    marketplace: MarketplaceCode
    detected_price: int


class DealReferenceStore:
    """`deal_id` -> `DealReference`, oldest evicted first once `max_deals` is reached."""

    def __init__(self, *, max_deals: int = DEFAULT_MAX_DEALS) -> None:
        self._references: OrderedDict[UUID, DealReference] = OrderedDict()
        self._max_deals = max_deals

    def __len__(self) -> int:
        return len(self._references)

    def record(self, payload: Mapping[str, Any]) -> DealReference:
        """Remember one `DEAL_SCORED` payload (`EVENT_SCHEMAS.md` §2)."""
        reference = DealReference(
            deal_id=parse_uuid(payload["deal_id"], "deal_id"),
            listing_id=parse_uuid(payload["listing_id"], "listing_id"),
            marketplace=MarketplaceCode(payload["marketplace"]),
            detected_price=payload["detected_price"],
        )
        # Re-scoring never happens in place (`STATE_TRANSITIONS.md` §1), so a
        # repeated `deal_id` is a stream redelivery of the same facts. Overwrite
        # and re-mark as most-recent rather than skip: the values are identical
        # and the recency is the useful part.
        self._references[reference.deal_id] = reference
        self._references.move_to_end(reference.deal_id)
        while len(self._references) > self._max_deals:
            evicted, _ = self._references.popitem(last=False)
            logger.debug("evicted deal reference %s at cap %d", evicted, self._max_deals)
        return reference

    def get(self, deal_id: UUID) -> DealReference | None:
        """The reference for one deal, or `None` if this process never saw it scored."""
        return self._references.get(deal_id)
