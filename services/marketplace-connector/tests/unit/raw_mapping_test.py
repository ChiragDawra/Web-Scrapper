"""Shared raw-item plumbing — Sprint 4.

Three connectors depend on these, so a change here is a change to three
marketplaces at once. The cases that matter are the ones where being lenient
and being wrong look alike: a truthy string that is not `true`, a rounded
display number, a float id.
"""

from __future__ import annotations

import json
import re
from pathlib import Path as FilePath

import pytest
from src.base.connector_interface import ParseFailedError
from src.base.fixture_source import iter_fixture_items, unwrap_items
from src.base.raw_mapping import (
    currency,
    first_paise,
    first_text,
    flag,
    identifier,
    only_present,
    optional_int,
    optional_number,
    optional_paise,
    paise,
    require,
    required_paise,
    required_text,
    select,
    text,
)

from libs.enums import CurrencyCode

ITEM = {
    "name": "  Lakme Absolute Foundation  ",
    "blank": "   ",
    "count": 12,
    "offers": [{"price": 1299.0}, {"price": 1499.0}],
    "nested": {"deep": {"value": "found"}},
    "nulled": None,
}


def test_select_walks_keys_and_indices() -> None:
    assert select(ITEM, ("nested", "deep", "value")) == "found"
    assert select(ITEM, ("offers", 0, "price")) == 1299.0
    assert select(ITEM, ("offers", -1, "price")) == 1499.0


@pytest.mark.parametrize(
    "path",
    [
        ("missing",),
        ("nested", "missing"),
        ("nulled", "anything"),
        ("offers", 9, "price"),
        ("name", "price"),
        ("count", 0),
    ],
)
def test_select_is_total(path: tuple[str | int, ...]) -> None:
    """A `KeyError` escaping mid-parse would abort an item that `validate()` is
    entitled to judge for itself. Every dead end resolves to `None`."""
    assert select(ITEM, path) is None


def test_text_trims_and_collapses_blank_to_none() -> None:
    """An empty `brand_name` and a missing one mean the same thing downstream, and
    `resolveBrand("")` would otherwise create a nameless `brands` row."""
    assert text(ITEM, ("name",)) == "Lakme Absolute Foundation"
    assert text(ITEM, ("blank",)) is None
    assert text(ITEM, ("count",)) is None  # a number is not a name


def test_first_text_takes_the_first_usable_string() -> None:
    assert first_text(ITEM, [("blank",), ("missing",), ("name",)]) == "Lakme Absolute Foundation"
    assert first_text(ITEM, [("blank",), ("missing",)]) is None


def test_require_and_required_text_name_the_field_and_the_path() -> None:
    with pytest.raises(ParseFailedError, match=re.escape("url: missing at nested.missing")):
        require(ITEM, ("nested", "missing"), "url")

    with pytest.raises(ParseFailedError, match="expected a string"):
        required_text(ITEM, ("count",), "external_listing_id")


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (1499, 149_900),
        (1499.0, 149_900),
        (899.99, 89_999),
        (1049.5, 104_950),
        ("1,299", 129_900),
        ("₹1,299", 129_900),
        (" 899.00 ", 89_900),
        ("0.005", 1),  # sub-paise precision rounds half-up rather than dropping the listing
    ],
)
def test_paise_converts_rupees_exactly(amount: object, expected: int) -> None:
    """Via `Decimal(str(...))`, never float: `899.99 * 100` is 89998 after `int()`."""
    assert paise(amount, "price") == expected


@pytest.mark.parametrize("amount", [True, None, "Best price in cart", float("inf"), ["1299"]])
def test_paise_rejects_what_is_not_a_number(amount: object) -> None:
    with pytest.raises(ParseFailedError, match="price"):
        paise(amount, "price")


def test_optional_and_first_paise_leave_absent_absent() -> None:
    assert optional_paise(ITEM, ("missing",), "mrp") is None
    assert first_paise(ITEM, [("missing",), ("offers", 0, "price")], "price") == 129_900
    assert first_paise(ITEM, [("missing",)], "mrp") is None


