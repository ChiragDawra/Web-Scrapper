"""`FlipkartConnector` — Sprint 4 Tasks 4.1.1 and 4.1.3.

Definition of Done is Sprint 2's, per marketplace: "5+ recorded fixtures
normalize correctly, including missing `mrp` (nullable) and no-stock-signal
(must infer `false`, never null)." The five valid recordings live in
`tests/fixtures/flipkart/`; the ones that must be dropped live in
`tests/fixtures/flipkart_invalid/`, kept apart so `fetch_raw()` over the valid
directory stays a clean batch.

Products are looked up by product id rather than by position: the fetch stub's
ordering is a filename-sort detail, and a test that breaks when a fixture is
renamed is testing the wrong thing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.base.connector_interface import ParseFailedError
from src.connectors.flipkart.connector import DEFAULT_FIXTURE_DIR, FlipkartConnector

from libs.canonical_models import CanonicalProduct
from libs.enums import CurrencyCode, MarketplaceCode

INVALID_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "flipkart_invalid"


@pytest.fixture(scope="module")
def products() -> dict[str, CanonicalProduct]:
    """Every valid recording, normalized once, keyed by `productId`."""
    connector = FlipkartConnector()
    return {
        product.external_listing_id: product
        for product in (connector.normalize(raw) for raw in connector.fetch_raw())
    }


def test_every_recorded_fixture_normalizes(products: dict[str, CanonicalProduct]) -> None:
    """The 5+ of the Definition of Done, and nothing silently dropped along the way."""
    assert len(products) >= 5
    assert set(products) == {
        "FLPCOMPLETE1",
        "FLPNOMRP002",
        "FLPNOSTOCK3",
        "FLPMESSAGE4",
        "FLPSOLDOUT5",
    }
    assert all(product.marketplace is MarketplaceCode.FLIPKART for product in products.values())


def test_the_default_fixture_directory_is_the_recorded_one() -> None:
    assert DEFAULT_FIXTURE_DIR.is_dir()
    assert sorted(path.name for path in DEFAULT_FIXTURE_DIR.glob("*.json")) == [
        "feed_products_response.json",
        "search_products_response.json",
    ]


def test_both_response_envelopes_are_unwrapped(products: dict[str, CanonicalProduct]) -> None:
    """Search returns `products`, the feed endpoint returns `productInfoList`. One
    connector reads both, or half the recordings are invisible."""
    assert "FLPCOMPLETE1" in products  # products[]
    assert "FLPMESSAGE4" in products  # productInfoList[]


def test_a_complete_item_maps_every_field(products: dict[str, CanonicalProduct]) -> None:
    product = products["FLPCOMPLETE1"]

    assert product.canonical_title == "Sony WH-1000XM5 Wireless Noise Cancelling Headphones"
    assert product.brand_name == "Sony"
    assert product.category == "Electronics"
    assert product.subcategory == "Over-Ear Headphones"
    assert product.url == "https://www.flipkart.com/p/FLPCOMPLETE1"
    assert product.currency is CurrencyCode.INR
    assert product.in_stock is True


def test_the_title_arrives_trimmed(products: dict[str, CanonicalProduct]) -> None:
    """§1 rule 1 says trimmed, and Task 2.2's `validate()` is what trims — so this
    also proves `normalize()` returns the validator's copy, not its own object."""
    assert products["FLPCOMPLETE1"].canonical_title.startswith("Sony")
    assert products["FLPCOMPLETE1"].canonical_title.endswith("Headphones")


def test_the_special_price_wins_over_the_selling_price(
    products: dict[str, CanonicalProduct],
) -> None:
    """24999 special, 27990 selling, 34990 MRP. Reading the selling price would
    score the deal against a number nobody is charged."""
    product = products["FLPCOMPLETE1"]

    assert product.price == 2_499_900
    assert product.mrp == 3_499_000


def test_the_selling_price_is_used_when_there_is_no_special_price(
    products: dict[str, CanonicalProduct],
) -> None:
    """899.99 rupees is 89999 paise. Float arithmetic lands on 89998 here."""
    assert products["FLPNOMRP002"].price == 89_999
    assert products["FLPMESSAGE4"].price == 104_950


