"""Where each `CanonicalProduct` field sits inside one raw Myntra item — Sprint 4 Task 4.2.1.

Split out from `connector.py` because this is the part that rots: Myntra can
move a field without changing what a listing *means*, and that diff should be a
path tuple in this file and nothing else.

**Which raw shape.** `INPUTS_NEEDED.md` item 1 is still open, so the recorded
fixtures this sprint runs against are Myntra product-search objects — a
`products[]` array, usually under a `data` envelope, where each entry carries
flat `price`/`discountedPrice` numbers, a per-size `inventoryInfo[]` list and a
site-relative `landingPageUrl`. Those three quirks are the whole reason this
connector is not a copy of Flipkart's; `connector.py` documents what each one
means. If direct HTML wins instead, this module becomes CSS selectors and
`connector.py` is untouched.

Paths are tuples of mapping keys and list indices, resolved by
`src.base.raw_mapping.select`. A missing key and an explicit `null` both
resolve to `None`.
"""

from __future__ import annotations

from typing import Final

from src.base.raw_mapping import Path

__all__ = [
    "ARTICLE_TYPE",
    "BASE_URL",
    "BRAND",
    "CATEGORY",
    "COLOR",
    "DISCOUNTED_PRICE",
    "IMAGE_URL_PATHS",
    "INVENTORY_AVAILABLE_KEY",
    "INVENTORY_COUNT_KEY",
    "INVENTORY_INFO",
    "ITEM_LIST_PATHS",
    "LANDING_PAGE_URL",
    "MRP_PATHS",
    "OUT_OF_STOCK",
    "PRICE",
    "PRODUCT_ID",
    "RATING",
    "REVIEW_COUNT",
    "SIZES",
    "SIZES_SEPARATOR",
    "TITLE_PATHS",
]

# --- Identity ----------------------------------------------------------------

#: A JSON *number*, not a string, unlike every other marketplace in scope.
#: `connector.py` is where that becomes the string `external_listing_id` is.
PRODUCT_ID: Final[Path] = ("productId",)

#: Site-relative ("puma-men-black-tshirt/1234/buy"), so it is not a URL until
#: `connector.py` joins it onto `BASE_URL`. §1 rule 6 wants an absolute URL on
#: a known host, and a purchase agent handed a relative path has nowhere to go.
LANDING_PAGE_URL: Final[Path] = ("landingPageUrl",)
BASE_URL: Final = "https://www.myntra.com/"

#: `product` on search responses, `productName` on the newer shape. Same field.
TITLE_PATHS: Final[tuple[Path, ...]] = (("product",), ("productName",))
BRAND: Final[Path] = ("brand",)

# --- Classification ----------------------------------------------------------

#: Myntra's own two-level split, already separate fields: "Tshirts" under
#: "Topwear". `articleType` is the leaf, which is what `subcategory` means.
CATEGORY: Final[Path] = ("category",)
ARTICLE_TYPE: Final[Path] = ("articleType",)

# --- Images ------------------------------------------------------------------

IMAGE_URL_PATHS: Final[tuple[Path, ...]] = (
    ("searchImage",),
    ("images", 0, "src"),
)

# --- Attributes --------------------------------------------------------------

#: A comma-joined string of every size in the listing ("S,M,L,XL"), not one
#: size. Carried through as recorded — `CanonicalProduct.attributes` is an open
#: map and the Deal Engine reads `size` as a label, not as a parsed set.
SIZES: Final[Path] = ("sizes",)
SIZES_SEPARATOR: Final = ","
COLOR: Final[Path] = ("primaryColour",)

# --- Money -------------------------------------------------------------------

#: Myntra's `price` is the *pre-discount* number and `discountedPrice` is what a
#: buyer pays — the opposite reading of `price` from every other connector here,
#: and the single most expensive field on this page to get backwards.
PRICE: Final[Path] = ("price",)
DISCOUNTED_PRICE: Final[Path] = ("discountedPrice",)

#: `mrp` when the response carries one, else the pre-discount `price`.
MRP_PATHS: Final[tuple[Path, ...]] = (("mrp",), ("price",))

# --- Stock -------------------------------------------------------------------

#: Stock is per size, not per listing: one `inventoryInfo` entry per SKU, each
#: with its own availability. `connector.py` treats any available size as the
#: listing being in stock, which is what a deal card means by "buyable".
INVENTORY_INFO: Final[Path] = ("inventoryInfo",)
INVENTORY_AVAILABLE_KEY: Final = "available"
INVENTORY_COUNT_KEY: Final = "inventory"

#: A whole-listing flag some responses carry instead of the inventory list.
OUT_OF_STOCK: Final[Path] = ("outOfStock",)

# --- Reviews -----------------------------------------------------------------

RATING: Final[Path] = ("rating",)
REVIEW_COUNT: Final[Path] = ("ratingCount",)

# --- Response envelopes ------------------------------------------------------

ITEM_LIST_PATHS: Final[tuple[Path, ...]] = (
    ("data", "products"),
    ("products",),
)
