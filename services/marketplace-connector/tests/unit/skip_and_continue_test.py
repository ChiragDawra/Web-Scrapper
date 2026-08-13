"""`CONN_PARSE_FAILED`: log, skip, keep going — Sprint 2 Task 2.5.

Definition of Done: "One malformed fixture is skipped; the next fixture in the
batch still processes." `tests/fixtures/amazon_mixed/` is that batch — valid,
malformed, valid, in that order, so a connector that aborts on the bad item is
caught by the *third* item being missing rather than by a count that a
reordering could accidentally satisfy.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from src.base.connector_interface import (
    ConnectorInterface,
    ParseFailedError,
    RateLimitedError,
    iter_products,
)
from src.connectors.amazon.connector import AmazonConnector

from libs.canonical_models import CanonicalProduct
from libs.enums import MarketplaceCode

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MIXED_FIXTURE_DIR = FIXTURES / "amazon_mixed"
INVALID_FIXTURE_DIR = FIXTURES / "amazon_invalid"

GOOD_BEFORE = "B0GOODONE1"
BAD = "B0MIDBAD01"
GOOD_AFTER = "B0GOODTWO2"


@pytest.fixture
def mixed_connector() -> AmazonConnector:
    return AmazonConnector(fixture_dir=MIXED_FIXTURE_DIR)


def test_the_item_after_a_malformed_one_still_processes(
    mixed_connector: AmazonConnector,
) -> None:
    """The Definition of Done, stated directly."""
    products = list(iter_products(mixed_connector))

    assert [product.external_listing_id for product in products] == [GOOD_BEFORE, GOOD_AFTER]


def test_the_malformed_item_is_not_emitted_even_partially(
    mixed_connector: AmazonConnector,
) -> None:
    """`SERVICE_INTERFACES.md` §1: no partial/malformed listing. Not a stub with a
    null title, not a placeholder — nothing."""
    products = list(iter_products(mixed_connector))

    assert BAD not in {product.external_listing_id for product in products}
    assert all(product.canonical_title for product in products)


def test_every_survivor_is_a_complete_product(mixed_connector: AmazonConnector) -> None:
    products = list(iter_products(mixed_connector))

    assert all(isinstance(product, CanonicalProduct) for product in products)
    assert all(product.marketplace is MarketplaceCode.AMAZON for product in products)
    assert all(product.price > 0 for product in products)


def test_the_skip_is_logged_with_the_error_code(
    mixed_connector: AmazonConnector, caplog: pytest.LogCaptureFixture
) -> None:
    """ "Logs and skips" — a silent skip is indistinguishable from a marketplace
    that returned fewer listings, which is how ingestion gaps go unnoticed."""
    with caplog.at_level(logging.WARNING, logger="src.base.connector_interface"):
        list(iter_products(mixed_connector))

    records = [record for record in caplog.records if "CONN_PARSE_FAILED" in record.getMessage()]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "AMAZON" in records[0].getMessage()


def test_the_skip_listener_sees_the_raw_item_and_the_error(
    mixed_connector: AmazonConnector,
) -> None:
    """The hook exists so a caller can count drops without re-parsing the log."""
    skipped: list[tuple[Any, ParseFailedError]] = []

    list(iter_products(mixed_connector, on_skip=lambda raw, exc: skipped.append((raw, exc))))

    assert len(skipped) == 1
    raw, exc = skipped[0]
    assert raw["ASIN"] == BAD
    assert exc.code == "CONN_PARSE_FAILED"
    assert exc.retryable is False


def test_an_all_malformed_batch_yields_nothing_and_does_not_raise() -> None:
    """Four bad items in a row is still a completed poll, not a crash."""
    skipped: list[Any] = []

    products = list(
        iter_products(
            AmazonConnector(fixture_dir=INVALID_FIXTURE_DIR),
            on_skip=lambda raw, _exc: skipped.append(raw),
        )
    )

    assert products == []
    assert len(skipped) == 4


def test_a_clean_batch_skips_nothing() -> None:
    """The skip path must not eat valid listings on its way past."""
    skipped: list[Any] = []

    products = list(iter_products(AmazonConnector(), on_skip=lambda raw, _exc: skipped.append(raw)))

    assert len(products) == 5
    assert skipped == []


class RateLimitedConnector(ConnectorInterface):
    """Fails the fetch itself, the way a 429 does."""

    marketplace: ClassVar[MarketplaceCode] = MarketplaceCode.AMAZON

    def fetch_raw(self) -> Iterator[dict[str, Any]]:
        raise RateLimitedError("429 from marketplace")
        yield  # pragma: no cover - unreachable, makes this a generator

    def normalize(self, raw_marketplace_response: Any) -> CanonicalProduct:
        raise AssertionError("normalize must not be reached")


def test_a_whole_batch_failure_is_not_swallowed_as_a_skip() -> None:
    """`CONN_RATE_LIMITED` applies to the fetch, not to one item. Swallowing it here
    would turn a throttled poll into an empty one that reads as "no listings"."""
    with pytest.raises(RateLimitedError):
        list(iter_products(RateLimitedConnector()))
