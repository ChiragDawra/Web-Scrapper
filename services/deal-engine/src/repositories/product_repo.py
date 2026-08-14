"""`products` access — Sprint 3 Task 3.1.

`DATABASE_SCHEMA.md` §3. A product is the marketplace-independent thing;
the offer for it lives in `listings` (§4).

The connection is injected and nothing here commits — the handler owns the
transaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Json

__all__ = ["Product", "ProductRepository"]


@dataclass(frozen=True, slots=True)
class Product:
    """One `products` row."""

    id: UUID
    brand_id: UUID | None
    canonical_title: str
    category: str | None
    subcategory: str | None
    attributes: Mapping[str, Any]
    image_url: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Product:
        """Build from a `_COLUMNS`-ordered row. psycopg decodes JSONB to a dict already."""
        return cls(
            id=row[0],
            brand_id=row[1],
            canonical_title=row[2],
            category=row[3],
            subcategory=row[4],
            attributes=row[5],
            image_url=row[6],
            created_at=row[7],
            updated_at=row[8],
        )


_COLUMNS: Final = (
    "id, brand_id, canonical_title, category, subcategory, "
    "attributes, image_url, created_at, updated_at"
)

_SELECT_BY_ID: Final = f"SELECT {_COLUMNS} FROM products WHERE id = %s"

# No ON CONFLICT: `products` has no natural unique key (§3 declares none —
# two listings for the same physical item are matched by the product matcher,
# not by a title constraint), so an insert here always produces a row.
_INSERT: Final = f"""
INSERT INTO products (brand_id, canonical_title, category, subcategory, attributes, image_url)
VALUES (%s, %s, %s, %s, %s, %s)
RETURNING {_COLUMNS}
"""


class ProductRepository:
    """Reads and writes `products`. Touches no other table."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_by_id(self, product_id: UUID) -> Product | None:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_BY_ID, (product_id,))
            row = cur.fetchone()
        return Product.from_row(row) if row else None

    def insert(
        self,
        *,
        brand_id: UUID | None,
        canonical_title: str,
        category: str | None = None,
        subcategory: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        image_url: str | None = None,
    ) -> Product:
        """Insert one product and return it as stored.

        `attributes` defaults to `{}` rather than NULL to match the column
        default (§3): a caller reading `product.attributes["size"]` should get
        a `KeyError`, not a `TypeError` on `None`.
        """
        params = (
            brand_id,
            canonical_title,
            category,
            subcategory,
            Json(dict(attributes or {})),
            image_url,
        )
        with self._conn.cursor() as cur:
            cur.execute(_INSERT, params)
            row = cur.fetchone()
        assert row is not None  # RETURNING on an unconditional INSERT
        return Product.from_row(row)
