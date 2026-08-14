"""`deals` access — Sprint 3 Task 3.1.

`DATABASE_SCHEMA.md` §6, statuses from `ENUMS.md` §deal_status and
`STATE_TRANSITIONS.md` §1.

The dedup rule — at most one non-terminal deal per listing — cannot be a
partial unique index, because the status set is mutable (§6 says so). It is
enforced here instead, and the enforcement is the reason `lock_listing()`
exists: two transactions can both find no open deal and both insert, and a
`SELECT ... FOR UPDATE` that matches no row locks nothing.

The connection is injected and nothing here commits — the handler owns the
transaction, which is also what makes the advisory lock meaningful: it is held
to the end of that transaction and released with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Json

from libs.canonical_models.scored_deal import ScoreBreakdown
from libs.enums import DealStatus

__all__ = [
    "OPEN_DEAL_STATUSES",
    "TERMINAL_DEAL_STATUSES",
    "Deal",
    "DealRepository",
]

# Verbatim from the §6 dedup comment. Listed rather than derived so that adding
# a `DealStatus` member does not silently make it "open".
TERMINAL_DEAL_STATUSES: Final[frozenset[DealStatus]] = frozenset(
    {
        DealStatus.EXPIRED,
        DealStatus.IGNORED,
        DealStatus.ORDERED,
        DealStatus.PRICE_CHANGED_REJECTED,
        DealStatus.SOLD_OUT_REJECTED,
    }
)

OPEN_DEAL_STATUSES: Final[frozenset[DealStatus]] = frozenset(DealStatus) - TERMINAL_DEAL_STATUSES


@dataclass(frozen=True, slots=True)
class Deal:
    """One `deals` row."""

    id: UUID
    listing_id: UUID
    status: DealStatus
    score: Decimal
    score_breakdown: ScoreBreakdown
    detected_price: int
    reference_price: int
    discount_pct: Decimal
    notified_at: datetime | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Deal:
        """Build from a `_COLUMNS`-ordered row.

        `score` and `discount_pct` stay `Decimal` (both are `NUMERIC(5,2)`);
        the breakdown is rebuilt into its model so callers do not index into a
        raw dict whose keys the scoring config decides.
        """
        return cls(
            id=row[0],
            listing_id=row[1],
            status=DealStatus(row[2]),
            score=row[3],
            score_breakdown=ScoreBreakdown.from_dict(row[4]),
            detected_price=row[5],
            reference_price=row[6],
            discount_pct=row[7],
            notified_at=row[8],
            expires_at=row[9],
            created_at=row[10],
            updated_at=row[11],
        )


_COLUMNS: Final = (
    "id, listing_id, status, score, score_breakdown, detected_price, "
    "reference_price, discount_pct, notified_at, expires_at, created_at, updated_at"
)

# Statuses are passed as an array parameter rather than interpolated into an
# IN (...) list — the set is data, and data belongs in a bound parameter.
_SELECT_OPEN_FOR_LISTING: Final = f"""
SELECT {_COLUMNS} FROM deals
WHERE listing_id = %s AND status <> ALL(%s)
ORDER BY created_at DESC
LIMIT 1
"""

_SELECT_BY_ID: Final = f"SELECT {_COLUMNS} FROM deals WHERE id = %s"

# The row lock a status transition takes: two taps on the same message arriving
# at two workers must not both read `DEAL_SENT` and both write. Unlike deal
# creation this one can be a row lock, because the row exists by definition.
_SELECT_BY_ID_FOR_UPDATE: Final = f"{_SELECT_BY_ID} FOR UPDATE"

_INSERT: Final = f"""
INSERT INTO deals (
  listing_id, status, score, score_breakdown,
  detected_price, reference_price, discount_pct, expires_at
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING {_COLUMNS}
"""

_UPDATE_STATUS: Final = f"""
UPDATE deals SET status = %s, updated_at = now()
WHERE id = %s
RETURNING {_COLUMNS}
"""

_LOCK_LISTING: Final = "SELECT pg_advisory_xact_lock(%s)"

_TERMINAL_VALUES: Final[list[str]] = sorted(str(status) for status in TERMINAL_DEAL_STATUSES)

# Postgres advisory lock keys are signed 64-bit; fold the UUID down to 63 bits
# so the value is always positive and the mapping is deterministic across
# processes. Collisions between two listings are possible and harmless: the
# consequence is one transaction waiting for an unrelated one, not a lost deal.
_ADVISORY_KEY_MASK: Final = (1 << 63) - 1


class DealRepository:
    """Reads and writes `deals`. Touches no other table."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def lock_listing(self, listing_id: UUID) -> None:
        """Serialize deal creation for one listing until the transaction ends.

        Call this *before* `find_open_for_listing()` when the next step may
        insert. An advisory lock rather than `SELECT ... FOR UPDATE` on the
        listing row for two reasons: this repository owns `deals` and nothing
        else, and row locks cannot cover a row that does not exist yet, which
        is exactly the race — two transactions both seeing no open deal.
        """
        key = int(listing_id) & _ADVISORY_KEY_MASK
        with self._conn.cursor() as cur:
            cur.execute(_LOCK_LISTING, (key,))

    def find_open_for_listing(self, listing_id: UUID) -> Deal | None:
        """The listing's non-terminal deal, if it has one.

        `LIMIT 1` with newest first: the dedup rule means there should be at
        most one, and if history ever left two behind, the recent one is the
        one a caller means.
        """
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_OPEN_FOR_LISTING, (listing_id, _TERMINAL_VALUES))
            row = cur.fetchone()
        return Deal.from_row(row) if row else None

    def get_by_id(self, deal_id: UUID, *, for_update: bool = False) -> Deal | None:
        """One deal by id, optionally locked for the rest of the transaction.

        `for_update=True` is for read-decide-write sequences — a status
        transition reads the current status and then writes based on it, and
        without the lock two concurrent taps can both pass the same guard.
        """
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_BY_ID_FOR_UPDATE if for_update else _SELECT_BY_ID, (deal_id,))
            row = cur.fetchone()
        return Deal.from_row(row) if row else None

    def insert(
        self,
        *,
        listing_id: UUID,
        score: Decimal,
        score_breakdown: ScoreBreakdown,
        detected_price: int,
        reference_price: int,
        discount_pct: Decimal,
        expires_at: datetime,
        status: DealStatus = DealStatus.SCORED,
    ) -> Deal:
        """Insert one deal. Caller is responsible for having taken the lock.

        `score_breakdown` is stored verbatim and never recomputed
        (`STATE_TRANSITIONS.md` §1) — including its `weights_version`, without
        which the numbers cannot be interpreted later.
        """
        params = (
            listing_id,
            str(status),
            score,
            Json(score_breakdown.to_dict()),
            detected_price,
            reference_price,
            discount_pct,
            expires_at,
        )
        with self._conn.cursor() as cur:
            cur.execute(_INSERT, params)
            row = cur.fetchone()
        assert row is not None  # RETURNING on an unconditional INSERT
        return Deal.from_row(row)

    def update_status(self, deal_id: UUID, status: DealStatus) -> Deal | None:
        """Move one deal to `status`. `None` if the deal is gone.

        Legal edges are `STATE_TRANSITIONS.md` §1's business, not this
        repository's: a repository that silently refused a write would make an
        illegal transition look like a missing row.
        """
        with self._conn.cursor() as cur:
            cur.execute(_UPDATE_STATUS, (str(status), deal_id))
            row = cur.fetchone()
        return Deal.from_row(row) if row else None
