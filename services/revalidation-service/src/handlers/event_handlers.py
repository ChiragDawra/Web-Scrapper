"""Event handlers — Sprint 5 Tasks 5.2 and 5.3.

`DEAL_REVALIDATION_REQUEST` in, `DEAL_REVALIDATED` out (`EVENT_SCHEMAS.md` §3).
`DEAL_SCORED` in, nothing out — it only feeds the reference projection
(`deal_reference.py`).

Correlation threading, `RESOLVED_QUESTIONS.md` Q15: "`DEAL_REVALIDATION_REQUEST`
sets it to `deal_id` — propagated unchanged by every downstream event in that
chain." The outgoing `correlation_id` is therefore copied from the request's
payload rather than regenerated or taken from the envelope, and a request whose
payload `correlation_id` is not its `deal_id` is a contract violation on the
producer's side that this service refuses rather than silently re-labels.

Nothing is published in three cases, each for its own reason:

* Timeout (`BudgetExceededError`, Task 5.3) — the Bot has already fail-safed to
  `PRICE_CHANGED`, and a late answer would consume the one re-confirmation
  `STATE_TRANSITIONS.md` §1 allows per deal.
* Unknown deal — the tolerance has no reference price to measure against, and
  the `DEAL_SCORED` that would supply it is either older than Redis retention or
  never happened. Raising leaves the event unacknowledged so a redelivery can
  find a warmed projection; see `_MissingReference` on why that stops.
* Unreadable listing (`ListingReadError`) — no price was observed, so there is
  no honest `RevalidationResult` to send.

In all three the Bot's 30s `REVAL_TIMEOUT` is the backstop, which is exactly the
fail-safe direction: silence becomes "treat as changed, force re-confirmation",
never "confirm at a price nobody checked".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from libs.canonical_models import RevalidationResult
from libs.event_bus import Envelope
from libs.event_bus.consumer import ReceivedEvent
from libs.event_bus.envelope import parse_uuid
from libs.event_bus.publisher import EventPublisher
from src.config import PRODUCER_SERVICE
from src.services.deal_reference import DealReference, DealReferenceStore
from src.services.listing_source import ListingReadError, ListingSource
from src.services.revalidator import BudgetExceededError, TimeoutBudget, revalidate

__all__ = [
    "DEAL_REVALIDATED",
    "DEAL_REVALIDATION_REQUEST",
    "DEAL_SCORED",
    "HandledRequest",
    "UnknownDealError",
    "handle_deal_revalidation_request",
    "handle_deal_scored",
    "revalidated_event",
]

logger: Final = logging.getLogger(__name__)

DEAL_SCORED: Final = "DEAL_SCORED"
DEAL_REVALIDATION_REQUEST: Final = "DEAL_REVALIDATION_REQUEST"
DEAL_REVALIDATED: Final = "DEAL_REVALIDATED"


class UnknownDealError(LookupError):
    """No `DEAL_SCORED` for this `deal_id` reached this process.

    A `LookupError`, and raised rather than swallowed, so the event stays
    unacknowledged and Redis redelivers it: the ordinary cause is a request
    arriving before the projection finished warming, and that fixes itself within
    one redelivery. The cause that does not fix itself — a `DEAL_SCORED` older
    than stream retention — is bounded by the consumer's own retry handling
    rather than by an unbounded loop here, and its user-visible outcome is the
    Bot's `REVAL_TIMEOUT` fail-safe either way.
    """


@dataclass(frozen=True, slots=True)
class HandledRequest:
    """What one request produced. `result` is `None` when nothing was published."""

    deal_id: UUID
    listing_id: UUID
    result: RevalidationResult | None
    published: bool


def handle_deal_scored(event: ReceivedEvent, *, references: DealReferenceStore) -> DealReference:
    """Record one scored deal's reference price. No side effects beyond the projection.

    This service is not `DEAL_SCORED`'s consumer in the contract sense — the Bot
    is (`EVENT_SCHEMAS.md` §2) — and consumer groups are per-service, so reading
    the stream here takes nothing away from it.
    """
    reference = references.record(event.envelope.payload)
    logger.debug(
        "recorded deal %s listing %s at %d paise",
        reference.deal_id,
        reference.listing_id,
        reference.detected_price,
    )
    return reference


def handle_deal_revalidation_request(
    publisher: EventPublisher,
    event: ReceivedEvent,
    *,
    references: DealReferenceStore,
    source: ListingSource,
    budget: TimeoutBudget | None = None,
) -> HandledRequest:
    """Read the listing live and publish `DEAL_REVALIDATED`, or publish nothing.

    `budget` is injected by the caller so the countdown starts at delivery
    (`main.py`); tests pass an expired one to assert the Task 5.3 guard.
    """
    payload = event.envelope.payload
    deal_id = parse_uuid(payload["deal_id"], "deal_id")
    listing_id = parse_uuid(payload["listing_id"], "listing_id")
    correlation_id = _correlation_id(payload, deal_id)
    budget = budget or TimeoutBudget()

    reference = references.get(deal_id)
    if reference is None:
        raise UnknownDealError(
            f"no DEAL_SCORED seen for deal {deal_id}; cannot measure the "
            "VALIDATION_RULES.md §5 tolerance without its detected_price"
        )
    if reference.listing_id != listing_id:
        # The request names a listing that is not the one the deal was scored
        # against. Revalidating it would compare two different listings' prices
        # and call the result a tolerance check.
        raise ValueError(
            f"deal {deal_id} was scored against listing {reference.listing_id}, "
            f"request names {listing_id}"
        )

    try:
        result = revalidate(
            listing_id,
            detected_price=reference.detected_price,
            deal_id=deal_id,
            source=source,
            budget=budget,
        )
    except BudgetExceededError as exc:
        # Task 5.3's whole point: the window closed, so this is where the event
        # is *not* emitted. WARNING, matching `REVAL_TIMEOUT`'s severity.
        logger.warning("%s", exc)
        return HandledRequest(deal_id=deal_id, listing_id=listing_id, result=None, published=False)
    except ListingReadError as exc:
        logger.warning(
            "%s: deal %s listing %s unreadable (retryable=%s), not emitting %s: %s",
            exc.code,
            deal_id,
            listing_id,
            exc.retryable,
            DEAL_REVALIDATED,
            exc.detail or "no detail",
        )
        return HandledRequest(deal_id=deal_id, listing_id=listing_id, result=None, published=False)

    # Checked once more immediately before the publish. The read finished inside
    # the window, but validation and the XADD are also spent out of it, and §3's
    # rule is about what the Bot receives in time, not what this service computed
    # in time.
    if budget.expired():
        logger.warning(
            "%s: dropping %s for deal %s, budget closed after the read",
            "REVAL_TIMEOUT",
            DEAL_REVALIDATED,
            deal_id,
        )
        return HandledRequest(deal_id=deal_id, listing_id=listing_id, result=None, published=False)

    publisher.publish(revalidated_event(result, correlation_id=correlation_id))
    logger.info(
        "published %s for deal %s: changed=%s, price=%d, in_stock=%s, %.2fs of %ds used",
        DEAL_REVALIDATED,
        deal_id,
        result.changed,
        result.current_price,
        result.in_stock,
        budget.elapsed_seconds,
        budget.budget_seconds,
    )
    return HandledRequest(deal_id=deal_id, listing_id=listing_id, result=result, published=True)


def revalidated_event(result: RevalidationResult, *, correlation_id: UUID) -> Envelope:
    """The `DEAL_REVALIDATED` envelope (`EVENT_SCHEMAS.md` §3).

    `RevalidationResult` is carried flat, not nested under a key — §3 and
    `deal_revalidated.json` both spell the payload as the model's own fields, and
    `to_dict()` is already that shape.

    `correlation_id` is required, not optional: this event only ever exists as the
    answer to a request that set one, so there is no call site that legitimately
    has none, and defaulting it to `None` would let a threading bug publish
    successfully.
    """
    return Envelope.new(
        event_type=DEAL_REVALIDATED,
        producer_service=PRODUCER_SERVICE,
        payload=result.to_dict(),
        correlation_id=correlation_id,
    )


def _correlation_id(payload: dict[str, Any], deal_id: UUID) -> UUID:
    """The request's payload `correlation_id`, which Q15 fixes as the `deal_id`.

    Read from the payload rather than the envelope because §3 requires it *in the
    payload* ("Required in the payload (not merely in the envelope)"), and
    validated against `deal_id` because the whole point of the convention is that
    every revalidation round for one deal threads together. A mismatch is the
    producer's bug; accepting it here would scatter one deal's rounds across two
    correlation ids and quietly break the audit trail this field exists for.
    """
    correlation_id = parse_uuid(payload["correlation_id"], "correlation_id")
    if correlation_id != deal_id:
        raise ValueError(
            f"correlation_id {correlation_id} must equal deal_id {deal_id} "
            "(RESOLVED_QUESTIONS.md Q15)"
        )
    return correlation_id
