"""`revalidate(listing_id) -> RevalidationResult` — `SERVICE_INTERFACES.md` §3.

Sprint 5 Tasks 5.1 and 5.3.

§3 gives the signature and the two rules that make it more than a fetch:

* `changed` is computed "per the 2%-delta / stock-flip guard". It is computed by
  calling `libs.validation_rules.revalidation_changed`, never by comparing
  against a number written here — `VALIDATION_RULES.md` §5 says the tolerance has
  one home, and Task 5.1's Definition of Done says this service reads it from
  there.
* "Must respond within 30s or the Bot times out [...] the service should not
  bother emitting late." That is Task 5.3, and it is stronger than "should not
  bother": a late `DEAL_REVALIDATED` is actively harmful. The Bot has already
  applied `REVAL_TIMEOUT` and moved the deal to `PRICE_CHANGED`
  (`STATE_TRANSITIONS.md` §1); an event landing afterwards asks it to re-decide a
  transition it has taken, and `PRICE_CHANGED -> REVALIDATING` is capped at one
  round-trip per deal, so spending it on a stale answer costs the user their one
  re-confirmation.

The budget is therefore enforced on both sides of the read: a deadline already
blown before the read is not read at all, and a read that returns after the
deadline is discarded rather than published. `time.monotonic` and not
`datetime.now` — a clock adjustment mid-read must not be able to hand back a
window that has closed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from libs.canonical_models import RevalidationResult
from libs.error_codes.error_codes import REVAL_PRICE_CHANGED, REVAL_SOLD_OUT, REVAL_TIMEOUT
from libs.validation_rules import REVALIDATION_TIMEOUT_SECONDS, revalidation_changed
from src.services.listing_source import ListingSource

__all__ = ["BudgetExceededError", "TimeoutBudget", "revalidate"]

logger: Final = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """The 30s window closed before a result was ready. `REVAL_TIMEOUT`.

    Raised rather than returned as a `RevalidationResult` with `changed=True`:
    the two are not the same event. A timeout means *no* `DEAL_REVALIDATED` is
    published and the Bot's own fail-safe applies (Task 5.3); a returned
    `changed=True` would publish a price and a stock flag this service never
    actually confirmed.
    """

    def __init__(self, listing_id: UUID, elapsed_seconds: float, budget_seconds: int) -> None:
        self.listing_id = listing_id
        self.elapsed_seconds = elapsed_seconds
        self.budget_seconds = budget_seconds
        super().__init__(
            f"{REVAL_TIMEOUT.code}: revalidation of {listing_id} took "
            f"{elapsed_seconds:.1f}s of a {budget_seconds}s budget; not emitting"
        )


@dataclass(slots=True)
class TimeoutBudget:
    """A monotonic countdown, started when the request was picked up.

    Constructed by the handler rather than inside `revalidate()` so the clock
    starts where the obligation does. The 30s in `SERVICE_INTERFACES.md` §3 is
    measured from the Bot's emit, and everything between that and the live read —
    stream delivery, dedup lookup, projection lookup — is spent out of the same
    window. A budget that started at the read would be a budget on the fast part.
    """

    budget_seconds: int = REVALIDATION_TIMEOUT_SECONDS
    clock: Callable[[], float] = time.monotonic
    started_at: float = 0.0

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    @property
    def elapsed_seconds(self) -> float:
        return self.clock() - self.started_at

    @property
    def remaining_seconds(self) -> float:
        return self.budget_seconds - self.elapsed_seconds

    def expired(self) -> bool:
        """True once the window has closed. `>=`, so a budget of 0 is already closed."""
        return self.elapsed_seconds >= self.budget_seconds


def revalidate(
    listing_id: UUID,
    *,
    detected_price: int,
    deal_id: UUID,
    source: ListingSource,
    budget: TimeoutBudget | None = None,
    was_in_stock: bool | None = None,
) -> RevalidationResult:
    """Read the listing live and return the verdict. `SERVICE_INTERFACES.md` §3.

    Keyword arguments beyond §3's `listing_id`: `detected_price` and `deal_id`
    are what the result is *about* (`RevalidationResult` carries `deal_id`, and
    §5's tolerance is measured against the scored price), and neither is
    derivable from a `listing_id` without reading a table this service does not
    own. `source` is the transport, injected so the fixture stub and the eventual
    live reader are the same call here.

    Raises `BudgetExceededError` when the window closed — before the read, so a
    hopeless request costs no marketplace traffic, and after it, so a slow
    response is discarded instead of published late.
    """
    budget = budget or TimeoutBudget()
    if budget.expired():
        raise BudgetExceededError(listing_id, budget.elapsed_seconds, budget.budget_seconds)

    snapshot = source.read(listing_id)

    if budget.expired():
        raise BudgetExceededError(listing_id, budget.elapsed_seconds, budget.budget_seconds)

    changed = revalidation_changed(
        detected_price=detected_price,
        current_price=snapshot.current_price,
        in_stock=snapshot.in_stock,
        was_in_stock=was_in_stock,
    )
    if changed:
        # INFO severity, both codes (`ERROR_CODES.md`): a price that moved or a
        # listing that sold out is the system working, not failing. Logged with
        # the code so the same search finds every rejected confirmation.
        code = REVAL_SOLD_OUT if not snapshot.in_stock else REVAL_PRICE_CHANGED
        logger.info(
            "%s: deal %s listing %s scored at %d, now %d, in_stock=%s",
            code.code,
            deal_id,
            listing_id,
            detected_price,
            snapshot.current_price,
            snapshot.in_stock,
        )

    return RevalidationResult(
        deal_id=deal_id,
        listing_id=listing_id,
        current_price=snapshot.current_price,
        in_stock=snapshot.in_stock,
        changed=changed,
        # When the observation was taken, not when the verdict was formed. The
        # Bot shows the user a price as of a moment, and the read is that moment.
        checked_at=snapshot.observed_at,
    )
