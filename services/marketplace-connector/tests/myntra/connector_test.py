"""`MyntraConnector` — Sprint 4 Tasks 4.2.1 and 4.2.3.

Definition of Done is Sprint 2's, per marketplace: "5+ recorded fixtures
normalize correctly, including missing `mrp` (nullable) and no-stock-signal
(must infer `false`, never null)." The five valid recordings live in
`tests/fixtures/myntra/`; the ones that must be dropped live in
`tests/fixtures/myntra_invalid/`, kept apart so `fetch_raw()` over the valid
directory stays a clean batch.

Three of these tests exist only because Myntra's shape differs from every other
connector's — a numeric id, a relative URL, and a `price` field that is not the
price. Those are exactly the three ways this connector can be quietly wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.base.connector_interface import ParseFailedError
from src.connectors.myntra.connector import DEFAULT_FIXTURE_DIR, MyntraConnector

from libs.canonical_models import CanonicalProduct
from libs.enums import CurrencyCode, MarketplaceCode

INVALID_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "myntra_invalid"


@pytest.fixture(scope="module")
def products() -> dict[str, CanonicalProduct]:
    """Every valid recording, normalized once, keyed by `productId`."""
    connector = MyntraConnector()
    return {
        product.external_listing_id: product
        for product in (connector.normalize(raw) for raw in connector.fetch_raw())
    }


def test_every_recorded_fixture_normalizes(products: dict[str, CanonicalProduct]) -> None:
    """The 5+ of the Definition of Done, and nothing silently dropped along the way."""
    assert len(products) >= 5
    assert set(products) == {
        "1466678",
        "2299001",
        "3388002",
        "4477003",
        "5566004",
    }
    assert all(product.marketplace is MarketplaceCode.MYNTRA for product in products.values())


def test_the_default_fixture_directory_is_the_recorded_one() -> None:
    assert DEFAULT_FIXTURE_DIR.is_dir()
    assert sorted(path.name for path in DEFAULT_FIXTURE_DIR.glob("*.json")) == [
        "list_products_response.json",
        "search_products_response.json",
    ]


def test_both_response_envelopes_are_unwrapped(products: dict[str, CanonicalProduct]) -> None:
    """Search wraps its array in `data`, the list endpoint does not."""
    assert "1466678" in products  # data.products[]
    assert "4477003" in products  # products[]


def test_a_numeric_product_id_becomes_a_string_id(products: dict[str, CanonicalProduct]) -> None:
    """`external_listing_id` is a string, and `str(1466678)` is the same listing key
    on every poll — so the number is converted, not dropped."""
    assert products["1466678"].external_listing_id == "1466678"
    assert products["5566004"].external_listing_id == "5566004"


def test_a_relative_landing_page_becomes_an_absolute_url(
    products: dict[str, CanonicalProduct],
) -> None:
    """§1 rule 6 wants an absolute URL on a known host; a purchase agent handed
    `"puma-tshirt/1466678/buy"` has nowhere to go. Leading slash or not."""
    assert products["1466678"].url == (
        "https://www.myntra.com/puma-men-black-solid-round-neck-t-shirt/1466678/buy"
    )
    assert products["5566004"].url == (
        "https://www.myntra.com/maybelline-superstay-matte-ink/5566004/buy"
    )


def test_a_complete_item_maps_every_field(products: dict[str, CanonicalProduct]) -> None:
    product = products["1466678"]

    assert product.canonical_title == "Puma Men Black Solid Round Neck T-shirt"
    assert product.brand_name == "Puma"
    assert product.category == "Topwear"
    assert product.subcategory == "Tshirts"
    assert product.image_url == "https://assets.myntassets.com/h_720/1466678/image.jpg"
    assert product.currency is CurrencyCode.INR
    assert product.in_stock is True
    assert product.attributes == {"size": "S,M,L,XL", "color": "Black"}


def test_the_discounted_price_is_the_price_and_price_is_the_mrp(
    products: dict[str, CanonicalProduct],
) -> None:
    """The most expensive field on this shape to read backwards: `price` is the
    pre-discount number, `discountedPrice` is what a buyer pays."""
    product = products["1466678"]

    assert product.price == 64_900
    assert product.mrp == 149_900  # `mrp` when it is quoted, not `price`


def test_price_falls_back_to_the_pre_discount_price_when_undiscounted(
    products: dict[str, CanonicalProduct],
) -> None:
    """No `discountedPrice` means no discount: price and mrp are the same number,
    which §1 rule 3 allows and which reads downstream as zero discount."""
    product = products["3388002"]

    assert product.price == 349_500
    assert product.mrp == 349_500


def test_mrp_falls_back_to_the_pre_discount_price(products: dict[str, CanonicalProduct]) -> None:
    """No `mrp` key, but `price` is the struck-through number on this shape."""
    assert products["2299001"].mrp == 399_900
    assert products["2299001"].price == 219_950  # 2199.5 rupees, exactly


def test_an_item_with_neither_mrp_nor_price_has_a_null_mrp(
    products: dict[str, CanonicalProduct],
) -> None:
    """Definition of Done, first named case: `mrp` is nullable, not zero, not the price."""
    product = products["4477003"]

    assert product.mrp is None
    assert product.price == 89_999  # 899.99 rupees; float arithmetic lands on 89998


def test_no_available_size_infers_false_never_null(
    products: dict[str, CanonicalProduct],
) -> None:
    """Definition of Done, second named case, and §1 rule 9.

    This listing's sizes are one `available: true` with zero inventory and one
    `available: false`. Neither is a positive signal, and `is False` rather than
    `not ...` catches a regression that puts a null into `listings.in_stock`.
    """
    assert products["3388002"].in_stock is False


def test_any_available_size_makes_the_listing_in_stock(
    products: dict[str, CanonicalProduct],
) -> None:
    """Stock is per size; a deal card promises the listing is buyable, not that
    every size is. Sizes S is sold out here and M has seven left."""
    assert products["1466678"].in_stock is True


def test_an_available_flag_with_no_count_is_trusted(
    products: dict[str, CanonicalProduct],
) -> None:
    """When Myntra records no inventory count, the flag is the only signal there is."""
    assert products["4477003"].in_stock is True


def test_the_whole_listing_flag_is_used_when_there_is_no_inventory_list(
    products: dict[str, CanonicalProduct],
) -> None:
    assert products["5566004"].in_stock is True


def test_reviews_are_carried_when_present_and_null_when_not(
    products: dict[str, CanonicalProduct],
) -> None:
    assert products["1466678"].rating == pytest.approx(4.2)
    assert products["1466678"].review_count == 3184
    assert products["2299001"].rating is None
    assert products["2299001"].review_count is None


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
        MyntraConnector().normalize(raw)

    assert raised.value.code == "CONN_PARSE_FAILED"
    assert expected_detail in str(raised.value)


def test_every_malformed_fixture_is_rejected() -> None:
    """Nothing in the invalid directory sneaks through as a product."""
    connector = MyntraConnector(fixture_dir=INVALID_FIXTURE_DIR)
    raws = list(connector.fetch_raw())

    assert len(raws) == 4
    for raw in raws:
        with pytest.raises(ParseFailedError):
            connector.normalize(raw)


def test_a_non_integer_product_id_is_rejected() -> None:
    """`1466678.0` and `1466678` would key the same listing two ways in `listings`."""
    with pytest.raises(ParseFailedError, match="external_listing_id"):
        MyntraConnector().normalize(
            {
                "productId": 1466678.0,
                "product": "Puma Men Black Solid Round Neck T-shirt",
                "landingPageUrl": "puma/1466678/buy",
                "discountedPrice": 649,
            }
        )


def test_a_non_mapping_item_is_rejected_rather_than_crashing() -> None:
    with pytest.raises(ParseFailedError, match="expected a mapping"):
        MyntraConnector().normalize(["not", "an", "item"])
