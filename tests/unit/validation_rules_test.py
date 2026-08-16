"""The 2% guard — `VALIDATION_RULES.md` §5 — Sprint 5 Task 5.1.

Tested in `libs` rather than in the service because §5 names itself the single
source of truth for the tolerance: the number is shared, so the assertions about
it are too, and a service-local test would let a second copy appear without
failing anything here.

The boundary cases are the point. §5 writes the rule with `<=`, so a delta of
exactly 2% is *unchanged* and decides `CONFIRMED` over `PRICE_CHANGED` — an edge
that has to be reproducible, which is why the implementation is `Decimal` and
these numbers are chosen to land exactly on it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.validation_rules import (
    REVALIDATION_PRICE_TOLERANCE,
    REVALIDATION_TIMEOUT_SECONDS,
    price_within_tolerance,
    revalidation_changed,
)


def test_the_tolerance_is_two_percent() -> None:
    """The one assertion that pins the documented number itself.

    Compared against `Decimal("0.02")`, not `0.02`: the float literal is not two
    percent, and a test that accepted it would be endorsing the arithmetic this
    module exists to avoid.
    """
    assert Decimal("0.02") == REVALIDATION_PRICE_TOLERANCE


def test_the_timeout_is_thirty_seconds() -> None:
    """`STATE_TRANSITIONS.md` §1, shared by the Bot's deadline and the service's budget."""
    assert REVALIDATION_TIMEOUT_SECONDS == 30


def test_an_unmoved_price_is_unchanged() -> None:
    assert price_within_tolerance(100_000, 100_000) is True


@pytest.mark.parametrize("current", [102_000, 98_000])
def test_exactly_two_percent_either_way_is_unchanged(current: int) -> None:
    """§5's rule is `<= 0.02`, so the boundary belongs to "unchanged"."""
    assert price_within_tolerance(100_000, current) is True


@pytest.mark.parametrize("current", [102_001, 97_999])
def test_one_paisa_past_the_boundary_is_changed(current: int) -> None:
    """The float version of this comparison is what `Decimal` is here to prevent."""
    assert price_within_tolerance(100_000, current) is False


def test_a_price_drop_beyond_tolerance_still_counts_as_changed() -> None:
    """ "in either direction" (`STATE_TRANSITIONS.md` §1) — a cheaper listing is not a freebie."""
    assert price_within_tolerance(100_000, 80_000) is False


def test_a_non_positive_reference_price_is_rejected() -> None:
    """Impossible on a scored deal (`paise` is exclusiveMinimum 0), so it is corruption."""
    with pytest.raises(ValueError, match="detected_price must be positive"):
        price_within_tolerance(0, 100_000)


def test_out_of_stock_is_changed_whatever_the_price_did() -> None:
    """`REVAL_SOLD_OUT` — a purchase cannot proceed against an unbuyable listing."""
    assert (
        revalidation_changed(detected_price=100_000, current_price=100_000, in_stock=False) is True
    )


def test_an_in_stock_listing_within_tolerance_is_unchanged() -> None:
    assert (
        revalidation_changed(detected_price=100_000, current_price=101_000, in_stock=True) is False
    )


def test_a_known_stock_flip_is_changed_even_within_tolerance() -> None:
    """ "OR any change in `in_stock`" — used when a baseline is available."""
    assert (
        revalidation_changed(
            detected_price=100_000, current_price=100_000, in_stock=True, was_in_stock=False
        )
        is True
    )


def test_an_unknown_baseline_does_not_invent_a_flip() -> None:
    """`DEAL_SCORED` carries no stock flag, so `None` must not read as `False`."""
    assert (
        revalidation_changed(
            detected_price=100_000, current_price=100_000, in_stock=True, was_in_stock=None
        )
        is False
    )
