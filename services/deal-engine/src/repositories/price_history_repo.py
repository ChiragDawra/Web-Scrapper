"""`price_history` access — Sprint 3 Task 3.1.

`DATABASE_SCHEMA.md` §5. Append-only: rows are inserted and never updated, so
there is no `update`/`delete` on this repository at all. The series attaches to
`listing_id`, not `product_id` (Q26) — an Amazon price and a Flipkart price are
two series, and merging them would invent discounts that never existed.

`lowest_price`, `first_seen` and `last_seen` are window queries here, not
stored columns — §5 says so explicitly, and a cached aggregate is a second
source of truth for the number the scorer discounts against.

The connection is injected and nothing here commits — the handler owns the
transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from psycopg import Connection

__all__ = ["PriceHistoryRepository", "PriceObservation", "PriceStats"]


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """One `price_history` row."""

    id: UUID
    listing_id: UUID
    price: int
    in_stock: bool
    observed_at: datetime

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> PriceObservation:
        return cls(id=row[0], listing_id=row[1], price=row[2], in_stock=row[3], observed_at=row[4])


@dataclass(frozen=True, slots=True)
class PriceStats:
    """Aggregates over one listing's series within a window.

    Not a table. `observation_count` is carried because a lowest price drawn
    from two observations says much less than one drawn from ninety, and the
    scorer's velocity factor needs to be able to tell the difference.
    """

    observation_count: int
    lowest_price: int
    highest_price: int
    first_seen: datetime
    last_seen: datetime


_COLUMNS: Final = "id, listing_id, price, in_stock, observed_at"

# `observed_at` is left to the column default (now()) rather than accepted as an
# argument: it means "when the database recorded this", and a producer clock
# skewed by a few minutes would reorder a series that the scorer reads as
# chronological.
_INSERT: Final = f"""
INSERT INTO price_history (listing_id, price, in_stock)
VALUES (%s, %s, %s)
RETURNING {_COLUMNS}
"""

_SELECT_LATEST: Final = f"""
SELECT {_COLUMNS} FROM price_history
WHERE listing_id = %s
ORDER BY observed_at DESC
LIMIT 1
"""

# `%s * INTERVAL '1 day'` rather than string-built SQL: the window is a bound
# parameter like everything else. Hits idx_price_history_listing_time.
_SELECT_STATS: Final = """
SELECT count(*), min(price), max(price), min(observed_at), max(observed_at)
FROM price_history
WHERE listing_id = %s
  AND observed_at >= now() - (%s * INTERVAL '1 day')
"""


class PriceHistoryRepository:
    """Appends to and reads `price_history`. Touches no other table."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(self, listing_id: UUID, price: int, in_stock: bool) -> PriceObservation:
        """Append one observation. Always produces a row — the table has no unique key."""
        with self._conn.cursor() as cur:
            cur.execute(_INSERT, (listing_id, price, in_stock))
            row = cur.fetchone()
        assert row is not None  # RETURNING on an unconditional INSERT
        return PriceObservation.from_row(row)

    def latest(self, listing_id: UUID) -> PriceObservation | None:
        """Most recent observation. `None` for a listing seen for the first time."""
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_LATEST, (listing_id,))
            row = cur.fetchone()
        return PriceObservation.from_row(row) if row else None

    def stats(self, listing_id: UUID, *, window_days: int) -> PriceStats | None:
        """Aggregates over the last `window_days`. `None` when the window is empty.

        `None` rather than a zero-filled `PriceStats`: a listing with no history
        has no lowest price, and returning 0 would make the scorer read a brand
        new listing as the deepest discount in the system.
        """
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_STATS, (listing_id, window_days))
            row = cur.fetchone()
        if row is None or row[0] == 0:
            return None
        return PriceStats(
            observation_count=row[0],
            lowest_price=row[1],
            highest_price=row[2],
            first_seen=row[3],
            last_seen=row[4],
        )
