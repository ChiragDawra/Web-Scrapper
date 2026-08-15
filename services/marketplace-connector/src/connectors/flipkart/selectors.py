"""Where each `CanonicalProduct` field sits inside one raw Flipkart item — Sprint 4 Task 4.1.1.

Split out from `connector.py` for the reason Sprint 2 split Amazon's: this is
the part that rots. Flipkart can move a field without changing what a listing
*means*, and that diff should be a path tuple in this file and nothing else.

**Which raw shape.** `INPUTS_NEEDED.md` item 1 is still open for every
marketplace, so the recorded fixtures this sprint runs against are Flipkart
Affiliate API product objects — a `products[]` array whose entries wrap a
`productBaseInfoV1` block, with shipping and category detail alongside it. That
is the one published, documented Flipkart shape; a data provider under option
(b) generally re-serves it, and if direct HTML (option c) wins instead this
module becomes CSS selectors and `connector.py` is untouched.

Paths are tuples of mapping keys and list indices, resolved by
`src.base.raw_mapping.select`. A missing key and an explicit `null` both
resolve to `None`.
"""

from __future__ import annotations

from typing import Final

from src.base.raw_mapping import Path

__all__ = [
    "AVAILABILITY_MESSAGE",
    "BRAND",
    "CATEGORY_PATH",
    "CATEGORY_PATH_SEPARATOR",
    "COLOR",
    "IMAGE_URL_PATHS",
    "IN_STOCK",
    "IN_STOCK_MESSAGE_MARKERS",
    "ITEM_LIST_PATHS",
    "MAXIMUM_RETAIL_PRICE_AMOUNT",
    "PRICE_CURRENCY",
    "PRICE_PATHS",
    "PRODUCT_ID",
    "PRODUCT_URL",
    "RATING",
    "REVIEW_COUNT",
    "SELLER_NAME",
    "SIZE",
    "TITLE",
]

_BASE: Final[Path] = ("productBaseInfoV1",)

# --- Identity ----------------------------------------------------------------

#: `productId` is Flipkart's stable per-listing id (`ITMxxxxxxxx`-style), which
#: is what `external_listing_id` means: the key `(marketplace, id)` the Deal
#: Engine dedups `listings` on. Not `pid`, which varies per seller offer.
PRODUCT_ID: Final[Path] = (*_BASE, "productId")
PRODUCT_URL: Final[Path] = (*_BASE, "productUrl")
TITLE: Final[Path] = (*_BASE, "title")
BRAND: Final[Path] = (*_BASE, "productBrand")

# --- Classification ----------------------------------------------------------

#: One `>`-joined string ("Clothing>Men's Clothing>T-Shirts"), unlike Amazon's
#: separate product group and browse node. `connector.py` splits it into
#: `category`/`subcategory`; this file only says where the string is.
CATEGORY_PATH: Final[Path] = (*_BASE, "categoryPath")
CATEGORY_PATH_SEPARATOR: Final = ">"

# --- Images ------------------------------------------------------------------

#: `imageUrls` is keyed by pixel size. Largest first: the deal card renders a
#: product image, and an upscaled 200x200 looks like a broken listing.
IMAGE_URL_PATHS: Final[tuple[Path, ...]] = (
    (*_BASE, "imageUrls", "800x800"),
    (*_BASE, "imageUrls", "400x400"),
    (*_BASE, "imageUrls", "200x200"),
)

# --- Attributes --------------------------------------------------------------

SIZE: Final[Path] = (*_BASE, "size")
COLOR: Final[Path] = (*_BASE, "color")
SELLER_NAME: Final[Path] = ("productShippingInfoV1", "sellerName")

# --- Money -------------------------------------------------------------------

#: Flipkart quotes three prices. Special price is what a buyer actually pays
#: when it exists, selling price when it does not; MRP is the struck-through
#: number and belongs in `mrp`, never in `price`. Order matters — reading
#: `flipkartSellingPrice` first would score a deal against a price nobody is
#: charged, and §1 rule 3 would then reject a perfectly good listing whenever
#: the special price sat below it.
PRICE_PATHS: Final[tuple[Path, ...]] = (
    (*_BASE, "flipkartSpecialPrice", "amount"),
    (*_BASE, "flipkartSellingPrice", "amount"),
)
PRICE_CURRENCY: Final[Path] = (*_BASE, "flipkartSellingPrice", "currency")
MAXIMUM_RETAIL_PRICE_AMOUNT: Final[Path] = (*_BASE, "maximumRetailPrice", "amount")

# --- Stock -------------------------------------------------------------------

#: A real boolean, which makes Flipkart the easy case: §1 rule 9 wants a
#: positive signal and this field is one. The message is consulted only when the
#: boolean is absent or is not a boolean at all.
IN_STOCK: Final[Path] = (*_BASE, "inStock")
AVAILABILITY_MESSAGE: Final[Path] = (*_BASE, "availability")

#: Compared against the case-folded message. "Out of stock" contains neither, so
#: it stays `False`, and "Only 2 left" is in stock.
IN_STOCK_MESSAGE_MARKERS: Final[tuple[str, ...]] = ("in stock", "left in stock", "left")

# --- Reviews -----------------------------------------------------------------

#: The affiliate feed itself carries no rating; these paths exist for the
#: provider case, which does. Absent means `None`, which §1 rule 7 permits — a
#: fabricated rating would silently skew Deal Engine scoring.
RATING: Final[Path] = (*_BASE, "productRating", "average")
REVIEW_COUNT: Final[Path] = (*_BASE, "productRating", "count")

# --- Response envelopes ------------------------------------------------------

#: Where a recorded response keeps its item array, most specific first. The
#: feed endpoint returns `productInfoList`, search returns `products`.
ITEM_LIST_PATHS: Final[tuple[Path, ...]] = (
    ("productInfoList",),
    ("products",),
)