def test_required_paise_names_every_path_it_tried() -> None:
    with pytest.raises(ParseFailedError, match=re.escape("price: missing at a or b.c")):
        required_paise(ITEM, [("a",), ("b", "c")], "price")


def test_optional_number_and_int_reject_the_wrong_type() -> None:
    """§1 permits a null `rating`; it does not permit a made-up one."""
    assert optional_number(ITEM, ("missing",), "rating") is None
    assert optional_number(ITEM, ("count",), "rating") == 12.0
    assert optional_int(ITEM, ("count",), "review_count") == 12

    with pytest.raises(ParseFailedError, match="rating"):
        optional_number(ITEM, ("name",), "rating")
    with pytest.raises(ParseFailedError, match="review_count"):
        optional_int(ITEM, ("offers", 0, "price"), "review_count")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (False, False), ("true", None), ("false", None), (1, None), (None, None)],
)
def test_flag_is_a_boolean_or_nothing(value: object, expected: bool | None) -> None:
    """`bool("false")` is `True`, which would send a purchase agent at an
    unbuyable listing. A non-boolean is no signal, not a false one."""
    assert flag({"in_stock": value}, ("in_stock",)) is expected


def test_identifier_accepts_strings_and_integers_and_nothing_else() -> None:
    assert identifier({"sku": " NYK-1 "}, [("sku",)], "external_listing_id") == "NYK-1"
    assert identifier({"productId": 1466678}, [("productId",)], "external_listing_id") == "1466678"
    assert identifier({"sku": "  ", "id": 42}, [("sku",), ("id",)], "id") == "42"

    with pytest.raises(ParseFailedError, match="neither a string nor an integer"):
        identifier({"productId": 1466678.0}, [("productId",)], "external_listing_id")
    with pytest.raises(ParseFailedError, match="missing at sku or id"):
        identifier({}, [("sku",), ("id",)], "external_listing_id")


def test_currency_defaults_to_inr_and_rejects_an_unmapped_code() -> None:
    """Quietly relabelling a USD price as rupees would put a wrong number into
    `deals.detected_price` with no trace."""
    assert currency({}, ("currency",)) is CurrencyCode.INR
    assert currency({"currency": "inr"}, ("currency",)) is CurrencyCode.INR

    with pytest.raises(ParseFailedError, match="currency"):
        currency({"currency": "USD"}, ("currency",))


def test_only_present_drops_nulls_rather_than_recording_them() -> None:
    """A `{"size": None}` entry reads as "null size"; an absent key reads as "unknown"."""
    assert only_present({"size": "M", "color": None}) == {"size": "M"}


def test_unwrap_items_tries_envelopes_then_a_bare_array_then_a_bare_object() -> None:
    """A hand-cut fixture of one awkward listing is the fastest way to pin a
    parsing bug, and it should not need a wrapper to be replayable."""
    paths = [("response", "products"), ("products",)]

    assert list(unwrap_items({"response": {"products": [{"a": 1}]}}, paths)) == [{"a": 1}]
    assert list(unwrap_items({"products": [{"a": 1}, "junk"]}, paths)) == [{"a": 1}]
    assert list(unwrap_items([{"a": 1}], paths)) == [{"a": 1}]
    assert list(unwrap_items({"a": 1}, paths)) == [{"a": 1}]
    assert list(unwrap_items("not an item", paths)) == []


def test_iter_fixture_items_reads_every_recording_in_filename_order(
    tmp_path: FilePath,
) -> None:
    (tmp_path / "b.json").write_text(json.dumps({"products": [{"n": 2}]}), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps({"products": [{"n": 1}]}), encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("not json", encoding="utf-8")

    assert list(iter_fixture_items(tmp_path, [("products",)])) == [{"n": 1}, {"n": 2}]
