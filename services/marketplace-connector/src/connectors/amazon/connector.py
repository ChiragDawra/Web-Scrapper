"""Amazon connector: raw-fetch stub + `normalize()` mapping — Sprint 2 Task 2.3.

The first real implementation inside the Task 2.1 frame. `selectors.py` says
*where* each field is; this module says what it *means* — rupees to paise,
absent stock signal to `false`, `SavingBasis` to `mrp`.

**Two layers of rejection, one error code.** `CanonicalProduct` is a frozen
dataclass with non-optional `canonical_title`/`price`/`url`/`external_listing_id`,
so an item missing one of those cannot be constructed at all, let alone handed to
`validate()`. Those raise `ParseFailedError` here. Everything a constructed
product can still get wrong — price <= 0, `mrp` < price, a URL on the wrong host,
a rating above 5.0 — is left to `src.base.normalizer.validate()` (Task 2.2), which
owns `VALIDATION_RULES.md` §1 for all four marketplaces. Both paths raise the same
`CONN_PARSE_FAILED`, so the poll loop above (Task 2.5) sees one behaviour, and no
§1 rule is re-implemented here.

`normalize()` returns `validate()`'s return value rather than its own object:
§1 rule 1 specifies `canonical_title` as trimmed, and the validator does the
trimming into a `dataclasses.replace()` copy.

`fetch_raw()` is a stub against recorded fixtures, which is exactly what Task 2.3
asks for — the live read path is blocked on `INPUTS_NEEDED.md` item 1 (official
PA-API vs. a data provider vs. HTML). Nothing above `normalize()`'s return type
depends on that decision, so Sprint 3 can be built on this connector before the
answer arrives.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, ClassVar

from libs.canonical_models import CanonicalProduct
from libs.enums import CurrencyCode, MarketplaceCode
from src.base.connector_interface import ConnectorInterface, ParseFailedError
from src.base.normalizer import validate
from src.connectors.amazon import selectors
from src.connectors.amazon.selectors import Path as SelectorPath
from src.connectors.amazon.selectors import select

__all__ = ["DEFAULT_FIXTURE_DIR", "AmazonConnector"]

#: Amazon quotes money in major units ("Amount": 1499.0 is one thousand four
#: hundred and ninety-nine rupees). Every money field in the system is minor
#: units — `DATABASE_SCHEMA.md`: "All money integer minor units (paise)".
PAISE_PER_RUPEE = Decimal(100)

#: Recorded responses for the fetch stub. Under `tests/` because they are test
#: data and nothing else consumes them; the path is a constructor argument so
#: Task 2.6's container can point at a mounted directory instead.
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "amazon"


class AmazonConnector(ConnectorInterface):
    """Reads Amazon India listings and normalizes them. Owns no tables."""

    marketplace: ClassVar[MarketplaceCode] = MarketplaceCode.AMAZON

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self.fixture_dir = fixture_dir if fixture_dir is not None else DEFAULT_FIXTURE_DIR

    def fetch_raw(self) -> Iterator[dict[str, Any]]:
        """Yield one raw item per recorded listing, oldest filename first.

        A generator rather than a list so the Task 2.5 poll loop can skip a bad
        item and keep pulling, and so a live implementation returning a paged
        cursor is a drop-in replacement for this one.
        """
        for path in sorted(self.fixture_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            yield from _items(payload)

    def normalize(self, raw_marketplace_response: Any) -> CanonicalProduct:
        """`SERVICE_INTERFACES.md` §1. Returns a valid product or raises; no third outcome."""
        raw = raw_marketplace_response
        if not isinstance(raw, Mapping):
            raise ParseFailedError(f"item is {type(raw).__name__}, expected a mapping")

        product = CanonicalProduct(
            canonical_title=_required_text(raw, selectors.TITLE, "canonical_title"),
            marketplace=self.marketplace,
            external_listing_id=_required_text(raw, selectors.ASIN, "external_listing_id"),
            url=_required_text(raw, selectors.DETAIL_PAGE_URL, "url"),
            price=_paise(_require(raw, selectors.PRICE_AMOUNT, "price"), "price"),
            in_stock=_in_stock(raw),
            brand_name=_text(raw, selectors.BRAND) or _text(raw, selectors.MANUFACTURER),
            category=_text(raw, selectors.PRODUCT_GROUP),
            subcategory=_text(raw, selectors.BROWSE_NODE_NAME),
            attributes=_attributes(raw),
            image_url=_text(raw, selectors.IMAGE_URL),
            mrp=_optional_paise(raw, selectors.SAVING_BASIS_AMOUNT, "mrp"),
            currency=_currency(raw),
            rating=_optional_number(raw, selectors.RATING, "rating"),
            review_count=_optional_int(raw, selectors.REVIEW_COUNT, "review_count"),
        )

        # Task 2.2 owns every §1 rule, including the ones this mapping could
        # plausibly get right on its own. Duplicating a check here is how the
        # two copies drift.
        return validate(product)


def _items(payload: Any) -> Iterator[dict[str, Any]]:
    """Unwrap whatever envelope a recording was saved in.

    `SearchItems` and `GetItems` differ only in the wrapper key, and a hand-cut
    fixture is often just the array or a single item. All four are accepted so a
    recording never has to be reshaped by hand before it can be replayed.
    """
    for path in selectors.ITEM_LIST_PATHS:
        items = select(payload, path)
        if isinstance(items, list):
            yield from (item for item in items if isinstance(item, dict))
            return

    if isinstance(payload, list):
        yield from (item for item in payload if isinstance(item, dict))
    elif isinstance(payload, dict):
        yield payload


def _require(raw: Mapping[str, Any], path: SelectorPath, field: str) -> Any:
    value = select(raw, path)
    if value is None:
        raise ParseFailedError(f"{field}: missing at {'.'.join(str(key) for key in path)}")
    return value


def _text(raw: Mapping[str, Any], path: SelectorPath) -> str | None:
    """A trimmed string, or `None` when absent, blank or not a string.

    Blank collapses to `None` deliberately: for the optional fields this serves,
    an empty `brand_name` and a missing one mean the same thing downstream, and
    `resolveBrand("")` would otherwise create a nameless `brands` row.
    """
    value = select(raw, path)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _required_text(raw: Mapping[str, Any], path: SelectorPath, field: str) -> str:
    value = _require(raw, path, field)
    if not isinstance(value, str):
        raise ParseFailedError(f"{field}: {type(value).__name__}, expected a string")
    return value


def _paise(amount: Any, field: str) -> int:
    """Rupees as recorded -> paise as stored.

    Via `Decimal(str(...))`, never float: `1499.35 * 100` is `149934.99999...`
    in binary floating point, and `int()` of that is a rupee-and-a-bit short on
    every listing. Half-up rounding covers sub-paise precision, which is a bug
    at the source rather than a reason to drop an otherwise good listing.
    """
    if isinstance(amount, bool) or not isinstance(amount, int | float | str | Decimal):
        raise ParseFailedError(f"{field}: {amount!r} is not a number")
    try:
        rupees = Decimal(str(amount))
    except InvalidOperation as error:
        raise ParseFailedError(f"{field}: {amount!r} is not a number") from error
    if not rupees.is_finite():
        raise ParseFailedError(f"{field}: {amount!r} is not finite")

    return int((rupees * PAISE_PER_RUPEE).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _optional_paise(raw: Mapping[str, Any], path: SelectorPath, field: str) -> int | None:
    value = select(raw, path)
    return None if value is None else _paise(value, field)


def _optional_number(raw: Mapping[str, Any], path: SelectorPath, field: str) -> float | None:
    """Absent stays absent. §1 permits a null `rating`; it does not permit a made-up one."""
    value = select(raw, path)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ParseFailedError(f"{field}: {value!r} is not a number")
    return float(value)


def _optional_int(raw: Mapping[str, Any], path: SelectorPath, field: str) -> int | None:
    value = select(raw, path)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParseFailedError(f"{field}: {value!r} is not an integer")
    return value


def _currency(raw: Mapping[str, Any]) -> CurrencyCode:
    """Recorded currency, or `INR` when the offer omits it (the model's default).

    An unmapped code raises rather than falling back: `CurrencyCode` has one
    member on purpose, and quietly relabelling a USD price as rupees would put a
    wrong number into `deals.detected_price` with no trace.
    """
    code = _text(raw, selectors.PRICE_CURRENCY)
    if code is None:
        return CurrencyCode.INR
    try:
        return CurrencyCode(code.upper())
    except ValueError as error:
        raise ParseFailedError(f"currency: {code!r} is not a supported currency_code") from error


def _attributes(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Only keys that are actually present.

    `attributes` is an open map, but a `{"size": None}` entry reads as "this
    listing has a null size" to anything iterating it, where an absent key reads
    as "unknown" — which is the truth.
    """
    candidates = {
        "size": _text(raw, selectors.SELECTOR_SIZE),
        "color": _text(raw, selectors.SELECTOR_COLOR),
        "merchant_name": _text(raw, selectors.MERCHANT_NAME),
    }
    return {key: value for key, value in candidates.items() if value is not None}


def _in_stock(raw: Mapping[str, Any]) -> bool:
    """§1 rule 9: a positive signal or `False` — never `None`.

    `Availability.Type` is authoritative when present. The message is consulted
    only in its absence, for providers that return prose and no type. Everything
    else, including no `Offers` block whatsoever, is not a positive signal.

    Erring towards `False` is the safe direction: a false `True` sends a purchase
    agent at an unbuyable listing, while a false `False` costs one missed deal
    that the next poll picks up.
    """
    availability_type = _text(raw, selectors.AVAILABILITY_TYPE)
    if availability_type is not None:
        return availability_type.lower() in selectors.IN_STOCK_AVAILABILITY_TYPES

    message = _text(raw, selectors.AVAILABILITY_MESSAGE)
    if message is not None:
        folded = message.lower()
        return any(marker in folded for marker in selectors.IN_STOCK_MESSAGE_MARKERS)

    return False
