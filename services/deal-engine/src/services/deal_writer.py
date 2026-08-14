"""One-open-deal-per-listing dedup guard — Sprint 3 Task 3.4.

`DATABASE_SCHEMA.md` §6: "at most one deal per listing_id with status NOT IN
('EXPIRED','IGNORED','ORDERED','PRICE_CHANGED_REJECTED','SOLD_OUT_REJECTED')".
The schema cannot express this — a partial unique index over a mutable status
set is not practical in Postgres — so it is enforced here, and this module is
the only place a `deals` row is created.

The race is two `LISTING_DISCOVERED` events for the same listing arriving on
different workers: both check, both find nothing open, both insert. A check
alone therefore proves nothing; the check has to happen behind a lock that the
other transaction also takes, which is `DealRepository.lock_listing()`. The
lock is transaction-scoped, so it is released by the same commit or rollback
that makes the insert visible — there is no window between "row exists" and
"lock dropped".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from libs.canonical_models.scored_deal import ScoredDeal
from src.repositories.deal_repo import Deal, DealRepository

__all__ = ["DealWriteResult", "write_deal"]

logger: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DealWriteResult:
    """What happened, and the row either way.

    `created` is what the caller keys the `DEAL_SCORED` emit off: a deal that
    was already open is not news, and re-announcing it every scan is how a user
    gets the same notification six times an hour.
    """

    deal: Deal
    created: bool


def write_deal(repo: DealRepository, scored: ScoredDeal) -> DealWriteResult:
    """Persist `scored` unless the listing already has an open deal.

    Takes the listing's lock first, so a concurrent call for the same listing
    waits here rather than racing the existence check. The caller commits: the
    lock is held until it does, which is exactly as long as the guard needs it.
    """
    repo.lock_listing(scored.listing_id)

    open_deal = repo.find_open_for_listing(scored.listing_id)
    if open_deal is not None:
        logger.info(
            "listing %s already has open deal %s (%s); not writing a second",
            scored.listing_id,
            open_deal.id,
            open_deal.status,
        )
        return DealWriteResult(deal=open_deal, created=False)

    deal = repo.insert(
        listing_id=scored.listing_id,
        score=_as_decimal(scored.score),
        score_breakdown=scored.score_breakdown,
        detected_price=scored.detected_price,
        reference_price=scored.reference_price,
        discount_pct=_as_decimal(scored.discount_pct),
        expires_at=scored.expires_at,
    )
    return DealWriteResult(deal=deal, created=True)


def _as_decimal(value: float) -> Decimal:
    """`score` and `discount_pct` are floats on the model, `NUMERIC(5,2)` in the table.

    Converted through `str` rather than `Decimal(float)`: the latter carries
    the full binary expansion (`Decimal(33.4)` is `33.39999...`), which
    Postgres would then round on the way in. Going through the repr rounds
    once, here, visibly.
    """
    return Decimal(str(round(value, 2)))
