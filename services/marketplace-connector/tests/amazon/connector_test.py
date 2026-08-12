"""`AmazonConnector` — Sprint 2 Task 2.3.

Definition of Done: "5+ recorded fixtures normalize correctly, including missing
`mrp` (nullable) and no-stock-signal (must infer `false`, never null)." The five
valid recordings live in `tests/fixtures/amazon/`; the ones that must be dropped
live in `tests/fixtures/amazon_invalid/`, kept apart so `fetch_raw()` over the
valid directory stays a clean batch.

Products are looked up by ASIN rather than by position: the fetch stub's ordering
is a filename-sort detail, and a test that breaks when a fixture is renamed is
testing the wrong thing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.base.connector_interface import ParseFailedError
from src.connectors.amazon.connector import DEFAULT_FIXTURE_DIR, AmazonConnector

from libs.canonical_models import CanonicalProduct
from libs.enums import CurrencyCode, MarketplaceCode

INVALID_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "amazon_invalid"


@pytest.fixture(scope="module")
def products() -> dict[str, CanonicalProduct]:
    """Every valid recording, normalized once, keyed by ASIN."""
    connector = AmazonConnector()
    return {
        product.external_listing_id: product
        for product in (connector.normalize(raw) for raw in connector.fetch_raw())
    }


def test_every_recorded_fixture_normalizes(products: dict[str, CanonicalProduct]) -> None:
    """The 5+ of the Definition of Done, and nothing silently dropped along the way."""
    assert len(products) >= 5
    assert set(products) == {
        "B0BXBQ7C4X",
        "B09NOMRP01",
        "B07NOSTOCK",
        "B0CRATED01",
        "B08OUTOFST",
    }
    assert all(product.marketplace is MarketplaceCode.AMAZON for product in products.values())


def test_the_default_fixture_directory_is_the_recorded_one() -> None:
    assert DEFAULT_FIXTURE_DIR.is_dir()
    assert sorted(path.name for path in DEFAULT_FIXTURE_DIR.glob("*.json")) == [
        "get_items_response.json",
        "search_items_response.json",
    ]


def test_a_complete_item_maps_every_field(products: dict[str, CanonicalProduct]) -> None:
    product = products["B0BXBQ7C4X"]

    assert product.canonical_title == "Sony WH-1000XM5 Wireless Noise Cancelling Headphones"
    assert product.brand_name == "Sony"
    assert product.category == "Electronics"
    assert product.subcategory == "Over-Ear Headphones"
    assert product.url == "https://www.amazon.in/dp/B0BXBQ7C4X"
    assert product.image_url == "https://m.media-amazon.com/images/I/B0BXBQ7C4X.jpg"
    assert product.currency is CurrencyCode.INR
    assert product.in_stock is True


def test_the_title_arrives_trimmed(products: dict[str, CanonicalProduct]) -> None:
    """§1 rule 1 says trimmed, and Task 2.2's `validate()` is what trims — so this
    also proves `normalize()` returns the validator's copy, not its own object."""
    assert products["B0BXBQ7C4X"].canonical_title.strip() == products["B0BXBQ7C4X"].canonical_title


def test_money_is_converted_from_rupees_to_paise(products: dict[str, CanonicalProduct]) -> None:
    """`DATABASE_SCHEMA.md`: all money is integer minor units."""
    product = products["B0BXBQ7C4X"]

    assert product.price == 2_499_900
    assert product.mrp == 3_499_000


def test_a_fractional_rupee_amount_converts_exactly(
    products: dict[str, CanonicalProduct],
) -> None:
    """899.99 rupees is 89999 paise. Float arithmetic lands on 89998 here."""
    assert products["B09NOMRP01"].price == 89_999
    assert products["B0CRATED01"].price == 104_950


def test_an_item_without_a_saving_basis_has_a_null_mrp(
    products: dict[str, CanonicalProduct],
) -> None:
    """Definition of Done, first named case: `mrp` is nullable, not zero, not the price."""
    assert products["B09NOMRP01"].mrp is None


def test_no_stock_signal_infers_false_never_null(
    products: dict[str, CanonicalProduct],
) -> None:
    """Definition of Done, second named case, and §1 rule 9.

    `is False` rather than `not ...`: a regression that leaves `in_stock` null
    would pass a falsiness check and put a null into `listings.in_stock`.
    """
    assert products["B07NOSTOCK"].in_stock is False


def test_an_explicit_out_of_stock_message_is_not_a_positive_signal(
    products: dict[str, CanonicalProduct],
) -> None:
    assert products["B08OUTOFST"].in_stock is False


def test_a_low_stock_message_is_a_positive_signal(
    products: dict[str, CanonicalProduct],
) -> None:
    """A low-stock message means in stock, and carries no `Availability.Type`."""
    assert products["B0CRATED01"].in_stock is True


def test_brand_falls_back_to_manufacturer(products: dict[str, CanonicalProduct]) -> None:
    """An imperfect name beats a null for the Deal Engine's `resolveBrand()`."""
    assert products["B09NOMRP01"].brand_name == "Imagine Marketing Ltd"


def test_reviews_are_carried_when_present_and_null_when_not(
    products: dict[str, CanonicalProduct],
) -> None:
    """PA-API itself returns neither; a fabricated rating would skew scoring."""
    assert products["B0CRATED01"].rating == pytest.approx(4.3)
    assert products["B0CRATED01"].review_count == 1520
    assert products["B0BXBQ7C4X"].rating is None
    assert products["B0BXBQ7C4X"].review_count is None


def test_attributes_hold_only_keys_that_are_present(
    products: dict[str, CanonicalProduct],
) -> None:
    """A `{"size": None}` entry reads as "null size"; an absent key reads as "unknown"."""
    assert products["B07NOSTOCK"].attributes == {"size": "34W x 32L", "color": "Indigo"}
    assert products["B0BXBQ7C4X"].attributes == {
        "color": "Midnight Black",
        "merchant_name": "Appario Retail Private Ltd",
    }


@pytest.mark.parametrize(
    ("fixture_name", "expected_detail"),
    [
        ("missing_title.json", "canonical_title"),
        ("price_zero.json", "price"),
        ("mrp_below_price.json", "mrp"),
        ("foreign_host.json", "url"),
    ],
)
def test_a_malformed_item_is_dropped_with_conn_parse_failed(
    fixture_name: str, expected_detail: str
) -> None:
    """§1: "A product failing any required-field rule is dropped (`CONN_PARSE_FAILED`),
    not partially emitted." One code whether the item died at construction or at
    `validate()`, so the Task 2.5 poll loop has one path to handle."""
    raw = json.loads((INVALID_FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))

    with pytest.raises(ParseFailedError) as raised:
        AmazonConnector().normalize(raw)

    assert raised.value.code == "CONN_PARSE_FAILED"
    assert expected_detail in str(raised.value)


def test_every_malformed_fixture_is_rejected() -> None:
    """Nothing in the invalid directory sneaks through as a product."""
    connector = AmazonConnector(fixture_dir=INVALID_FIXTURE_DIR)
    raws = list(connector.fetch_raw())

    assert len(raws) == 4
    for raw in raws:
        with pytest.raises(ParseFailedError):
            connector.normalize(raw)


def test_a_non_mapping_item_is_rejected_rather_than_crashing() -> None:
    with pytest.raises(ParseFailedError, match="expected a mapping"):
        AmazonConnector().normalize(["not", "an", "item"])
