"""Flipkart connector: raw-fetch stub + `normalize()` mapping — Sprint 4 Task 4.1.1.

`selectors.py` says *where* each field is; this module says what it *means* —
which of Flipkart's three prices a buyer actually pays, a `>`-joined category
path split into `category`/`subcategory`, a real `inStock` boolean taken at its
word.

**Two layers of rejection, one error code**, as in Sprint 2's Amazon connector:
`CanonicalProduct` cannot be constructed without `canonical_title`/`price`/
`url`/`external_listing_id`, so those raise `ParseFailedError` here, and
everything a constructed product can still get wrong — price <= 0, `mrp` below
price, a URL on the wrong host — is left to `src.base.normalizer.validate()`,
which owns `VALIDATION_RULES.md` §1 for all four marketplaces. Both paths raise
`CONN_PARSE_FAILED`, so the poll loop sees one behaviour and no §1 rule is
re-implemented per marketplace.

`normalize()` returns `validate()`'s return value rather than its own object:
§1 rule 1 specifies `canonical_title` as trimmed, and the validator does the
trimming into a `dataclasses.replace()` copy.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, ClassVar, Final

from libs.canonical_models import CanonicalProduct
from libs.enums import MarketplaceCode
from src.base.connector_interface import ConnectorInterface, ParseFailedError
from src.base.fixture_source import iter_fixture_items
from src.base.normalizer import validate
from src.base.raw_mapping import (
    currency,
    first_text,
    flag,
    only_present,
    optional_int,
    optional_number,
    optional_paise,
    required_paise,
    required_text,
    text,
)
from src.connectors.flipkart import selectors

__all__ = ["DEFAULT_FIXTURE_DIR", "FlipkartConnector"]

#: Recorded responses for the fetch stub. Under `tests/` because they are test
#: data and nothing else consumes them; the path is a constructor argument so
#: the container can point at a mounted directory instead.
DEFAULT_FIXTURE_DIR: Final = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "flipkart"


class FlipkartConnector(ConnectorInterface):
    """Reads Flipkart listings and normalizes them. Owns no tables."""

    marketplace: ClassVar[MarketplaceCode] = MarketplaceCode.FLIPKART

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

        category, subcategory = _category_path(raw)

        product = CanonicalProduct(
            canonical_title=required_text(raw, selectors.TITLE, "canonical_title"),
            marketplace=self.marketplace,
            external_listing_id=required_text(raw, selectors.PRODUCT_ID, "external_listing_id"),
            url=required_text(raw, selectors.PRODUCT_URL, "url"),
            price=_price(raw),
            in_stock=_in_stock(raw),
            brand_name=text(raw, selectors.BRAND),
            category=category,
            subcategory=subcategory,
            attributes=only_present(
                {
                    "size": text(raw, selectors.SIZE),
                    "color": text(raw, selectors.COLOR),
                    "seller_name": text(raw, selectors.SELLER_NAME),
                }
            ),
            image_url=first_text(raw, selectors.IMAGE_URL_PATHS),
            mrp=optional_paise(raw, selectors.MAXIMUM_RETAIL_PRICE_AMOUNT, "mrp"),
            currency=currency(raw, selectors.PRICE_CURRENCY),
            rating=optional_number(raw, selectors.RATING, "rating"),
            review_count=optional_int(raw, selectors.REVIEW_COUNT, "review_count"),
        )

        # `validate()` owns every §1 rule, including the ones this mapping could
        # plausibly get right on its own. Duplicating a check here is how the
        # two copies drift.
        return validate(product)


def _price(raw: Mapping[str, Any]) -> int:
    """The special price when Flipkart quotes one, otherwise the selling price.

    Missing *both* is fatal for the item rather than a fallback to MRP: MRP is
    the number nobody pays, and scoring a deal against it would invent a
    discount that does not exist.
    """
    return required_paise(raw, selectors.PRICE_PATHS, "price")


def _category_path(raw: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Split "Clothing>Men's Clothing>T-Shirts" into its broadest and narrowest parts.

    The leaf is the useful one for `subcategory`, and the root is what
    `category` means elsewhere in the system. Middle segments are dropped
    rather than joined: `CanonicalProduct` has two slots, and a
    `"Men's Clothing>T-Shirts"` `subcategory` would not group with the same
    leaf arriving under a different parent from another marketplace.

    A single-segment path is a category with no subcategory, not a subcategory
    with no parent.
    """
    joined = text(raw, selectors.CATEGORY_PATH)
    if joined is None:
        return None, None

    segments = [
        segment.strip()
        for segment in joined.split(selectors.CATEGORY_PATH_SEPARATOR)
        if segment.strip()
    ]
    if not segments:
        return None, None
    if len(segments) == 1:
        return segments[0], None
    return segments[0], segments[-1]


def _in_stock(raw: Mapping[str, Any]) -> bool:
    """§1 rule 9: a positive signal or `False` — never `None`.

    The `inStock` boolean is authoritative when it really is a boolean. The
    availability message is consulted only in its absence, for providers that
    return prose and no flag. Everything else, including a listing with neither,
    is not a positive signal.

    Erring towards `False` is the safe direction: a false `True` sends a
    purchase agent at an unbuyable listing, while a false `False` costs one
    missed deal that the next poll picks up.
    """
    in_stock = flag(raw, selectors.IN_STOCK)
    if in_stock is not None:
        return in_stock

    message = text(raw, selectors.AVAILABILITY_MESSAGE)
    if message is not None:
        folded = message.lower()
        if "out of stock" in folded or "sold out" in folded:
            return False
        return any(marker in folded for marker in selectors.IN_STOCK_MESSAGE_MARKERS)

    return False
