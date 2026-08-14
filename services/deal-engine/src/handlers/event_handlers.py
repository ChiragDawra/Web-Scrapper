"""Event handlers — Sprint 3 Task 3.5.

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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from psycopg import Connection

from libs.canonical_models import CanonicalProduct
from libs.canonical_models.scored_deal import ScoredDeal
from libs.enums import MarketplaceCode
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
    "HandledListing",
    "deal_scored_event",
    "handle_listing_discovered",
]

logger: Final = logging.getLogger(__name__)

LISTING_DISCOVERED: Final = "LISTING_DISCOVERED"
DEAL_SCORED: Final = "DEAL_SCORED"


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
