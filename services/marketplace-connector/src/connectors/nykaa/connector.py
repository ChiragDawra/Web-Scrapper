"""Nykaa connector: raw-fetch stub + `normalize()` mapping — Sprint 4 Task 4.3.1.

`selectors.py` says *where* each field is; this module says what it *means*, and
Nykaa means two things nothing else in this service does:

1. Money arrives as a display string as often as a number — `"₹1,299"`,
   `"899.00"`. The shared paise conversion strips the sign and the grouping
   separator, because dropping a good listing over punctuation helps nobody,
   and a value that is still not a number after that is a real defect.
2. Stock is an on-hand `quantity` as often as a boolean, and `0` is the one
   unambiguous out-of-stock signal the catalog gives.

**Two layers of rejection, one error code**, as in Sprint 2's Amazon connector:
`CanonicalProduct` cannot be constructed without `canonical_title`/`price`/
`url`/`external_listing_id`, so those raise `ParseFailedError` here, and
everything a constructed product can still get wrong — price <= 0, `mrp` below
price, a URL on the wrong host — is left to `src.base.normalizer.validate()`,
which owns `VALIDATION_RULES.md` §1 for all four marketplaces. Both paths raise
`CONN_PARSE_FAILED`, so the poll loop sees one behaviour.

`normalize()` returns `validate()`'s return value rather than its own object:
§1 rule 1 specifies `canonical_title` as trimmed, and the validator does the
trimming into a `dataclasses.replace()` copy.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, ClassVar, Final

from libs.canonical_models import CanonicalProduct
from libs.enums import CurrencyCode, MarketplaceCode
from src.base.connector_interface import ConnectorInterface, ParseFailedError
from src.base.fixture_source import iter_fixture_items
from src.base.normalizer import validate
from src.base.raw_mapping import (
    first_paise,
    first_text,
    flag,
    identifier,
    only_present,
    optional_number,
    required_paise,
    select,
    text,
)
from src.connectors.nykaa import selectors

__all__ = ["DEFAULT_FIXTURE_DIR", "NykaaConnector"]

#: Recorded responses for the fetch stub. Under `tests/` because they are test
#: data and nothing else consumes them; the path is a constructor argument so
#: the container can point at a mounted directory instead.
DEFAULT_FIXTURE_DIR: Final = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "nykaa"


class NykaaConnector(ConnectorInterface):
    """Reads Nykaa listings and normalizes them. Owns no tables."""

    marketplace: ClassVar[MarketplaceCode] = MarketplaceCode.NYKAA

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self.fixture_dir = fixture_dir if fixture_dir is not None else DEFAULT_FIXTURE_DIR

    def fetch_raw(self) -> Iterator[dict[str, Any]]:
        """Yield one raw item per recorded listing, oldest filename first."""
        return iter_fixture_items(self.fixture_dir, selectors.ITEM_LIST_PATHS)

    def normalize(self, raw_marketplace_response: Any) -> CanonicalProduct:
        """`SERVICE_INTERFACES.md` §1. Returns a valid product or raises; no third outcome."""
        raw = raw_marketplace_response
        if not isinstance(raw, Mapping):
            raise ParseFailedError(f"item is a {type(raw).__name__}, expected a mapping")

        title = first_text(raw, selectors.TITLE_PATHS)
        if title is None:
            raise ParseFailedError("canonical_title: missing at name or title")

        url = first_text(raw, selectors.PRODUCT_URL_PATHS)
        if url is None:
            raise ParseFailedError("url: missing at product_url or url")

        product = CanonicalProduct(
            canonical_title=title,
            marketplace=self.marketplace,
            external_listing_id=identifier(raw, selectors.PRODUCT_ID_PATHS, "external_listing_id"),
            url=url,
            price=required_paise(raw, selectors.PRICE_PATHS, "price"),
            in_stock=_in_stock(raw),
            brand_name=first_text(raw, selectors.BRAND_PATHS),
            category=text(raw, selectors.CATEGORY),
            subcategory=first_text(raw, selectors.SUBCATEGORY_PATHS),
            attributes=only_present(
                {
                    "size": first_text(raw, selectors.PACK_SIZE_PATHS),
                    "color": first_text(raw, selectors.SHADE_NAME_PATHS),
                    "variant": text(raw, selectors.VARIANT_NAME),
                }
            ),
            image_url=first_text(raw, selectors.IMAGE_URL_PATHS),
            mrp=first_paise(raw, selectors.MRP_PATHS, "mrp"),
            # Nykaa quotes no currency code: it is an India-only marketplace and
            # every recorded amount is rupees. The model's default is the honest
            # value here, not a code invented from a missing field.
            currency=CurrencyCode.INR,
            rating=optional_number(raw, selectors.RATING, "rating"),
            review_count=_review_count(raw),
        )

        # `validate()` owns every §1 rule, including the ones this mapping could
        # plausibly get right on its own. Duplicating a check here is how the
        # two copies drift.
        return validate(product)


def _review_count(raw: Mapping[str, Any]) -> int | None:
    """Review count from the first path that carries one, as an integer.

    Recorded as a string on the search shape (`"1,204"`), so digits are read out
    of it rather than the listing dropped — but only digits: a `"1.2k"` count is
    a rounded display value, and §1 rule 8 would rather have no count than a
    wrong one.
    """
    for path in selectors.REVIEW_COUNT_PATHS:
        value = select(raw, path)
        if value is None:
            continue
        if isinstance(value, bool):
            raise ParseFailedError(f"review_count: {value!r} is not an integer")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            digits = value.replace(",", "").strip()
            if digits.isdigit():
                return int(digits)
        raise ParseFailedError(f"review_count: {value!r} is not an integer")
    return None


def _in_stock(raw: Mapping[str, Any]) -> bool:
    """§1 rule 9: a positive signal or `False` — never `None`.

    The boolean wins when it is a real boolean. Otherwise the on-hand quantity
    decides, which is the field the catalog shape actually ships; a quantity of
    `0` is out of stock, and any positive count is in stock. The prose status is
    the last resort, for shapes that carry neither.

    Erring towards `False` is the safe direction: a false `True` sends a
    purchase agent at an unbuyable listing, while a false `False` costs one
    missed deal that the next poll picks up.
    """
    in_stock = flag(raw, selectors.IN_STOCK)
    if in_stock is not None:
        return in_stock

    quantity = select(raw, selectors.QUANTITY)
    if isinstance(quantity, int) and not isinstance(quantity, bool):
        return quantity > 0

    status = text(raw, selectors.STOCK_STATUS)
    if status is not None:
        folded = status.lower()
        if "out of stock" in folded or "sold out" in folded:
            return False
        return any(marker in folded for marker in selectors.IN_STOCK_STATUS_MARKERS)

    return False
