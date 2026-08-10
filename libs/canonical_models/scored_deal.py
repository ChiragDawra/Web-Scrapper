"""`CANONICAL_MODELS.md` §ScoredDeal — Sprint 1 Task 1.7.

Produced by the Deal Engine's scoring step; maps onto `deals`
(`DATABASE_SCHEMA.md` §6).

There is no `deal_id` field. The `DEAL_SCORED` event payload carries one
(`EVENT_SCHEMAS.md` §2), but the model as documented does not — a `ScoredDeal`
is the scoring result, which exists before the row it becomes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from libs.enums import MarketplaceCode
from libs.event_bus.envelope import parse_timestamp, parse_uuid

__all__ = ["ScoreBreakdown", "ScoredDeal"]


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Per-factor contribution to a score.

    Stored verbatim and never recomputed (`STATE_TRANSITIONS.md` §1): it is the
    audit trail for why a deal was surfaced, and an ML training feature. Hence
    `weights_version` — a breakdown is only interpretable against the scoring
    config that produced it.
    """

    discount_score: float
    brand_score: float
    rating_score: float
    velocity_score: float
    weights_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "discount_score": self.discount_score,
            "brand_score": self.brand_score,
            "rating_score": self.rating_score,
            "velocity_score": self.velocity_score,
            "weights_version": self.weights_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScoreBreakdown:
        return cls(
            discount_score=data["discount_score"],
            brand_score=data["brand_score"],
            rating_score=data["rating_score"],
            velocity_score=data["velocity_score"],
            weights_version=data["weights_version"],
        )


@dataclass(frozen=True, slots=True)
class ScoredDeal:
    """One scored deal. Never rescored in place — a later qualifying price makes a new one."""

    listing_id: UUID
    # Joined from listings/marketplaces at scoring time (the Deal Engine owns
    # both tables) and then carried opaquely through the purchase event chain,
    # so no downstream consumer re-derives it via a cross-service read (ADR-009).
    marketplace: MarketplaceCode
    score: float
    score_breakdown: ScoreBreakdown
    detected_price: int
    reference_price: int
    discount_pct: float
    expires_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": str(self.listing_id),
            "marketplace": str(self.marketplace),
            "score": self.score,
            "score_breakdown": self.score_breakdown.to_dict(),
            "detected_price": self.detected_price,
            "reference_price": self.reference_price,
            "discount_pct": self.discount_pct,
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScoredDeal:
        return cls(
            listing_id=parse_uuid(data["listing_id"], "listing_id"),
            marketplace=MarketplaceCode(data["marketplace"]),
            score=data["score"],
            score_breakdown=ScoreBreakdown.from_dict(data["score_breakdown"]),
            detected_price=data["detected_price"],
            reference_price=data["reference_price"],
            discount_pct=data["discount_pct"],
            expires_at=parse_timestamp(data["expires_at"], "expires_at"),
        )
