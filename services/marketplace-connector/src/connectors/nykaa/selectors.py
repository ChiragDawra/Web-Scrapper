"""Where each `CanonicalProduct` field sits inside one raw Nykaa item — Sprint 4 Task 4.3.1.

Split out from `connector.py` because this is the part that rots: Nykaa can move
a field without changing what a listing *means*, and that diff should be a path
tuple in this file and nothing else.

**Which raw shape.** `INPUTS_NEEDED.md` item 1 is still open, so the recorded
fixtures this sprint runs against are Nykaa catalog product objects — a
`products[]` array under a `response` or `data` envelope, with money quoted as
display strings (`"₹1,299"`, `"899.00"`), a three-level `primary_categories`
block, and stock expressed as an on-hand `quantity` as often as a boolean. Those
are the quirks `connector.py` interprets. If direct HTML wins instead, this
module becomes CSS selectors and `connector.py` is untouched.

Paths are tuples of mapping keys and list indices, resolved by
`src.base.raw_mapping.select`. A missing key and an explicit `null` both resolve
to `None`.
"""

from __future__ import annotations

from typing import Final

from src.base.raw_mapping import Path

__all__ = [
    "BRAND_PATHS",
    "CATEGORY",
    "IMAGE_URL_PATHS",
    "IN_STOCK",
    "IN_STOCK_STATUS_MARKERS",
    "ITEM_LIST_PATHS",
    "MRP_PATHS",
    "PACK_SIZE_PATHS",
    "PRICE_PATHS",
    "PRODUCT_ID_PATHS",
    "PRODUCT_URL_PATHS",
    "QUANTITY",
    "RATING",
    "REVIEW_COUNT_PATHS",
    "SHADE_NAME_PATHS",
    "STOCK_STATUS",
    "SUBCATEGORY_PATHS",
    "TITLE_PATHS",
    "VARIANT_NAME",
]

# --- Identity ----------------------------------------------------------------

#: `sku` first: Nykaa's `id` is per catalog row and changes when a product is
#: relisted, while the SKU stays with the thing on the shelf. `external_listing_id`
#: is the key `listings` dedups on, so a churning id would create a new listing —
#: and a new deal — for a product that never changed.
PRODUCT_ID_PATHS: Final[tuple[Path, ...]] = (("sku",), ("product_id",), ("id",))
PRODUCT_URL_PATHS: Final[tuple[Path, ...]] = (("product_url",), ("url",))
TITLE_PATHS: Final[tuple[Path, ...]] = (("name",), ("title",))

#: Flat on the search shape, nested on the detail shape. Same field.
BRAND_PATHS: Final[tuple[Path, ...]] = (("brand_name",), ("brand", "name"))

# --- Classification ----------------------------------------------------------

#: Three levels, already separate: l1 "Makeup", l2 "Face", l3 "Foundation".
#: `CanonicalProduct` has two slots, so the broadest and the narrowest win — l2
#: is dropped rather than joined, because a `"Face > Foundation"` `subcategory`
#: would not group with the same leaf arriving from another marketplace.
CATEGORY: Final[Path] = ("primary_categories", "l1", "name")
SUBCATEGORY_PATHS: Final[tuple[Path, ...]] = (
    ("primary_categories", "l3", "name"),
    ("primary_categories", "l2", "name"),
)

# --- Images ------------------------------------------------------------------

IMAGE_URL_PATHS: Final[tuple[Path, ...]] = (("image_url",), ("images", 0, "url"))

# --- Attributes --------------------------------------------------------------

#: Beauty listings vary by shade and pack size rather than by garment size, so
#: `shade_name` is what `color` means here and the pack size is what `size` does.
SHADE_NAME_PATHS: Final[tuple[Path, ...]] = (("shade_name",), ("variant", "shade"))
PACK_SIZE_PATHS: Final[tuple[Path, ...]] = (("pack_size",), ("size",))
VARIANT_NAME: Final[Path] = ("variant_name",)

# --- Money -------------------------------------------------------------------

#: What a buyer pays, most specific first. Quoted as display strings often
#: enough that the paise conversion strips grouping separators and the rupee
#: sign rather than dropping the listing over punctuation.
PRICE_PATHS: Final[tuple[Path, ...]] = (("final_price",), ("offer_price",), ("price",))

#: The struck-through number. `price` is *not* a fallback: on this shape it is
#: what a buyer pays when no offer applies, so reading it as MRP would report a
#: discount of zero as a discount off itself.
MRP_PATHS: Final[tuple[Path, ...]] = (("mrp",), ("list_price",))

# --- Stock -------------------------------------------------------------------

IN_STOCK: Final[Path] = ("in_stock",)

#: On-hand units. Nykaa ships this on the catalog shape more reliably than any
#: boolean, and `0` is the one unambiguous out-of-stock signal it gives.
QUANTITY: Final[Path] = ("quantity",)
STOCK_STATUS: Final[Path] = ("stock_status",)

#: Compared against the case-folded status. "Out of stock" and "Sold out"
#: contain neither.
IN_STOCK_STATUS_MARKERS: Final[tuple[str, ...]] = ("in stock", "available", "low stock")

# --- Reviews -----------------------------------------------------------------

RATING: Final[Path] = ("rating",)
REVIEW_COUNT_PATHS: Final[tuple[Path, ...]] = (("rating_count",), ("review_count",))

# --- Response envelopes ------------------------------------------------------

ITEM_LIST_PATHS: Final[tuple[Path, ...]] = (
    ("response", "products"),
    ("data", "products"),
    ("products",),
)
