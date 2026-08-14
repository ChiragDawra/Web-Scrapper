"""`write_deal()` order of operations — Sprint 3 Task 3.4.

The guard's real claim is about two connections contending, which needs a
database and lives in `tests/integration/deal_writer_test.py`. What is checkable
without one is the sequence: the lock must be taken *before* the existence
check, because a check that runs first is the race it is meant to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

from src.repositories.deal_repo import Deal, DealRepository
from src.services.deal_writer import write_deal

from libs.canonical_models.scored_deal import ScoreBreakdown, ScoredDeal
from libs.enums import DealStatus, MarketplaceCode

BREAKDOWN = ScoreBreakdown(
    discount_score=31.25,
    brand_score=18.75,
    rating_score=14.06,
    velocity_score=25.0,
    weights_version="builtin-v1",
)


class FakeDealRepository:
    """Records the call sequence and hands back whatever the test seeded."""

    def __init__(self, open_deal: Deal | None = None) -> None:
        self.calls: list[str] = []
        self.open_deal = open_deal
        self.inserted: dict[str, object] | None = None

    def lock_listing(self, listing_id: UUID) -> None:
        self.calls.append("lock")

    def find_open_for_listing(self, listing_id: UUID) -> Deal | None:
        self.calls.append("find")
        return self.open_deal

    def insert(self, **kwargs: object) -> Deal:
        self.calls.append("insert")
        self.inserted = kwargs
        return _deal(cast(UUID, kwargs["listing_id"]))

    def as_repo(self) -> DealRepository:
        return cast(DealRepository, self)


def _deal(listing_id: UUID, status: DealStatus = DealStatus.SCORED) -> Deal:
    moment = datetime.now(UTC)
    return Deal(
        id=uuid4(),
        listing_id=listing_id,
        status=status,
        score=Decimal("89.06"),
        score_breakdown=BREAKDOWN,
        detected_price=100000,
        reference_price=200000,
        discount_pct=Decimal("50.00"),
        notified_at=None,
        expires_at=moment + timedelta(hours=6),
        created_at=moment,
        updated_at=moment,
    )


def scored_deal(listing_id: UUID, *, score: float = 89.06) -> ScoredDeal:
    return ScoredDeal(
        listing_id=listing_id,
        marketplace=MarketplaceCode.AMAZON,
        score=score,
        score_breakdown=BREAKDOWN,
        detected_price=100000,
        reference_price=200000,
        discount_pct=50.0,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
    )


def test_lock_is_taken_before_the_existence_check() -> None:
    """A check that runs first is the race, not the guard against it."""
    repo = FakeDealRepository()

    write_deal(repo.as_repo(), scored_deal(uuid4()))

    assert repo.calls == ["lock", "find", "insert"]


def test_an_open_deal_short_circuits_the_insert() -> None:
    listing_id = uuid4()
    existing = _deal(listing_id, DealStatus.NOTIFIED)
    repo = FakeDealRepository(open_deal=existing)

    result = write_deal(repo.as_repo(), scored_deal(listing_id))

    assert result.created is False
    assert result.deal is existing
    assert repo.calls == ["lock", "find"]


def test_floats_are_converted_through_their_repr() -> None:
    """`Decimal(33.4)` is `33.39999...`; the column is `NUMERIC(5,2)`."""
    repo = FakeDealRepository()

    write_deal(repo.as_repo(), scored_deal(uuid4(), score=89.055))

    assert repo.inserted is not None
    assert repo.inserted["score"] == Decimal("89.06")
    assert repo.inserted["discount_pct"] == Decimal("50.0")
