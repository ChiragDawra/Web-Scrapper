"""Myntra connector: raw-fetch stub + `normalize()` mapping — Sprint 4 Task 4.2.1.

`selectors.py` says *where* each field is; this module says what it *means*, and
Myntra means three things nothing else in this service does:

1. `productId` is a JSON number. `external_listing_id` is a string, and
   `str(1466678)` is the same listing key on every poll, so the number is
   converted rather than the item dropped.
2. `landingPageUrl` is site-relative. §1 rule 6 wants an absolute URL on a known
   host, so it is joined onto `selectors.BASE_URL` here — a purchase agent
   handed `"puma-tshirt/1466678/buy"` has nowhere to go.
3. `price` is the *pre-discount* number and `discountedPrice` is what a buyer
   pays. Reading `price` as the price would score every listing against its MRP.

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
from urllib.parse import urljoin

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
    optional_int,
    optional_number,
    paise,
    require,
    select,
    text,
)
from src.connectors.myntra import selectors

__all__ = ["DEFAULT_FIXTURE_DIR", "MyntraConnector"]

#: Recorded responses for the fetch stub. Under `tests/` because they are test
#: data and nothing else consumes them; the path is a constructor argument so
#: the container can point at a mounted directory instead.
DEFAULT_FIXTURE_DIR: Final = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "myntra"


class MyntraConnector(ConnectorInterface):
    """Reads Myntra listings and normalizes them. Owns no tables."""

    marketplace: ClassVar[MarketplaceCode] = MarketplaceCode.MYNTRA

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
            raise ParseFailedError("canonical_title: missing at product or productName")

        product = CanonicalProduct(
            canonical_title=title,
            marketplace=self.marketplace,
            external_listing_id=identifier(raw, (selectors.PRODUCT_ID,), "external_listing_id"),
            url=_url(raw),
            price=_price(raw),
            in_stock=_in_stock(raw),
            brand_name=text(raw, selectors.BRAND),
            category=text(raw, selectors.CATEGORY),
            subcategory=text(raw, selectors.ARTICLE_TYPE),
            attributes=only_present(
                {
                    "size": text(raw, selectors.SIZES),
                    "color": text(raw, selectors.COLOR),
                }
            ),
            image_url=first_text(raw, selectors.IMAGE_URL_PATHS),
            mrp=_mrp(raw),
            # Myntra quotes no currency: it is an India-only marketplace and
            # every recorded amount is rupees. The model's default is the honest
            # value here, not a code invented from a missing field.
            currency=CurrencyCode.INR,
            rating=optional_number(raw, selectors.RATING, "rating"),
            review_count=optional_int(raw, selectors.REVIEW_COUNT, "review_count"),
        )

        # `validate()` owns every §1 rule, including the ones this mapping could
        # plausibly get right on its own. Duplicating a check here is how the
        # two copies drift.
        return validate(product)


def _price(raw: Mapping[str, Any]) -> int:
    """What a buyer pays: `discountedPrice` when Myntra quotes one, else `price`.

    Note the direction — `price` is the fallback, never the preference. On this
    shape `price` is the pre-discount number, and preferring it would score
    every discounted listing against its own MRP and find no deal at all.
    """
    discounted = select(raw, selectors.DISCOUNTED_PRICE)
    if discounted is not None:
        return paise(discounted, "price")
    return paise(require(raw, selectors.PRICE, "price"), "price")


def _url(raw: Mapping[str, Any]) -> str:
    """The site-relative `landingPageUrl` joined onto Myntra's base.

    An already-absolute value is left alone: `urljoin` returns it unchanged, and
    a recording that carries a full URL is not a reason to mangle it. The
    validator still checks the host, so a joined URL that somehow lands off
    `myntra.com` is dropped rather than trusted.
    """
    landing = require(raw, selectors.LANDING_PAGE_URL, "url")
    if not isinstance(landing, str) or not landing.strip():
        raise ParseFailedError(f"url: {landing!r} is not a usable landingPageUrl")
    return urljoin(selectors.BASE_URL, landing.strip())


def _mrp(raw: Mapping[str, Any]) -> int | None:
    """`mrp` when present, else the pre-discount `price`, else null.

    Falling back to `price` is not inventing a discount: on this shape `price`
    *is* the struck-through number. When there is no `discountedPrice`, the
    listing is undiscounted and `mrp == price` — which §1 rule 3 allows
    ("`mrp >= price`") and which reads correctly downstream as zero discount.
    """
    return first_paise(raw, selectors.MRP_PATHS, "mrp")


def _in_stock(raw: Mapping[str, Any]) -> bool:
    """§1 rule 9: a positive signal or `False` — never `None`.

    Stock is per size here, so any available size makes the listing buyable —
    that is what a deal card promises. An `available` entry with a zero
    inventory count is not a positive signal: Myntra leaves the flag set on
    sold-out sizes often enough that trusting it alone sends purchase agents at
    unbuyable SKUs.

    The whole-listing `outOfStock` flag is consulted only when there is no
    inventory list at all. Everything else, including a listing with neither, is
    not a positive signal — a false `False` costs one missed deal that the next
    poll picks up, while a false `True` costs a failed purchase.
    """
    inventory = select(raw, selectors.INVENTORY_INFO)
    if isinstance(inventory, list):
        return any(_size_available(entry) for entry in inventory)

    out_of_stock = flag(raw, selectors.OUT_OF_STOCK)
    if out_of_stock is not None:
        return not out_of_stock

    return False


def _size_available(entry: Any) -> bool:
    if not isinstance(entry, Mapping):
        return False
    if entry.get(selectors.INVENTORY_AVAILABLE_KEY) is not True:
        return False
    count = entry.get(selectors.INVENTORY_COUNT_KEY)
    if isinstance(count, bool) or not isinstance(count, int):
        return True  # No count recorded: the flag is the only signal there is.
    return count > 0
