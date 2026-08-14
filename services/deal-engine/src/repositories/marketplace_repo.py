"""`marketplaces` access — Sprint 3 Task 3.1.

`DATABASE_SCHEMA.md` §2. Read-only by design: that section says "Seed row per
marketplace_code value. No dynamic inserts at runtime." A `LISTING_DISCOVERED`
naming an unseeded marketplace is a deployment gap, and inserting the row here
would hide it behind a listing that appears to work.

The connection is injected and nothing here commits — the handler owns the
transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from psycopg import Connection

from libs.enums import MarketplaceCode

__all__ = ["Marketplace", "MarketplaceRepository"]


@dataclass(frozen=True, slots=True)
class Marketplace:
    """One `marketplaces` row."""

    id: UUID
    code: MarketplaceCode
    display_name: str
    base_url: str
    is_active: bool
    created_at: datetime

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Marketplace:
        """Build from a `_COLUMNS`-ordered row. `code` is re-typed, not trusted as str."""
        return cls(
            id=row[0],
            code=MarketplaceCode(row[1]),
            display_name=row[2],
            base_url=row[3],
            is_active=row[4],
            created_at=row[5],
        )


_COLUMNS: Final = "id, code, display_name, base_url, is_active, created_at"

# `code` is a Postgres enum and UNIQUE (§2), so exact match on the seeded value
# is the whole lookup — no case folding, unlike brands, whose names are free text.
_SELECT_BY_CODE: Final = f"SELECT {_COLUMNS} FROM marketplaces WHERE code = %s"


class MarketplaceRepository:
    """Reads `marketplaces`. Touches no other table, and never writes."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def find_by_code(self, code: MarketplaceCode) -> Marketplace | None:
        """The seeded row for one marketplace. `None` means the seed is missing.

        Callers should treat `None` as a configuration failure, not as an
        ordinary miss: every `MarketplaceCode` member is supposed to have a row.
        """
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_BY_CODE, (str(code),))
            row = cur.fetchone()
        return Marketplace.from_row(row) if row else None
