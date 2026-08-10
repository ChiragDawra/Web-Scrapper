"""`CANONICAL_MODELS.md` §CanonicalProduct — Sprint 1 Task 1.7.

What every Marketplace Connector's `normalize()` returns and every downstream
service consumes. Maps onto `products` + `listings` (`DATABASE_SCHEMA.md` §3,
§4) but is deliberately not a row: the model is the contract, the column names
are an implementation of it.

Wire validation lives in `libs/event_bus/schema/canonical_models.json`
(`$defs/CanonicalProduct`), not here — one JSON Schema, applied at the publish
boundary. These dataclasses are the in-process representation on either side of
that boundary, so `from_dict` parses and does not re-litigate the schema. A
contract test asserts the two never drift apart.

Cross-field rules JSON Schema cannot express (`mrp >= price`, URL host matching
the marketplace domain) are the producing connector's job per
`VALIDATION_RULES.md` §1, and are not enforced here either.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from libs.enums import CurrencyCode, MarketplaceCode

__all__ = ["CanonicalProduct"]


@dataclass(frozen=True, slots=True)
class CanonicalProduct:
    """One marketplace listing, normalized. Immutable once produced by a connector."""

    canonical_title: str
    marketplace: MarketplaceCode
    external_listing_id: str
    url: str
    price: int
    in_stock: bool
    brand_name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    # Open map: connectors add marketplace-specific keys freely, but only
    # `size`/`color`/`variant` are read by the Deal Engine. Everything else is
    # carried through opaquely and never interpreted downstream.
    attributes: Mapping[str, Any] = field(default_factory=dict)
    image_url: str | None = None
    mrp: int | None = None
    currency: CurrencyCode = CurrencyCode.INR
    rating: float | None = None
    review_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_title": self.canonical_title,
            "brand_name": self.brand_name,
            "category": self.category,
            "subcategory": self.subcategory,
            "attributes": dict(self.attributes),
            "image_url": self.image_url,
            "marketplace": str(self.marketplace),
            "external_listing_id": self.external_listing_id,
            "url": self.url,
            "price": self.price,
            "mrp": self.mrp,
            "currency": str(self.currency),
            "rating": self.rating,
            "review_count": self.review_count,
            "in_stock": self.in_stock,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CanonicalProduct:
        """Parse a wire dict. `currency` defaults to INR when absent, per the contract."""
        raw_currency = data.get("currency")
        return cls(
            canonical_title=data["canonical_title"],
            marketplace=MarketplaceCode(data["marketplace"]),
            external_listing_id=data["external_listing_id"],
            url=data["url"],
            price=data["price"],
            in_stock=data["in_stock"],
            brand_name=data.get("brand_name"),
            category=data.get("category"),
            subcategory=data.get("subcategory"),
            attributes=data.get("attributes") or {},
            image_url=data.get("image_url"),
            mrp=data.get("mrp"),
            currency=CurrencyCode(raw_currency) if raw_currency else CurrencyCode.INR,
            rating=data.get("rating"),
            review_count=data.get("review_count"),
        )
