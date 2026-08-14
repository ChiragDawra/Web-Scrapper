"""`listings` access — Sprint 3 Task 3.1.

`DATABASE_SCHEMA.md` §4. One row per (marketplace, external listing id); the
external id lives in a column, never as the primary key (ADR-011).

`current_price` and `mrp` are paise, integers, everywhere. Nothing in this
module converts money — the connector already did that at the boundary.

The connection is injected and nothing here commits — the handler owns the
transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from psycopg import Connection

from libs.enums import CurrencyCode

__all__ = ["Listing", "ListingRepository"]


@dataclass(frozen=True, slots=True)
class Listing:
    """One `listings` row."""

    id: UUID
    product_id: UUID
    marketplace_id: UUID
    external_listing_id: str
    url: str
    current_price: int
    currency: CurrencyCode
    mrp: int | None
    rating: Decimal | None
    review_count: int | None
    in_stock: bool
    last_scanned_at: datetime
    created_at: datetime

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Listing:
        """Build from a `_COLUMNS`-ordered row.

        `rating` stays a `Decimal` — the column is `NUMERIC(2,1)`, and floating
        point is not a thing to introduce on the way out of a scoring input.
        """
        return cls(
            id=row[0],
            product_id=row[1],
            marketplace_id=row[2],
            external_listing_id=row[3],
            url=row[4],
            current_price=row[5],
            currency=CurrencyCode(row[6]),
            mrp=row[7],
            rating=row[8],
            review_count=row[9],
            in_stock=row[10],
            last_scanned_at=row[11],
            created_at=row[12],
        )


_COLUMNS: Final = (
    "id, product_id, marketplace_id, external_listing_id, url, current_price, "
    "currency, mrp, rating, review_count, in_stock, last_scanned_at, created_at"
)

_SELECT_BY_ID: Final = f"SELECT {_COLUMNS} FROM listings WHERE id = %s"

# The UNIQUE (marketplace_id, external_listing_id) pair from §4 — the identity
# of an offer as far as this system is concerned.
_SELECT_BY_EXTERNAL: Final = f"""
SELECT {_COLUMNS} FROM listings
WHERE marketplace_id = %s AND external_listing_id = %s
"""

# `DO NOTHING` + `RETURNING` yields no row when a concurrent transaction
# inserted the same pair first; the caller re-reads. Same shape as brands.
_INSERT: Final = f"""
INSERT INTO listings (
  product_id, marketplace_id, external_listing_id, url,
  current_price, currency, mrp, rating, review_count, in_stock
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (marketplace_id, external_listing_id) DO NOTHING
RETURNING {_COLUMNS}
"""

# `last_scanned_at = now()` is set here and not passed in: the timestamp means
# "when this row was written", and a producer clock has no business deciding it.
# `url` is refreshed too — marketplaces reissue canonical URLs for the same id.
_UPDATE_OBSERVATION: Final = f"""
UPDATE listings
SET current_price = %s,
    mrp = %s,
    rating = %s,
    review_count = %s,
    in_stock = %s,
    url = COALESCE(%s, url),
    last_scanned_at = now()
WHERE id = %s
RETURNING {_COLUMNS}
"""


class ListingRepository:
    """Reads and writes `listings`. Touches no other table."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_by_id(self, listing_id: UUID) -> Listing | None:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_BY_ID, (listing_id,))
            row = cur.fetchone()
        return Listing.from_row(row) if row else None

    def find_by_external(self, marketplace_id: UUID, external_listing_id: str) -> Listing | None:
        """The offer a marketplace calls `external_listing_id`. `None` when unseen."""
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_BY_EXTERNAL, (marketplace_id, external_listing_id))
            row = cur.fetchone()
        return Listing.from_row(row) if row else None

    def insert(
        self,
        *,
        product_id: UUID,
        marketplace_id: UUID,
        external_listing_id: str,
        url: str,
        current_price: int,
        currency: CurrencyCode = CurrencyCode.INR,
        mrp: int | None = None,
        rating: Decimal | None = None,
        review_count: int | None = None,
        in_stock: bool = True,
    ) -> Listing | None:
        """Insert one listing. `None` if a concurrent transaction won the race."""
        params = (
            product_id,
            marketplace_id,
            external_listing_id,
            url,
            current_price,
            str(currency),
            mrp,
            rating,
            review_count,
            in_stock,
        )
        with self._conn.cursor() as cur:
            cur.execute(_INSERT, params)
            row = cur.fetchone()
        return Listing.from_row(row) if row else None

    def update_observation(
        self,
        listing_id: UUID,
        *,
        current_price: int,
        mrp: int | None = None,
        rating: Decimal | None = None,
        review_count: int | None = None,
        in_stock: bool = True,
        url: str | None = None,
    ) -> Listing | None:
        """Record what the latest scan saw. `None` if the listing is gone.

        This is the mutable "current state" half of an observation; the
        immutable half is one `price_history` row, written by its own
        repository in the same transaction.
        """
        params = (current_price, mrp, rating, review_count, in_stock, url, listing_id)
        with self._conn.cursor() as cur:
            cur.execute(_UPDATE_OBSERVATION, params)
            row = cur.fetchone()
        return Listing.from_row(row) if row else None
