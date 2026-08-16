"""The revalidation guard — `VALIDATION_RULES.md` §5 — Sprint 5 Task 5.1.

§5: "`abs(current_price - detected_price) / detected_price <= 0.02` counts as
unchanged (`STATE_TRANSITIONS.md` §1). This is the single source of truth for
'2%' — do not hardcode a different tolerance anywhere else." That sentence is
why the number lives in `libs` and not in the Revalidation Service: the Bot
renders the verdict, `RevalidationResult.changed` carries it, and the schema
description quotes it, so three places would otherwise each own a copy of a
threshold that only one document is allowed to set.

The comparison is exact, on `Decimal`, not float. Prices are paise integers
(`common.json#/$defs/paise`) and `0.02` has no binary float representation, so
a delta landing exactly on the boundary — 100000 paise against 102000 — decides
`CONFIRMED` versus `PRICE_CHANGED` on a rounding artifact if computed in
float. §5 writes the rule with `<=`, so the boundary is *unchanged*, and that
edge has to be reproducible.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

__all__ = [
    "REVALIDATION_PRICE_TOLERANCE",
    "REVALIDATION_TIMEOUT_SECONDS",
    "price_within_tolerance",
    "revalidation_changed",
]

#: `VALIDATION_RULES.md` §5 / `STATE_TRANSITIONS.md` §1 "Tolerance changed"
#: guard. The only place this fraction is written.
REVALIDATION_PRICE_TOLERANCE: Final = Decimal("0.02")

#: `STATE_TRANSITIONS.md` §1: "REVALIDATING --(timeout 30s, no response)-->
#: PRICE_CHANGED". The Bot's deadline and the Revalidation Service's own budget
#: are the same 30s (`SERVICE_INTERFACES.md` §3: "Must respond within 30s [...]
#: the service should not bother emitting late"), so both read it from here.
REVALIDATION_TIMEOUT_SECONDS: Final = 30


def price_within_tolerance(detected_price: int, current_price: int) -> bool:
    """True when the live price counts as unchanged — `VALIDATION_RULES.md` §5.

    "in either direction" (`STATE_TRANSITIONS.md` §1): the delta is absolute, so
    a listing that got 5% *cheaper* since it was scored is still a change the
    user re-confirms. It is not treated as a free upgrade — the price the user
    was shown is no longer the price on offer either way.

    A non-positive `detected_price` cannot be a denominator. It is also
    impossible on a scored deal (`paise` is `exclusiveMinimum: 0`), so it is a
    corrupt reference rather than a cheap listing, and calling it "unchanged"
    would confirm a purchase against a price nobody validated.
    """
    if detected_price <= 0:
        raise ValueError(f"detected_price must be positive paise, got {detected_price}")
    delta = abs(Decimal(current_price) - Decimal(detected_price)) / Decimal(detected_price)
    return delta <= REVALIDATION_PRICE_TOLERANCE


def revalidation_changed(
    *,
    detected_price: int,
    current_price: int,
    in_stock: bool,
    was_in_stock: bool | None = None,
) -> bool:
    """`RevalidationResult.changed` — the whole §5 guard, price and stock together.

    `STATE_TRANSITIONS.md` §1: "price delta > 2% in either direction, OR any
    change in `in_stock`, counts as changed".

    `was_in_stock` is `None` when the baseline is unknown, which is the ordinary
    case: `DEAL_SCORED` (`EVENT_SCHEMAS.md` §2) carries `detected_price` but no
    stock flag, so the Revalidation Service has a price to compare against and
    nothing to compare stock against. Unknown baseline still detects the flip
    that matters — `in_stock=False` is `changed` regardless of what came before,
    since a purchase cannot proceed against an out-of-stock listing
    (`REVAL_SOLD_OUT`, `SOLD_OUT` edge). What it cannot detect is a
    false-to-true flip, and a deal that was out of stock when scored is not one
    the Bot offers. Recorded as a contract gap in `INPUTS_NEEDED.md`.
    """
    if not in_stock:
        return True
    if was_in_stock is not None and was_in_stock != in_stock:
        return True
    return not price_within_tolerance(detected_price, current_price)
