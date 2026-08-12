"""Where each `CanonicalProduct` field sits inside one raw Amazon item — Sprint 2 Task 2.3.

Split out of `connector.py` because this is the part that rots. Amazon can move a
field without changing what a listing *means*; when it does, the diff should be a
path tuple in this file and nothing else. `connector.py` holds the mapping rules
(paise conversion, stock inference, fallbacks), which do not change when a key
moves.

**Which raw shape.** `INPUTS_NEEDED.md` item 1 is still open — official PA-API,
a third-party provider, or direct HTML. The fixtures this sprint runs against are
PA-API 5.0 `GetItems`/`SearchItems` `Items[]` objects, for two reasons: it is the
only one of the three with a published, stable field layout, and providers under
option (b) return either PA-API's shape or a flatter one that maps onto these
same paths. If option (c) wins instead, this module becomes CSS selectors and
`connector.py` is untouched — which is the whole point of the split.

Paths are tuples of mapping keys and list indices, resolved by `select()`. A
missing key and an explicit `null` both resolve to `None`: Amazon omits absent
fields rather than nulling them, and no rule in `VALIDATION_RULES.md` §1 treats
the two differently.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "ASIN",
    "AVAILABILITY_MESSAGE",
    "AVAILABILITY_TYPE",
    "BRAND",
    "BROWSE_NODE_NAME",
    "DETAIL_PAGE_URL",
    "IMAGE_URL",
    "IN_STOCK_AVAILABILITY_TYPES",
    "IN_STOCK_MESSAGE_MARKERS",
    "ITEM_LIST_PATHS",
    "MANUFACTURER",
    "MERCHANT_NAME",
    "PRICE_AMOUNT",
    "PRICE_CURRENCY",
    "PRODUCT_GROUP",
    "RATING",
    "REVIEW_COUNT",
    "SAVING_BASIS_AMOUNT",
    "SELECTOR_COLOR",
    "SELECTOR_SIZE",
    "Path",
    "select",
]

Path = tuple[str | int, ...]

# --- Identity ---------------------------------------------------------------

#: `external_listing_id`. The ASIN is Amazon's own listing key, so it satisfies
#: §1's "unique per marketplace" without any derivation of ours.
ASIN: Path = ("ASIN",)
DETAIL_PAGE_URL: Path = ("DetailPageURL",)

# --- Descriptive ------------------------------------------------------------

TITLE: Path = ("ItemInfo", "Title", "DisplayValue")
BRAND: Path = ("ItemInfo", "ByLineInfo", "Brand", "DisplayValue")
#: Fallback for `brand_name`. Plenty of Amazon India listings carry a
#: manufacturer and no brand; the Deal Engine's `resolveBrand()` would rather
#: have an imperfect name than a null.
MANUFACTURER: Path = ("ItemInfo", "ByLineInfo", "Manufacturer", "DisplayValue")
PRODUCT_GROUP: Path = ("ItemInfo", "Classifications", "ProductGroup", "DisplayValue")
BROWSE_NODE_NAME: Path = ("BrowseNodeInfo", "BrowseNodes", 0, "DisplayName")
IMAGE_URL: Path = ("Images", "Primary", "Large", "URL")

# --- Attributes -------------------------------------------------------------

#: `CanonicalProduct.attributes` is an open map, but only `size`/`color`/
#: `variant` are read downstream. PA-API's item payload carries no variant
#: label — variants come from `VariationsResult`, a separate operation — so the
#: connector leaves `variant` unset rather than inventing one from `Binding`.
SELECTOR_SIZE: Path = ("ItemInfo", "ProductInfo", "Size", "DisplayValue")
SELECTOR_COLOR: Path = ("ItemInfo", "ProductInfo", "Color", "DisplayValue")
MERCHANT_NAME: Path = ("Offers", "Listings", 0, "MerchantInfo", "Name")

# --- Money ------------------------------------------------------------------

#: Offer 0 only. PA-API sorts `Offers.Listings` with the buy-box winner first,
#: and that is the price a purchase agent would actually pay.
PRICE_AMOUNT: Path = ("Offers", "Listings", 0, "Price", "Amount")
PRICE_CURRENCY: Path = ("Offers", "Listings", 0, "Price", "Currency")
#: `mrp`. Amazon calls the struck-through reference price `SavingBasis`; it is
#: absent whenever the item is not discounted, which is why `mrp` is nullable.
SAVING_BASIS_AMOUNT: Path = ("Offers", "Listings", 0, "SavingBasis", "Amount")

# --- Stock ------------------------------------------------------------------

AVAILABILITY_TYPE: Path = ("Offers", "Listings", 0, "Availability", "Type")
AVAILABILITY_MESSAGE: Path = ("Offers", "Listings", 0, "Availability", "Message")

#: Compared case-folded. `Now` is PA-API's only in-stock `Availability.Type`;
#: everything else, including its absence, is not a positive signal and §1
#: rule 9 then requires `in_stock=false`.
IN_STOCK_AVAILABILITY_TYPES = frozenset({"now"})

#: Message fallback, used only when `Availability.Type` is absent — some
#: providers return the human string and nothing else. Substring match on a
#: case-folded message, so "Only 3 left in stock - order soon." counts and
#: "Currently unavailable." does not.
IN_STOCK_MESSAGE_MARKERS = ("in stock",)

# --- Reviews ----------------------------------------------------------------

#: PA-API 5.0 itself returns no star rating or review count — its
#: `CustomerReviews` resource is an iframe URL. These paths exist for the
#: provider case (option b), which does return them. Absent means `None`, which
#: §1 permits; a fabricated rating would silently skew Deal Engine scoring.
RATING: Path = ("CustomerReviews", "StarRating", "Value")
REVIEW_COUNT: Path = ("CustomerReviews", "Count")

# --- Response envelopes -----------------------------------------------------

#: Where a recorded response keeps its item array, most specific first.
#: `SearchItems` and `GetItems` differ only in this wrapper.
ITEM_LIST_PATHS: tuple[Path, ...] = (
    ("SearchResult", "Items"),
    ("ItemsResult", "Items"),
    ("Items",),
)


def select(raw: Any, path: Path) -> Any:
    """Walk `path` through `raw`, returning `None` the moment it stops resolving.

    Total by design: every caller here is asking "is this field present and what
    is it", and a `KeyError`/`TypeError` escaping mid-parse would abort an item
    that a later `validate()` call is entitled to judge for itself.
    """
    current: Any = raw
    for key in path:
        if isinstance(key, int):
            if not isinstance(current, Sequence) or isinstance(current, str | bytes):
                return None
            if not -len(current) <= key < len(current):
                return None
            current = current[key]
        else:
            if not isinstance(current, Mapping):
                return None
            current = current.get(key)
            if current is None:
                return None
    return current