def test_an_item_without_a_maximum_retail_price_has_a_null_mrp(
    products: dict[str, CanonicalProduct],
) -> None:
    """Definition of Done, first named case: `mrp` is nullable, not zero, not the price."""
    assert products["FLPNOMRP002"].mrp is None


def test_no_stock_signal_infers_false_never_null(
    products: dict[str, CanonicalProduct],
) -> None:
    """Definition of Done, second named case, and §1 rule 9.

    `is False` rather than `not ...`: a regression that leaves `in_stock` null
    would pass a falsiness check and put a null into `listings.in_stock`.
    """
    assert products["FLPNOSTOCK3"].in_stock is False


def test_the_in_stock_boolean_is_authoritative(products: dict[str, CanonicalProduct]) -> None:
    """`inStock: false` beats any prose next to it."""
    assert products["FLPSOLDOUT5"].in_stock is False


def test_a_low_stock_message_is_a_positive_signal(
    products: dict[str, CanonicalProduct],
) -> None:
    """ "Only 2 left in stock" means in stock, and carries no `inStock` flag."""
    assert products["FLPMESSAGE4"].in_stock is True


def test_a_single_segment_category_path_has_no_subcategory(
    products: dict[str, CanonicalProduct],
) -> None:
    """ "Electronics" is a category with no subcategory, not the reverse."""
    assert products["FLPNOMRP002"].category == "Electronics"
    assert products["FLPNOMRP002"].subcategory is None


def test_the_largest_recorded_image_is_preferred(products: dict[str, CanonicalProduct]) -> None:
    """The deal card renders this; an upscaled 200x200 looks like a broken listing."""
    assert products["FLPCOMPLETE1"].image_url == (
        "https://rukminim1.flixcart.com/image/800/800/FLPCOMPLETE1.jpeg"
    )
    assert products["FLPNOMRP002"].image_url == (
        "https://rukminim1.flixcart.com/image/200/200/FLPNOMRP002.jpeg"
    )


def test_reviews_are_carried_when_present_and_null_when_not(
    products: dict[str, CanonicalProduct],
) -> None:
    """The affiliate feed carries none; a fabricated rating would skew scoring."""
    assert products["FLPCOMPLETE1"].rating == pytest.approx(4.3)
    assert products["FLPCOMPLETE1"].review_count == 1520
    assert products["FLPNOMRP002"].rating is None
    assert products["FLPNOMRP002"].review_count is None


def test_attributes_hold_only_keys_that_are_present(
    products: dict[str, CanonicalProduct],
) -> None:
    """A `{"size": None}` entry reads as "null size"; an absent key reads as "unknown"."""
    assert products["FLPNOSTOCK3"].attributes == {"size": "34W x 32L", "color": "Indigo"}
    assert products["FLPCOMPLETE1"].attributes == {
        "color": "Midnight Black",
        "seller_name": "SuperComNet",
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
        FlipkartConnector().normalize(raw)

    assert raised.value.code == "CONN_PARSE_FAILED"
    assert expected_detail in str(raised.value)


def test_every_malformed_fixture_is_rejected() -> None:
    """Nothing in the invalid directory sneaks through as a product."""
    connector = FlipkartConnector(fixture_dir=INVALID_FIXTURE_DIR)
    raws = list(connector.fetch_raw())

    assert len(raws) == 4
    for raw in raws:
        with pytest.raises(ParseFailedError):
            connector.normalize(raw)


def test_an_item_with_no_price_at_all_is_dropped() -> None:
    """Not a fallback to MRP: that is the number nobody pays, and using it would
    invent a discount that does not exist."""
    with pytest.raises(ParseFailedError, match="price"):
        FlipkartConnector().normalize(
            {
                "productBaseInfoV1": {
                    "productId": "FLPNOPRICE9",
                    "title": "Priceless",
                    "productUrl": "https://www.flipkart.com/p/FLPNOPRICE9",
                    "maximumRetailPrice": {"amount": 999.0, "currency": "INR"},
                    "inStock": True,
                }
            }
        )


def test_a_non_mapping_item_is_rejected_rather_than_crashing() -> None:
    with pytest.raises(ParseFailedError, match="expected a mapping"):
        FlipkartConnector().normalize(["not", "an", "item"])
