"""`score(product) -> ScoredDeal | null` — Sprint 3 Task 3.3.

`SERVICE_INTERFACES.md` §2 and `VALIDATION_RULES.md` §2: a listing that does
not clear the configured minimum threshold returns `None` and emits nothing —
a silent skip, not an error, and with no side effects.

Where the four components come from
-----------------------------------
`ZIP_05/DEAL_SCORING.md` lists seven weighted components (Discount 30,
Historical Lowest Price 20, Brand Popularity 15, Seller Trust 15, Ratings 10,
Review Count 5, Confidence 5). `CANONICAL_MODELS.md` freezes
`ScoreBreakdown` at four fields, and ZIP_13 is the frozen contract, so the
seven are folded into the four:

| Breakdown field | ZIP_05 components | Raw | Weight |
|---|---|---|---|
| `discount_score` | Discount | 30 | 0.375 |
| `velocity_score` | Historical Lowest Price | 20 | 0.250 |
| `brand_score` | Brand Popularity | 15 | 0.1875 |
| `rating_score` | Ratings + Review Count | 15 | 0.1875 |

Seller Trust (15) and Confidence (5) are dropped, not redistributed silently:
there is no seller entity anywhere in `DATABASE_SCHEMA.md` and no confidence
input on `CanonicalProduct`, so neither has a value to read. The remaining 80
raw points are renormalized to 1.0, which is what the Task 3.3 DoD checks.
Scoring the two missing components is a schema change, not a config change.

The shape of each component curve (`VALIDATION_RULES.md` leaves it open) is
chosen here and stated in each `_*_factor` docstring. All four return 0.0-1.0,
so no component can produce a value outside its own weighted range — the
failure mode §2 calls a scoring-config bug.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from libs.canonical_models import CanonicalProduct
from libs.canonical_models.scored_deal import ScoreBreakdown, ScoredDeal
from libs.enums import BrandTier, MarketplaceCode
from src.repositories.price_history_repo import PriceStats

__all__ = [
    "DEFAULT_CONFIG",
    "ScoringConfig",
    "ScoringWeights",
    "load_scoring_config",
    "score",
]

logger: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """The four weights, as fractions of one whole score."""

    discount: float
    velocity: float
    brand: float
    rating: float

    def total(self) -> float:
        return self.discount + self.velocity + self.brand + self.rating


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """What `GET /scoring-config` returns (`API_CONTRACTS.md` §5).

    `weights_version` is stored verbatim in every `score_breakdown` and is the
    only thing that makes a stored breakdown interpretable later — a `PUT`
    creates a new version and never rescores past deals
    (`STATE_TRANSITIONS.md` §1).
    """

    weights_version: str
    weights: ScoringWeights
    min_discount_pct: float
    min_score: float
    expiry_hours: int
    history_window_days: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoringConfig:
        weights = data["weights"]
        return cls(
            weights_version=data["weights_version"],
            weights=ScoringWeights(
                discount=float(weights["discount"]),
                velocity=float(weights["velocity"]),
                brand=float(weights["brand"]),
                rating=float(weights["rating"]),
            ),
            min_discount_pct=float(data["min_discount_pct"]),
            min_score=float(data["min_score"]),
            expiry_hours=int(data["expiry_hours"]),
            history_window_days=int(data["history_window_days"]),
        )


# Used until the API Gateway exists (Sprint 13 Task 13.7). Named as a version
# so a breakdown scored today stays distinguishable from one scored against a
# staff-edited config later.
DEFAULT_CONFIG: Final = ScoringConfig(
    weights_version="builtin-v1",
    weights=ScoringWeights(discount=0.375, velocity=0.250, brand=0.1875, rating=0.1875),
    min_discount_pct=15.0,
    min_score=40.0,
    expiry_hours=6,
    history_window_days=90,
)

SCORING_CONFIG_URL_VAR: Final = "SCORING_CONFIG_URL"
_FETCH_TIMEOUT_SECONDS: Final = 3

# Component curve constants. Each is the input value at which its component
# earns full credit.
FULL_CREDIT_DISCOUNT_PCT: Final = 60.0
FULL_CREDIT_REVIEW_COUNT: Final = 500
# A price this far above the historical low earns nothing for velocity.
VELOCITY_ZERO_CREDIT_MARGIN: Final = 0.20

_BRAND_FACTORS: Final[dict[BrandTier, float]] = {
    BrandTier.PREMIUM: 1.0,
    BrandTier.STANDARD: 0.6,
    BrandTier.UNBRANDED: 0.2,
}


def load_scoring_config(url: str | None = None) -> ScoringConfig:
    """Read the active weights from `GET /scoring-config`.

    Falls back to `DEFAULT_CONFIG` when no URL is configured or the gateway is
    unreachable: scoring the next listing against known weights beats halting
    ingestion, and the fallback is logged rather than silent. The version in
    every stored breakdown says which of the two was used.
    """
    endpoint = url or os.environ.get(SCORING_CONFIG_URL_VAR)
    if not endpoint:
        return DEFAULT_CONFIG

    try:
        with urllib.request.urlopen(endpoint, timeout=_FETCH_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return ScoringConfig.from_dict(payload)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
        logger.warning(
            "scoring config unreachable at %s (%s); falling back to %s",
            endpoint,
            exc,
            DEFAULT_CONFIG.weights_version,
        )
        return DEFAULT_CONFIG


def score(
    product: CanonicalProduct,
    *,
    listing_id: UUID,
    brand_tier: BrandTier | None = None,
    price_stats: PriceStats | None = None,
    config: ScoringConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
) -> ScoredDeal | None:
    """Score one listing, or return `None` if it does not clear the thresholds.

    `SERVICE_INTERFACES.md` writes this as `score(product)`; the keyword
    arguments are the context that a `CanonicalProduct` cannot carry —
    `listing_id` because a `ScoredDeal` names a persisted listing, `brand_tier`
    and `price_stats` because they are reads the caller has already done and
    should not be repeated per component.

    Pure: no writes, no events. Persisting the result is Task 3.4's job, which
    is what makes "silent skip, not an error" mean "no side effects".
    """
    reference_price = _reference_price(product, price_stats)
    if reference_price is None or reference_price <= product.price:
        # No MRP and no history above the current price: nothing to discount
        # against. Not an error — the listing is simply unscoreable today.
        return None

    discount_pct = (reference_price - product.price) / reference_price * 100
    if discount_pct < config.min_discount_pct:
        return None

    breakdown = _breakdown(product, brand_tier, price_stats, discount_pct, config)
    total = (
        breakdown.discount_score
        + breakdown.velocity_score
        + breakdown.brand_score
        + breakdown.rating_score
    )
    if total < config.min_score:
        return None

    moment = now or datetime.now(UTC)
    return ScoredDeal(
        listing_id=listing_id,
        marketplace=MarketplaceCode(product.marketplace),
        score=round(total, 2),
        score_breakdown=breakdown,
        detected_price=product.price,
        reference_price=reference_price,
        discount_pct=round(discount_pct, 2),
        expires_at=moment + timedelta(hours=config.expiry_hours),
    )


def _reference_price(product: CanonicalProduct, price_stats: PriceStats | None) -> int | None:
    """What the price is discounted against.

    MRP first: it is the marketplace's own claim and is what the notification
    shows. Without one, the highest price actually observed for this listing is
    the honest substitute — an invented reference would manufacture discounts.
    """
    if product.mrp is not None and product.mrp > product.price:
        return product.mrp
    if price_stats is not None and price_stats.highest_price > product.price:
        return price_stats.highest_price
    return None


def _breakdown(
    product: CanonicalProduct,
    brand_tier: BrandTier | None,
    price_stats: PriceStats | None,
    discount_pct: float,
    config: ScoringConfig,
) -> ScoreBreakdown:
    """Each component is `weight * factor * 100`, so the four sum to the score."""
    weights = config.weights
    return ScoreBreakdown(
        discount_score=round(weights.discount * _discount_factor(discount_pct) * 100, 2),
        velocity_score=round(
            weights.velocity * _velocity_factor(product.price, price_stats) * 100, 2
        ),
        brand_score=round(weights.brand * _brand_factor(brand_tier) * 100, 2),
        rating_score=round(
            weights.rating * _rating_factor(product.rating, product.review_count) * 100, 2
        ),
        weights_version=config.weights_version,
    )


def _discount_factor(discount_pct: float) -> float:
    """Linear from 0% to `FULL_CREDIT_DISCOUNT_PCT`, flat above it.

    Flat rather than unbounded: a 90% "discount" off an inflated MRP is not
    three times the deal a 30% one is, and letting it run would let a single
    fake MRP outscore every real bargain in the queue.
    """
    return _clamp(discount_pct / FULL_CREDIT_DISCOUNT_PCT)


def _velocity_factor(price: int, price_stats: PriceStats | None) -> float:
    """Full credit at or below the window's lowest price, zero well above it.

    No history means no credit, not average credit: a listing seen for the
    first time has not been proven cheap, and assuming it has is how a
    permanently-discounted item gets notified every single scan.
    """
    if price_stats is None or price_stats.lowest_price <= 0:
        return 0.0
    if price <= price_stats.lowest_price:
        return 1.0
    excess = (price - price_stats.lowest_price) / price_stats.lowest_price
    return _clamp(1.0 - excess / VELOCITY_ZERO_CREDIT_MARGIN)


def _brand_factor(brand_tier: BrandTier | None) -> float:
    """Tier lookup. An unresolved brand scores as `UNBRANDED`, not as zero risk."""
    if brand_tier is None:
        return _BRAND_FACTORS[BrandTier.UNBRANDED]
    return _BRAND_FACTORS[brand_tier]


def _rating_factor(rating: float | None, review_count: int | None) -> float:
    """Rating above 3.0, discounted by how few reviews back it.

    An absent rating earns nothing rather than a neutral half: connectors
    return `None` when the marketplace gave no rating, and treating silence as
    a middling review would invent the input the connector refused to invent.
    A 5.0 from two reviewers is likewise not a 5.0 from two thousand.
    """
    if rating is None:
        return 0.0
    quality = _clamp((rating - 3.0) / 2.0)
    confidence = _clamp((review_count or 0) / FULL_CREDIT_REVIEW_COUNT)
    return quality * confidence


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
