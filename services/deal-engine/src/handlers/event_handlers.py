"""Event handlers — Sprint 3 Tasks 3.5 and 3.6.

`LISTING_DISCOVERED` in, `DEAL_SCORED` out (`EVENT_SCHEMAS.md` §2). One handled
event is one transaction: ingest the observation, score it, and — only if it
clears the thresholds and the listing has no open deal — write the deal and
publish. The caller commits once, after the handler returns.

Ordering inside that transaction matters in one place. The `DEAL_SCORED` XADD
is not transactional and cannot be rolled back, so it happens *after* the
insert but before the commit: a crash in that window republishes an event whose
deal never existed, which the bot's own dedup absorbs, whereas publishing first
would announce a deal that a rollback then erased.

The `marketplace` on the outgoing event is joined here from `listings` and
`marketplaces` — both Deal-Engine-owned — and then carried opaquely by every
downstream consumer, so nobody re-derives it with a cross-service read
(ADR-009, `CANONICAL_MODELS.md` §ScoredDeal).

`USER_INTERESTED` (Task 3.6) is the one write that moves an existing deal's
status. The legal edge is `DEAL_SENT -> INTERESTED` and nothing else
(`STATE_TRANSITIONS.md` §1); everything that is not that edge — an expired
deal, a terminal deal, a second tap — is rejected as a no-op rather than
raising, because none of them become legal on redelivery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from psycopg import Connection

from libs.canonical_models import CanonicalProduct
from libs.canonical_models.scored_deal import ScoredDeal
from libs.enums import DealStatus, MarketplaceCode
from libs.event_bus import Envelope
from libs.event_bus.consumer import ReceivedEvent
from libs.event_bus.publisher import EventPublisher
from src.config import PRODUCER_SERVICE
from src.repositories.brand_repo import BrandRepository
from src.repositories.deal_repo import DealRepository
from src.repositories.listing_repo import Listing, ListingRepository
from src.repositories.marketplace_repo import MarketplaceRepository
from src.repositories.price_history_repo import PriceHistoryRepository
from src.repositories.product_repo import ProductRepository
from src.services.brand_resolver import resolve_brand
from src.services.deal_writer import write_deal
from src.services.scorer import DEFAULT_CONFIG, ScoringConfig, score

__all__ = [
    "DEAL_SCORED",
    "LISTING_DISCOVERED",
    "USER_INTERESTED",
    "HandledInterest",
    "HandledListing",
    "InterestRejection",
    "deal_scored_event",
    "handle_listing_discovered",
    "handle_user_interested",
]

logger: Final = logging.getLogger(__name__)

LISTING_DISCOVERED: Final = "LISTING_DISCOVERED"
DEAL_SCORED: Final = "DEAL_SCORED"
USER_INTERESTED: Final = "USER_INTERESTED"

#: The only status a tap may be applied from (`STATE_TRANSITIONS.md` §1).
#: `WATCHING` is not here: a watched deal is re-notified back to `DEAL_SENT`
#: first, and that re-notification is the notification worker's edge, not this
#: handler's to shortcut.
INTEREST_SOURCE_STATUS: Final = DealStatus.DEAL_SENT


@dataclass(frozen=True, slots=True)
class HandledListing:
    """What one `LISTING_DISCOVERED` did, for logging and for tests.

    `deal` is `None` for the ordinary below-threshold case — a silent skip
    (`VALIDATION_RULES.md` §2), not an error. `published` is separately false
    when a deal already existed: the listing is scored, but re-announcing an
    open deal every scan is how one bargain becomes six notifications.
    """

    listing_id: UUID
    scored: ScoredDeal | None
    deal_id: UUID | None
    published: bool


def handle_listing_discovered(
    conn: Connection,
    publisher: EventPublisher,
    event: ReceivedEvent,
    *,
    scoring_config: ScoringConfig = DEFAULT_CONFIG,
) -> HandledListing:
    """Ingest, score, persist, and emit `DEAL_SCORED` when there is one to emit."""
    product = CanonicalProduct.from_dict(event.envelope.payload["product"])
    marketplace = _marketplace_id(conn, product.marketplace)

    listing = _upsert_listing(conn, product, marketplace_id=marketplace)

    history = PriceHistoryRepository(conn)
    history.insert(listing.id, product.price, product.in_stock)
    stats = history.stats(listing.id, window_days=scoring_config.history_window_days)

    brand = BrandRepository(conn).find_by_name(product.brand_name) if product.brand_name else None

    scored = score(
        product,
        listing_id=listing.id,
        brand_tier=brand.tier if brand else None,
        price_stats=stats,
        config=scoring_config,
    )
    if scored is None:
        logger.debug("listing %s did not clear the scoring thresholds", listing.id)
        return HandledListing(listing_id=listing.id, scored=None, deal_id=None, published=False)

    result = write_deal(DealRepository(conn), scored)
    if not result.created:
        return HandledListing(
            listing_id=listing.id, scored=scored, deal_id=result.deal.id, published=False
        )

    publisher.publish(deal_scored_event(result.deal.id, scored))
    logger.info(
        "deal %s scored %.2f on listing %s (%s)",
        result.deal.id,
        scored.score,
        listing.id,
        product.marketplace,
    )
    return HandledListing(
        listing_id=listing.id, scored=scored, deal_id=result.deal.id, published=True
    )


class InterestRejection(StrEnum):
    """Why a tap was not applied. Every value is a normal outcome, not an error."""

    NO_SUCH_DEAL = "NO_SUCH_DEAL"
    EXPIRED = "EXPIRED"
    ALREADY_INTERESTED = "ALREADY_INTERESTED"
    WRONG_STATUS = "WRONG_STATUS"


@dataclass(frozen=True, slots=True)
class HandledInterest:
    """What one `USER_INTERESTED` did.

    `applied` and `rejection` are exclusive: an applied tap has no rejection,
    and a rejected one names its reason so the log says which guard fired.
    """

    deal_id: UUID
    applied: bool
    status: DealStatus | None
    rejection: InterestRejection | None


def handle_user_interested(
    conn: Connection,
    publisher: EventPublisher,
    event: ReceivedEvent,
    *,
    scoring_config: ScoringConfig = DEFAULT_CONFIG,
) -> HandledInterest:
    """Apply `DEAL_SENT -> INTERESTED`, or reject the tap.

    `publisher` and `scoring_config` are unused and kept anyway: every handler
    in `main.HANDLERS` is called through one signature, and a special case
    there would be worse than two ignored arguments here. Nothing is rescored
    on this edge — `STATE_TRANSITIONS.md` §1, "No in-place rescoring".

    The Bot enforces the tap-after-expiry guard at the callback
    (`STATE_TRANSITIONS.md` §1) and so should not emit for an expired deal,
    but the guard is re-checked here: the Bot's view of `expires_at` is
    whatever it rendered into the message, and this handler owns the table.

    No event is published on this edge. The Bot emits
    `DEAL_REVALIDATION_REQUEST` itself once its callback succeeds — the Deal
    Engine publishing it too would start two revalidation rounds per tap.
    """
    deal_id = UUID(str(event.envelope.payload["deal_id"]))
    repo = DealRepository(conn)

    deal = repo.get_by_id(deal_id, for_update=True)
    if deal is None:
        return _rejected(deal_id, None, InterestRejection.NO_SUCH_DEAL)

    if deal.status is DealStatus.EXPIRED:
        return _rejected(deal_id, deal.status, InterestRejection.EXPIRED)

    if deal.expires_at <= datetime.now(UTC):
        # Lazily applies the §1 edge "expires_at reached, no action -> EXPIRED".
        # Nothing sweeps deals to EXPIRED yet (that worker is Sprint 6), so a
        # tap that arrives late would otherwise pass the status guard on a deal
        # whose price is no longer being honored.
        repo.update_status(deal_id, DealStatus.EXPIRED)
        logger.info("deal %s expired at %s; tap rejected", deal_id, deal.expires_at)
        return _rejected(deal_id, DealStatus.EXPIRED, InterestRejection.EXPIRED)

    if deal.status is DealStatus.INTERESTED:
        # A double tap, or the same tap redelivered past its dedup mark. The
        # deal is already where the user wants it, so this is idempotent.
        return _rejected(deal_id, deal.status, InterestRejection.ALREADY_INTERESTED)

    if deal.status is not INTEREST_SOURCE_STATUS:
        logger.info(
            "deal %s is %s, not %s; tap rejected", deal_id, deal.status, INTEREST_SOURCE_STATUS
        )
        return _rejected(deal_id, deal.status, InterestRejection.WRONG_STATUS)

    updated = repo.update_status(deal_id, DealStatus.INTERESTED)
    if updated is None:
        # Read under `FOR UPDATE` and gone by the update: the row was deleted
        # inside this transaction's own snapshot, which no code path does.
        raise RuntimeError(f"deal {deal_id} vanished between lock and update")

    logger.info("deal %s moved to %s", deal_id, updated.status)
    return HandledInterest(deal_id=deal_id, applied=True, status=updated.status, rejection=None)


def _rejected(
    deal_id: UUID, status: DealStatus | None, rejection: InterestRejection
) -> HandledInterest:
    logger.debug("tap on deal %s rejected: %s", deal_id, rejection)
    return HandledInterest(deal_id=deal_id, applied=False, status=status, rejection=rejection)


def deal_scored_event(
    deal_id: UUID, scored: ScoredDeal, *, correlation_id: UUID | None = None
) -> Envelope:
    """The `DEAL_SCORED` envelope (`EVENT_SCHEMAS.md` §2).

    `deal_id` is the one field `ScoredDeal` does not carry — the model is the
    scoring result and exists before the row does, so the id is added at
    publish time rather than back-filled into the model.
    """
    payload: dict[str, Any] = scored.to_dict()
    payload["deal_id"] = str(deal_id)
    return Envelope.new(
        event_type=DEAL_SCORED,
        producer_service=PRODUCER_SERVICE,
        payload=payload,
        correlation_id=correlation_id,
    )


def _marketplace_id(conn: Connection, code: MarketplaceCode) -> UUID:
    """The seeded `marketplaces` row for `code`.

    A miss is a deployment failure, not a listing problem (`DATABASE_SCHEMA.md`
    §2: seeded per code, no dynamic inserts), so it raises — the event stays
    unacknowledged and is retried once the seed is in place, rather than being
    dropped.
    """
    marketplace = MarketplaceRepository(conn).find_by_code(code)
    if marketplace is None:
        raise LookupError(f"marketplaces has no seeded row for {code}; run the seed migration")
    return marketplace.id


def _upsert_listing(
    conn: Connection, product: CanonicalProduct, *, marketplace_id: UUID
) -> Listing:
    """Find the listing this event describes, creating it and its product if new.

    A second connector poll of the same ASIN is the common case, so the lookup
    comes first. `products` is only written on a genuine miss — the product
    matcher that would collapse two listings onto one product is Sprint 11, and
    until it exists a new listing gets its own product row rather than a guess.
    """
    listings = ListingRepository(conn)
    existing = listings.find_by_external(marketplace_id, product.external_listing_id)
    if existing is not None:
        updated = listings.update_observation(
            existing.id,
            current_price=product.price,
            mrp=product.mrp,
            rating=_as_rating(product.rating),
            review_count=product.review_count,
            in_stock=product.in_stock,
            url=product.url,
        )
        return updated or existing

    brand_id = resolve_brand(BrandRepository(conn), product.brand_name)
    new_product = ProductRepository(conn).insert(
        brand_id=brand_id,
        canonical_title=product.canonical_title,
        category=product.category,
        subcategory=product.subcategory,
        attributes=product.attributes,
        image_url=product.image_url,
    )
    inserted = listings.insert(
        product_id=new_product.id,
        marketplace_id=marketplace_id,
        external_listing_id=product.external_listing_id,
        url=product.url,
        current_price=product.price,
        currency=product.currency,
        mrp=product.mrp,
        rating=_as_rating(product.rating),
        review_count=product.review_count,
        in_stock=product.in_stock,
    )
    if inserted is not None:
        return inserted

    # `DO NOTHING` fired: another worker inserted the same (marketplace,
    # external id) between the lookup and the insert. Re-read, as with brands.
    reread = listings.find_by_external(marketplace_id, product.external_listing_id)
    if reread is None:
        raise RuntimeError(
            f"listing {product.external_listing_id} conflicted on insert but is not readable"
        )
    return reread


def _as_rating(rating: float | None) -> Decimal | None:
    """`listings.rating` is `NUMERIC(2,1)`; the model carries a float.

    Through `str` and rounded once here, for the same reason `deal_writer`
    does it: `Decimal(4.3)` is `4.2999...`, and letting the driver round hides
    where the precision went.
    """
    if rating is None:
        return None
    return Decimal(str(round(rating, 1)))
