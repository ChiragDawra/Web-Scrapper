"""`score()` — Sprint 3 Task 3.3.

Definition of Done: "Below-threshold product returns `null`, no side effects;
above-threshold `score_breakdown` component weights sum to 1.0."
`test_below_threshold_product_returns_none` and
`test_component_weights_sum_to_one` are those two.

No database and no bus: `score()` is pure, and that is the property that makes
"silent skip, not an error" (`VALIDATION_RULES.md` §2) mean something — there
is nothing for a skipped listing to leave behind.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from src.repositories.price_history_repo import PriceStats
from src.services.scorer import (
    DEFAULT_CONFIG,
    SCORING_CONFIG_URL_VAR,
    ScoringConfig,
    load_scoring_config,
    score,
)

from libs.canonical_models import CanonicalProduct
from libs.enums import BrandTier, MarketplaceCode

LISTING_ID = uuid4()
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def product(**overrides: object) -> CanonicalProduct:
    """A comfortably-scoring listing: 50% off, well reviewed, in stock."""
    base = {
        "canonical_title": "Sony WH-1000XM5",
        "marketplace": MarketplaceCode.AMAZON,
        "external_listing_id": "B0BXBQ7C4X",
        "url": "https://www.amazon.in/dp/B0BXBQ7C4X",
        "price": 100000,
        "mrp": 200000,
        "in_stock": True,
        "rating": 4.6,
        "review_count": 1200,
        "brand_name": "Sony",
    }
    base.update(overrides)
    return CanonicalProduct(**base)  # type: ignore[arg-type]


def stats(lowest: int, highest: int, count: int = 20) -> PriceStats:
    return PriceStats(
        observation_count=count,
        lowest_price=lowest,
        highest_price=highest,
        first_seen=NOW,
        last_seen=NOW,
    )


# --- thresholds -------------------------------------------------------------


def test_below_threshold_product_returns_none() -> None:
    """5% off does not clear `min_discount_pct`; nothing is returned or emitted."""
    shallow = product(price=190000, mrp=200000)

    assert score(shallow, listing_id=LISTING_ID, brand_tier=BrandTier.PREMIUM, now=NOW) is None


def test_score_below_min_score_returns_none() -> None:
    """Clears the discount gate, fails the score gate: still a silent skip."""
    config = replace(DEFAULT_CONFIG, min_score=99.0)

    assert score(product(), listing_id=LISTING_ID, config=config, now=NOW) is None


def test_a_listing_with_no_reference_price_is_skipped() -> None:
    """No MRP and no history above the price — nothing honest to discount against."""
    unreferenced = product(mrp=None)

    assert score(unreferenced, listing_id=LISTING_ID, now=NOW) is None


def test_mrp_at_or_below_price_is_not_a_reference() -> None:
    assert score(product(mrp=100000), listing_id=LISTING_ID, now=NOW) is None


def test_history_supplies_the_reference_when_mrp_is_absent() -> None:
    deal = score(
        product(mrp=None),
        listing_id=LISTING_ID,
        price_stats=stats(lowest=95000, highest=200000),
        now=NOW,
    )

    assert deal is not None
    assert deal.reference_price == 200000


# --- the deal it produces ---------------------------------------------------


def test_component_weights_sum_to_one() -> None:
    assert DEFAULT_CONFIG.weights.total() == pytest.approx(1.0)


def test_components_sum_to_the_score() -> None:
    """Each component is `weight * factor * 100`, so the four are the score."""
    deal = score(
        product(),
        listing_id=LISTING_ID,
        brand_tier=BrandTier.PREMIUM,
        price_stats=stats(lowest=100000, highest=200000),
        now=NOW,
    )

    assert deal is not None
    breakdown = deal.score_breakdown
    total = (
        breakdown.discount_score
        + breakdown.velocity_score
        + breakdown.brand_score
        + breakdown.rating_score
    )
    assert deal.score == pytest.approx(total, abs=0.01)


def test_a_perfect_listing_scores_one_hundred() -> None:
    """Every component maxed is exactly 100 — no component exceeds its weighted range."""
    perfect = product(price=50000, mrp=200000, rating=5.0, review_count=5000)

    deal = score(
        perfect,
        listing_id=LISTING_ID,
        brand_tier=BrandTier.PREMIUM,
        price_stats=stats(lowest=50000, highest=200000),
        now=NOW,
    )

    assert deal is not None
    assert deal.score == pytest.approx(100.0)


def test_deal_carries_its_marketplace_and_prices() -> None:
    deal = score(product(), listing_id=LISTING_ID, brand_tier=BrandTier.STANDARD, now=NOW)

    assert deal is not None
    assert deal.listing_id == LISTING_ID
    assert deal.marketplace is MarketplaceCode.AMAZON
    assert deal.detected_price == 100000
    assert deal.reference_price == 200000
    assert deal.discount_pct == pytest.approx(50.0)


def test_expiry_comes_from_the_config() -> None:
    config = replace(DEFAULT_CONFIG, expiry_hours=12)

    deal = score(product(), listing_id=LISTING_ID, config=config, now=NOW)

    assert deal is not None
    assert (deal.expires_at - NOW).total_seconds() == 12 * 3600


def test_breakdown_records_the_weights_version() -> None:
    """Without it, a stored breakdown cannot be interpreted later."""
    config = replace(DEFAULT_CONFIG, weights_version="staff-2026-01")

    deal = score(product(), listing_id=LISTING_ID, config=config, now=NOW)

    assert deal is not None
    assert deal.score_breakdown.weights_version == "staff-2026-01"


# --- component curves -------------------------------------------------------


def test_deeper_discount_never_scores_lower() -> None:
    prices = (180000, 150000, 120000, 90000, 60000)
    scores = []
    for price in prices:
        deal = score(product(price=price), listing_id=LISTING_ID, now=NOW)
        scores.append(deal.score_breakdown.discount_score if deal else 0.0)

    assert scores == sorted(scores)


def test_discount_credit_is_capped() -> None:
    """A 95% cut off an inflated MRP earns no more than a 60% one."""
    capped = score(product(price=10000), listing_id=LISTING_ID, now=NOW)
    at_cap = score(product(price=80000), listing_id=LISTING_ID, now=NOW)

    assert capped is not None
    assert at_cap is not None
    assert capped.score_breakdown.discount_score == at_cap.score_breakdown.discount_score


@pytest.mark.parametrize(
    ("tier", "expected"),
    [(BrandTier.PREMIUM, 18.75), (BrandTier.STANDARD, 11.25), (BrandTier.UNBRANDED, 3.75)],
)
def test_brand_component_by_tier(tier: BrandTier, expected: float) -> None:
    deal = score(product(), listing_id=LISTING_ID, brand_tier=tier, now=NOW)

    assert deal is not None
    assert deal.score_breakdown.brand_score == pytest.approx(expected)


def test_unresolved_brand_scores_as_unbranded() -> None:
    unresolved = score(product(), listing_id=LISTING_ID, brand_tier=None, now=NOW)
    unbranded = score(product(), listing_id=LISTING_ID, brand_tier=BrandTier.UNBRANDED, now=NOW)

    assert unresolved is not None
    assert unbranded is not None
    assert unresolved.score_breakdown.brand_score == unbranded.score_breakdown.brand_score


def test_absent_rating_earns_nothing() -> None:
    """Silence is not a middling review — the connector refused to invent it too."""
    deal = score(
        product(rating=None, review_count=None),
        listing_id=LISTING_ID,
        brand_tier=BrandTier.PREMIUM,
        now=NOW,
    )

    assert deal is not None
    assert deal.score_breakdown.rating_score == 0.0


def test_a_high_rating_from_few_reviewers_is_discounted() -> None:
    thin = score(
        product(rating=5.0, review_count=5),
        listing_id=LISTING_ID,
        brand_tier=BrandTier.PREMIUM,
        now=NOW,
    )
    thick = score(
        product(rating=5.0, review_count=5000),
        listing_id=LISTING_ID,
        brand_tier=BrandTier.PREMIUM,
        now=NOW,
    )

    assert thin is not None
    assert thick is not None
    assert thin.score_breakdown.rating_score < thick.score_breakdown.rating_score


def test_a_rating_at_or_below_three_earns_nothing() -> None:
    deal = score(
        product(rating=3.0, review_count=5000),
        listing_id=LISTING_ID,
        brand_tier=BrandTier.PREMIUM,
        now=NOW,
    )

    assert deal is not None
    assert deal.score_breakdown.rating_score == 0.0


def test_no_history_earns_no_velocity_credit() -> None:
    deal = score(product(), listing_id=LISTING_ID, price_stats=None, now=NOW)

    assert deal is not None
    assert deal.score_breakdown.velocity_score == 0.0


def test_an_all_time_low_earns_full_velocity_credit() -> None:
    deal = score(
        product(),
        listing_id=LISTING_ID,
        price_stats=stats(lowest=120000, highest=200000),
        now=NOW,
    )

    assert deal is not None
    assert deal.score_breakdown.velocity_score == pytest.approx(25.0)


def test_a_price_well_above_the_low_earns_no_velocity_credit() -> None:
    deal = score(
        product(),
        listing_id=LISTING_ID,
        price_stats=stats(lowest=50000, highest=200000),
        now=NOW,
    )

    assert deal is not None
    assert deal.score_breakdown.velocity_score == 0.0


# --- config -----------------------------------------------------------------


def test_config_defaults_when_no_url_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SCORING_CONFIG_URL_VAR, raising=False)

    assert load_scoring_config() is DEFAULT_CONFIG


def test_config_falls_back_when_the_gateway_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scoring against known weights beats halting ingestion; the version says which."""
    monkeypatch.setenv(SCORING_CONFIG_URL_VAR, "http://127.0.0.1:1/scoring-config")

    assert load_scoring_config() is DEFAULT_CONFIG


def test_config_parses_the_gateway_payload() -> None:
    payload = {
        "weights_version": "staff-2026-02",
        "weights": {"discount": 0.4, "velocity": 0.2, "brand": 0.2, "rating": 0.2},
        "min_discount_pct": 10,
        "min_score": 30,
        "expiry_hours": 8,
        "history_window_days": 60,
    }

    config = ScoringConfig.from_dict(payload)

    assert config.weights_version == "staff-2026-02"
    assert config.weights.total() == pytest.approx(1.0)
    assert config.expiry_hours == 8
