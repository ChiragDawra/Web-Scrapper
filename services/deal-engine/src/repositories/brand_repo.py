"""`brands` access — Sprint 3 Task 3.1.

`DATABASE_SCHEMA.md` §1. Backs `resolveBrand()` (`SERVICE_INTERFACES.md` §2):
case-insensitive exact match, `STANDARD`-tier row created on miss. The matching
and creation *policy* lives in `services/brand_resolver.py` (Task 3.2); this
module only knows how to ask the table.

The connection is injected and nothing here commits — a handler processes one
event in one transaction, and a repository that committed on its own would
break that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from psycopg import Connection

from libs.enums import BrandTier

__all__ = ["Brand", "BrandRepository"]


@dataclass(frozen=True, slots=True)
class Brand:
    """One `brands` row."""

    id: UUID
    name: str
    tier: BrandTier
    created_at: datetime

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Brand:
        """Build from a `_COLUMNS`-ordered row.

        Explicit rather than `psycopg.rows.class_row`: the driver hands back
        `tier` as a plain string, and a `Brand` holding `"STANDARD"` where the
        annotation promises a `BrandTier` would type-check and then fail an
        `is` comparison at the one place it matters — the scorer.
        """
        return cls(id=row[0], name=row[1], tier=BrandTier(row[2]), created_at=row[3])


_COLUMNS: Final = "id, name, tier, created_at"

# `lower(name) = lower(%s)` rather than `ILIKE`: ILIKE treats `%` and `_` in the
# argument as wildcards, and brand names are attacker-influenced free text
# arriving from a marketplace listing.
_SELECT_BY_NAME: Final = f"SELECT {_COLUMNS} FROM brands WHERE lower(name) = lower(%s)"

# `DO NOTHING` + `RETURNING` yields no row when another transaction inserted the
# same name first; the caller re-reads. `name` is UNIQUE (§1), so this is the
# whole race.
_INSERT: Final = f"""
INSERT INTO brands (name, tier) VALUES (%s, %s)
ON CONFLICT (name) DO NOTHING
RETURNING {_COLUMNS}
"""


class BrandRepository:
    """Reads and writes `brands`. Touches no other table."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def find_by_name(self, name: str) -> Brand | None:
        """Case-insensitive exact match. `None` when the brand is unknown."""
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_BY_NAME, (name,))
            row = cur.fetchone()
        return Brand.from_row(row) if row else None

    def insert(self, name: str, tier: BrandTier = BrandTier.STANDARD) -> Brand | None:
        """Insert one brand. `None` if a concurrent transaction already inserted the name.

        `STANDARD` by default per `CANONICAL_MODELS.md` "Brand resolution": a
        brand nobody has classified is ordinary, not premium and not unbranded.
        """
        with self._conn.cursor() as cur:
            cur.execute(_INSERT, (name, str(tier)))
            row = cur.fetchone()
        return Brand.from_row(row) if row else None
