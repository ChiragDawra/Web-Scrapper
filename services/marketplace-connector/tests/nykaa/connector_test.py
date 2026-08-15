"""`NykaaConnector` — Sprint 4 Tasks 4.3.1 and 4.3.3.

Definition of Done is Sprint 2's, per marketplace: "5+ recorded fixtures
normalize correctly, including missing `mrp` (nullable) and no-stock-signal
(must infer `false`, never null)." The five valid recordings live in
`tests/fixtures/nykaa/`; the ones that must be dropped live in
`tests/fixtures/nykaa_invalid/`, kept apart so `fetch_raw()` over the valid
directory stays a clean batch.

The tests that carry their weight here are the two Nykaa-shaped ones: money
quoted as a display string, and stock expressed as an on-hand quantity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.base.connector_interface import ParseFailedError
from src.connectors.nykaa.connector import DEFAULT_FIXTURE_DIR, NykaaConnector

from libs.canonical_models import CanonicalProduct
from libs.enums import CurrencyCode, MarketplaceCode

INVALID_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "nykaa_invalid"


@pytest.fixture(scope="module")
def products() -> dict[str, CanonicalProduct]:
    """Every valid recording, normalized once, keyed by SKU."""
    connector = NykaaConnector()
    return {
        product.external_listing_id: product
        for product in (connector.normalize(raw) for raw in connector.fetch_raw())
    }


def test_every_recorded_fixture_normalizes(products: dict[str, CanonicalProduct]) -> None:
    """The 5+ of the Definition of Done, and nothing silently dropped along the way."""
    assert len(products) >= 5
    assert set(products) == {
        "NYK-SKU-1001",
        "NYK-SKU-1002",
        "NYK-SKU-1003",
        "NYK-SKU-1004",
        "8805",
    }
    assert all(product.marketplace is MarketplaceCode.NYKAA for product in products.values())


def test_the_default_fixture_directory_is_the_recorded_one() -> None:
    assert DEFAULT_FIXTURE_DIR.is_dir()
    assert sorted(path.name for path in DEFAULT_FIXTURE_DIR.glob("*.json")) == [
        "catalog_products_response.json",
        "search_products_response.json",
    ]


def test_both_response_envelopes_are_unwrapped(products: dict[str, CanonicalProduct]) -> None:
    """The catalog shape wraps its array in `response`, search does not."""
    assert "NYK-SKU-1001" in products  # response.products[]
    assert "NYK-SKU-1004" in products  # products[]


def test_the_sku_is_preferred_over_the_catalog_id(
    products: dict[str, CanonicalProduct],
) -> None:
    """`id` churns when a product is relisted; the SKU stays with the thing on the
    shelf, and `listings` dedups on this key. Item 1 carries both."""
    assert products["NYK-SKU-1001"].external_listing_id == "NYK-SKU-1001"


def test_a_numeric_id_becomes_a_string_id(products: dict[str, CanonicalProduct]) -> None:
    """The last listing has no SKU at all, only a numeric `product_id`."""
    assert products["8805"].external_listing_id == "8805"


def test_a_complete_item_maps_every_field(products: dict[str, CanonicalProduct]) -> None:
    product = products["NYK-SKU-1001"]

    assert product.canonical_title == "Lakme Absolute Skin Dew Satin Foundation"
    assert product.brand_name == "Lakme"
    assert product.category == "Makeup"
    assert product.subcategory == "Foundation"  # l3, not the l2 "Face"
    assert product.url == ("https://www.nykaa.com/lakme-absolute-skin-dew-satin-foundation/p/8801")
    assert product.image_url == "https://images-static.nykaa.com/media/catalog/product/8801.jpg"
    assert product.currency is CurrencyCode.INR
    assert product.in_stock is True
    assert product.attributes == {
        "size": "30 ml",
        "color": "Ivory Fair 01",
        "variant": "Satin Matte",
    }


def test_money_quoted_as_a_display_string_converts_to_paise(
    products: dict[str, CanonicalProduct],
) -> None:
    """ "₹1,299" is 129900 paise. Dropping a good listing over punctuation helps nobody."""
    product = products["NYK-SKU-1001"]

    assert product.price == 129_900
    assert product.mrp == 199_900


def test_the_final_price_wins_over_the_listed_price(
    products: dict[str, CanonicalProduct],
) -> None:
    """Item 1 quotes `final_price` 1299 and `price` 1499; a buyer pays the former."""
    assert products["NYK-SKU-1001"].price == 129_900


def test_a_numeric_price_still_converts_exactly(products: dict[str, CanonicalProduct]) -> None:
    """899.99 rupees is 89999 paise. Float arithmetic lands on 89998 here."""
    assert products["NYK-SKU-1002"].price == 89_999


def test_an_item_without_an_mrp_has_a_null_mrp(products: dict[str, CanonicalProduct]) -> None:
    """Definition of Done, first named case: `mrp` is nullable, not zero, not the price.

    `price` is deliberately not an MRP fallback on this shape — it is what a
    buyer pays when no offer applies, so reading it as MRP would report a
    discount off itself.
    """
    assert products["NYK-SKU-1002"].mrp is None
    assert products["8805"].mrp is None


def test_no_stock_signal_infers_false_never_null(
    products: dict[str, CanonicalProduct],
) -> None:
    """Definition of Done, second named case, and §1 rule 9.

    `is False` rather than `not ...`: a regression that leaves `in_stock` null
    would pass a falsiness check and put a null into `listings.in_stock`.
    """
    assert products["NYK-SKU-1003"].in_stock is False


def test_a_zero_quantity_beats_an_in_stock_status_string(
    products: dict[str, CanonicalProduct],
) -> None:
    """The catalog leaves the prose status stale; the count is the real signal, and
    a false `True` sends a purchase agent at an unbuyable listing."""
    assert products["NYK-SKU-1004"].in_stock is False


def test_a_positive_quantity_is_a_positive_signal(
    products: dict[str, CanonicalProduct],
) -> None:
    assert products["NYK-SKU-1001"].in_stock is True


def test_a_low_stock_status_is_a_positive_signal(
    products: dict[str, CanonicalProduct],
) -> None:
    """The last resort, for shapes carrying neither a flag nor a count."""
    assert products["8805"].in_stock is True


def test_reviews_are_carried_when_present_and_null_when_not(
    products: dict[str, CanonicalProduct],
) -> None:
    """`"1,204"` is a count quoted for display, not a reason to lose the count."""
    assert products["NYK-SKU-1001"].rating == pytest.approx(4.5)
    assert products["NYK-SKU-1001"].review_count == 1204
    assert products["NYK-SKU-1003"].review_count == 486  # the `review_count` spelling
    assert products["NYK-SKU-1002"].rating is None
    assert products["NYK-SKU-1002"].review_count is None


def test_a_rounded_display_review_count_is_rejected_not_guessed() -> None:
    """§1 rule 8 would rather have no count than a wrong one."""
    with pytest.raises(ParseFailedError, match="review_count"):
        NykaaConnector().normalize(
            {
                "sku": "NYK-SKU-1099",
                "name": "Kay Beauty Hydrating Foundation",
                "product_url": "https://www.nykaa.com/kay-beauty-foundation/p/9099",
                "final_price": "1,299",
                "rating_count": "1.2k",
                "quantity": 3,
            }
        )


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
        NykaaConnector().normalize(raw)

    assert raised.value.code == "CONN_PARSE_FAILED"
    assert expected_detail in str(raised.value)


def test_every_malformed_fixture_is_rejected() -> None:
    """Nothing in the invalid directory sneaks through as a product."""
    connector = NykaaConnector(fixture_dir=INVALID_FIXTURE_DIR)
    raws = list(connector.fetch_raw())

    assert len(raws) == 4
    for raw in raws:
        with pytest.raises(ParseFailedError):
            connector.normalize(raw)


def test_a_price_that_is_not_a_number_after_cleanup_is_dropped() -> None:
    with pytest.raises(ParseFailedError, match="price"):
        NykaaConnector().normalize(
            {
                "sku": "NYK-SKU-1098",
                "name": "Kay Beauty Hydrating Foundation",
                "product_url": "https://www.nykaa.com/kay-beauty-foundation/p/9098",
                "final_price": "Best price in cart",
                "quantity": 3,
            }
        )


def test_a_non_mapping_item_is_rejected_rather_than_crashing() -> None:
    with pytest.raises(ParseFailedError, match="expected a mapping"):
        NykaaConnector().normalize(["not", "an", "item"])
