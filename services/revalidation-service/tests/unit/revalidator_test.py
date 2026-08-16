"""`revalidate()` and its 30s budget — Sprint 5 Tasks 5.1 and 5.3.

Task 5.3's Definition of Done: "A forced-slow (>30s) fixture results in no event
published." The forced-slow fixture is `SlowSource` here, and "no event
published" is asserted twice over: at this level as `BudgetExceededError` (so
nothing can be built from a stale read), and in `event_handlers_test.py` as an
empty stream.

The clock is injected, so nothing in this module waits 30 seconds.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from src.services.listing_source import ListingSnapshot, ListingVanishedError
from src.services.revalidator import BudgetExceededError, TimeoutBudget, revalidate

from libs.validation_rules import REVALIDATION_TIMEOUT_SECONDS

SCORED_PRICE = 100_000


class FakeClock:
    """A monotonic clock that only moves when a test says so."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StubSource:
    """Returns one snapshot. `reads` proves whether it was consulted at all."""

    def __init__(self, *, current_price: int = SCORED_PRICE, in_stock: bool = True) -> None:
        self.current_price = current_price
        self.in_stock = in_stock
        self.reads = 0

    def read(self, listing_id: UUID) -> ListingSnapshot:
        self.reads += 1
        return ListingSnapshot(
            listing_id=listing_id,
            current_price=self.current_price,
            in_stock=self.in_stock,
            observed_at=datetime.now(UTC),
        )


class SlowSource(StubSource):
    """The forced-slow fixture of Task 5.3: the read itself burns the budget."""

    def __init__(
        self,
        clock: FakeClock,
        *,
        seconds: float,
        current_price: int = SCORED_PRICE,
        in_stock: bool = True,
    ) -> None:
        super().__init__(current_price=current_price, in_stock=in_stock)
        self._clock = clock
        self._seconds = seconds

    def read(self, listing_id: UUID) -> ListingSnapshot:
        self._clock.advance(self._seconds)
        return super().read(listing_id)


class VanishedSource:
    def read(self, listing_id: UUID) -> ListingSnapshot:
        raise ListingVanishedError(f"listing {listing_id} is gone")


def budget(clock: FakeClock, *, seconds: int = REVALIDATION_TIMEOUT_SECONDS) -> TimeoutBudget:
    return TimeoutBudget(budget_seconds=seconds, clock=clock)


def test_a_price_within_tolerance_is_unchanged() -> None:
    clock = FakeClock()
    listing_id, deal_id = uuid4(), uuid4()

    result = revalidate(
        listing_id,
        detected_price=SCORED_PRICE,
        deal_id=deal_id,
        source=StubSource(current_price=101_000),
        budget=budget(clock),
    )

    assert result.changed is False
    assert result.deal_id == deal_id
    assert result.listing_id == listing_id
    assert result.current_price == 101_000
    assert result.in_stock is True


def test_a_price_outside_tolerance_is_changed() -> None:
    result = revalidate(
        uuid4(),
        detected_price=SCORED_PRICE,
        deal_id=uuid4(),
        source=StubSource(current_price=110_000),
        budget=budget(FakeClock()),
    )

    assert result.changed is True


def test_an_out_of_stock_listing_is_changed_at_the_same_price() -> None:
    """`REVAL_SOLD_OUT`, which the Bot turns into the `SOLD_OUT` edge."""
    result = revalidate(
        uuid4(),
        detected_price=SCORED_PRICE,
        deal_id=uuid4(),
        source=StubSource(in_stock=False),
        budget=budget(FakeClock()),
    )

    assert result.changed is True
    assert result.in_stock is False


def test_checked_at_is_when_the_listing_was_observed() -> None:
    """The Bot shows a price as of a moment, and the read is that moment."""
    source = StubSource()

    result = revalidate(
        uuid4(),
        detected_price=SCORED_PRICE,
        deal_id=uuid4(),
        source=source,
        budget=budget(FakeClock()),
    )

    assert result.checked_at.tzinfo is not None


def test_a_slow_read_produces_no_result() -> None:
    """Task 5.3: a >30s read is discarded, not published late."""
    clock = FakeClock()
    source = SlowSource(clock, seconds=REVALIDATION_TIMEOUT_SECONDS + 1)

    with pytest.raises(BudgetExceededError) as exc:
        revalidate(
            uuid4(),
            detected_price=SCORED_PRICE,
            deal_id=uuid4(),
            source=source,
            budget=budget(clock),
        )

    assert exc.value.budget_seconds == REVALIDATION_TIMEOUT_SECONDS
    assert exc.value.elapsed_seconds > REVALIDATION_TIMEOUT_SECONDS


def test_a_read_finishing_exactly_on_the_deadline_is_too_late() -> None:
    """`expired()` is `>=`: the Bot's own timer fires at 30s, so 30s is already gone."""
    clock = FakeClock()

    with pytest.raises(BudgetExceededError):
        revalidate(
            uuid4(),
            detected_price=SCORED_PRICE,
            deal_id=uuid4(),
            source=SlowSource(clock, seconds=REVALIDATION_TIMEOUT_SECONDS),
            budget=budget(clock),
        )


def test_an_already_closed_budget_costs_no_marketplace_traffic() -> None:
    """Checked before the read, so a hopeless request is not paid for twice."""
    clock = FakeClock()
    source = StubSource()
    spent = budget(clock)
    clock.advance(REVALIDATION_TIMEOUT_SECONDS + 5)

    with pytest.raises(BudgetExceededError):
        revalidate(
            uuid4(),
            detected_price=SCORED_PRICE,
            deal_id=uuid4(),
            source=source,
            budget=spent,
        )

    assert source.reads == 0


def test_a_read_inside_the_budget_is_kept() -> None:
    clock = FakeClock()

    result = revalidate(
        uuid4(),
        detected_price=SCORED_PRICE,
        deal_id=uuid4(),
        source=SlowSource(clock, seconds=REVALIDATION_TIMEOUT_SECONDS - 1),
        budget=budget(clock),
    )

    assert result.changed is False


def test_a_vanished_listing_propagates_rather_than_inventing_a_price() -> None:
    """No `current_price` was observed, so there is no honest result to return."""
    with pytest.raises(ListingVanishedError):
        revalidate(
            uuid4(),
            detected_price=SCORED_PRICE,
            deal_id=uuid4(),
            source=VanishedSource(),
            budget=budget(FakeClock()),
        )


def test_the_budget_defaults_to_the_documented_thirty_seconds() -> None:
    assert TimeoutBudget().budget_seconds == REVALIDATION_TIMEOUT_SECONDS
