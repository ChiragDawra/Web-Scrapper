"""The recorded live read — Sprint 5 Task 5.1.

`FixtureListingSource` is a stub, but the rules it enforces are not: a recording
missing a price or a stock flag must fail loudly, because the alternative is a
`RevalidationResult` asserting facts nobody observed. Those refusals are what
this module tests; the replay itself is one assertion.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from src.services.listing_source import (
    DEFAULT_FIXTURE_DIR,
    FixtureListingSource,
    ListingUnreadableError,
    ListingVanishedError,
)

#: The two recordings committed under `tests/fixtures/listings`, one inside the
#: 2% tolerance of 799900 and one outside it.
UNCHANGED_LISTING = UUID("3f2504e0-4f89-41d3-9a0c-0305e82c3401")
CHANGED_LISTING = UUID("3f2504e0-4f89-41d3-9a0c-0305e82c3402")


def write(dir_path: Path, listing_id: UUID, payload: Any) -> None:
    (dir_path / f"{listing_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_the_committed_recordings_replay() -> None:
    """The default directory is the one the image ships, so it has to resolve."""
    source = FixtureListingSource()

    snapshot = source.read(UNCHANGED_LISTING)

    assert source.fixture_dir == DEFAULT_FIXTURE_DIR
    assert snapshot.listing_id == UNCHANGED_LISTING
    assert snapshot.current_price == 799_900
    assert snapshot.in_stock is True
    assert snapshot.observed_at == datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC)


def test_a_missing_recording_reads_as_a_vanished_listing() -> None:
    """The service cannot tell "delisted" from "never recorded", and must not assume it is fine."""
    source = FixtureListingSource()

    with pytest.raises(ListingVanishedError) as exc:
        source.read(uuid4())

    assert exc.value.code == "CONN_LISTING_NOT_FOUND"


def test_price_is_accepted_as_an_alias_for_current_price(tmp_path: Path) -> None:
    """A recording taken off a marketplace response is likelier to say `price`."""
    listing_id = uuid4()
    write(tmp_path, listing_id, {"price": 123_400, "in_stock": True})

    assert FixtureListingSource(tmp_path).read(listing_id).current_price == 123_400


def test_a_recording_without_a_price_is_unreadable(tmp_path: Path) -> None:
    listing_id = uuid4()
    write(tmp_path, listing_id, {"in_stock": True})

    with pytest.raises(ListingUnreadableError, match="positive paise price"):
        FixtureListingSource(tmp_path).read(listing_id)


@pytest.mark.parametrize("price", [0, -1, "799900", True])
def test_a_price_that_is_not_positive_paise_is_unreadable(tmp_path: Path, price: Any) -> None:
    """`True` is in here on purpose: `bool` is an `int` in Python, and 1 paisa is not a price."""
    listing_id = uuid4()
    write(tmp_path, listing_id, {"current_price": price, "in_stock": True})

    with pytest.raises(ListingUnreadableError):
        FixtureListingSource(tmp_path).read(listing_id)


def test_a_missing_stock_flag_is_not_inferred_as_false(tmp_path: Path) -> None:
    """`VALIDATION_RULES.md` §1 puts that inference in the connector, against a real response.

    Inferring it here would answer `SOLD_OUT` for a listing nobody checked.
    """
    listing_id = uuid4()
    write(tmp_path, listing_id, {"current_price": 799_900})

    with pytest.raises(ListingUnreadableError, match="boolean in_stock"):
        FixtureListingSource(tmp_path).read(listing_id)


def test_an_absent_observed_at_falls_back_to_now(tmp_path: Path) -> None:
    listing_id = uuid4()
    write(tmp_path, listing_id, {"current_price": 799_900, "in_stock": True})

    before = datetime.now(UTC)
    snapshot = FixtureListingSource(tmp_path).read(listing_id)

    assert snapshot.observed_at >= before


def test_a_recording_that_is_not_an_object_is_unreadable(tmp_path: Path) -> None:
    listing_id = uuid4()
    write(tmp_path, listing_id, [{"current_price": 799_900, "in_stock": True}])

    with pytest.raises(ListingUnreadableError, match="not an object"):
        FixtureListingSource(tmp_path).read(listing_id)
