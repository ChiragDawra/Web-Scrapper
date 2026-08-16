"""The live read path behind `revalidate()` — Sprint 5 Task 5.1.

`SERVICE_INTERFACES.md` §3: "Fetches current price/stock live from the
marketplace (via the relevant Connector's read path, not a cached `listings`
row)". Two halves of that sentence shape this module.

*Not a cached `listings` row* is the load-bearing half, and it is why nothing
here reads Postgres: `listings` belongs to the Deal Engine (`DATABASE_SCHEMA.md`
table ownership, ADR-009), and a price copied from it at confirmation time is the
exact staleness revalidation exists to catch.

*Via the relevant Connector's read path* is a transport statement, and the
transport is still undecided (`INPUTS_NEEDED.md` item 1: official API vs. data
provider vs. HTML). So this module fixes only the shape — `read(listing_id) ->
ListingSnapshot` — and ships the same recorded-fixture stub the Sprint 2/4
connectors use for `fetch_raw()`. `ListingSource` is a Protocol rather than an
ABC so the eventual live implementation can live in the connector package and
satisfy this without either service importing the other's `src`.

Errors are `ERROR_CODES.md` `CONN_*` codes, reused rather than redefined: a
listing that 404s or a marketplace that times out is the same condition here as
in a connector, and a second registry of near-identical codes is how two
services end up disagreeing about what is retryable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Final, Protocol
from uuid import UUID

from libs.error_codes import ErrorCode
from libs.error_codes.error_codes import CONN_LISTING_NOT_FOUND, CONN_PARSE_FAILED

__all__ = [
    "DEFAULT_FIXTURE_DIR",
    "FixtureListingSource",
    "ListingReadError",
    "ListingSnapshot",
    "ListingSource",
    "ListingUnreadableError",
    "ListingVanishedError",
]


@dataclass(frozen=True, slots=True)
class ListingSnapshot:
    """One live observation of a listing: what it costs now, and whether it is buyable.

    Deliberately smaller than `CanonicalProduct`. Revalidation answers two
    questions (`RevalidationResult`), and a snapshot carrying a title and a brand
    would invite a consumer to treat this as a re-ingestion path — which it is
    not: `STATE_TRANSITIONS.md` §1 forbids in-place rescoring, so nothing read
    here may touch the deal's score.
    """

    listing_id: UUID
    current_price: int
    in_stock: bool
    observed_at: datetime


class ListingReadError(Exception):
    """A `CONN_*` failure reading one listing. `error` is the `ERROR_CODES.md` row."""

    error: ClassVar[ErrorCode]

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.error.code}: {detail}" if detail else self.error.code)

    @property
    def code(self) -> str:
        return self.error.code

    @property
    def retryable(self) -> bool:
        return self.error.retryable


class ListingVanishedError(ListingReadError):
    """The listing is gone from the marketplace, not merely out of stock.

    Distinct from `in_stock=False`: a delisted product has no price to compare,
    so it cannot be answered with a `RevalidationResult` — the handler lets this
    propagate and the Bot's own 30s timeout applies `REVAL_TIMEOUT`, which
    fail-safes to `PRICE_CHANGED` (`STATE_TRANSITIONS.md` §1). Inventing a
    `current_price` of 0 to force a "changed" verdict would put a fabricated
    price in the audit trail.
    """

    error = CONN_LISTING_NOT_FOUND


class ListingUnreadableError(ListingReadError):
    """The response arrived but does not yield a price and a stock flag."""

    error = CONN_PARSE_FAILED


class ListingSource(Protocol):
    """The one read `revalidate()` needs. Implementations own their transport."""

    def read(self, listing_id: UUID) -> ListingSnapshot:
        """Return the live price/stock for one listing, or raise a `ListingReadError`."""
        ...


#: Recordings live beside the service's tests, one file per listing, named for
#: the `listing_id` the request asks about — the only key a
#: `DEAL_REVALIDATION_REQUEST` carries. Same location and same reasoning as the
#: connectors' `DEFAULT_FIXTURE_DIR`: the image layout mirrors the repo, so one
#: path is correct in both.
DEFAULT_FIXTURE_DIR: Final = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "listings"

_PRICE_KEYS: Final = ("current_price", "price")
_STOCK_KEYS: Final = ("in_stock", "available")


class FixtureListingSource:
    """Replays a recorded live read. The stub half of `INPUTS_NEEDED.md` item 1.

    Kept behind the same `ListingSource` shape as the eventual live source so the
    swap is a one-line change in `main.py` and no handler or test moves with it.
    """

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self._fixture_dir = fixture_dir or DEFAULT_FIXTURE_DIR

    @property
    def fixture_dir(self) -> Path:
        return self._fixture_dir

    def read(self, listing_id: UUID) -> ListingSnapshot:
        path = self._fixture_dir / f"{listing_id}.json"
        if not path.is_file():
            # A missing recording *is* the "no such listing" case for this
            # transport. Treated as vanished rather than as a test-setup problem
            # because the service cannot tell the two apart at runtime, and the
            # safe reading of "I cannot see this listing" is not "it is fine".
            raise ListingVanishedError(f"no recording for listing {listing_id} in {path.parent}")
        return self._snapshot(listing_id, json.loads(path.read_text(encoding="utf-8")))

    def _snapshot(self, listing_id: UUID, payload: Any) -> ListingSnapshot:
        if not isinstance(payload, dict):
            raise ListingUnreadableError(f"recording for {listing_id} is not an object")

        price = _first_present(payload, _PRICE_KEYS)
        stock = _first_present(payload, _STOCK_KEYS)
        if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
            raise ListingUnreadableError(f"recording for {listing_id} has no positive paise price")
        if not isinstance(stock, bool):
            # `VALIDATION_RULES.md` §1 on `in_stock`: "connectors must not omit;
            # infer false if the response gives no positive stock signal, never
            # leave null." Absent is a defective recording, not an inferred
            # false — inferring here would silently answer `SOLD_OUT` for a
            # listing nobody actually checked.
            raise ListingUnreadableError(f"recording for {listing_id} has no boolean in_stock")

        observed = payload.get("observed_at")
        return ListingSnapshot(
            listing_id=listing_id,
            current_price=price,
            in_stock=stock,
            # The recording may state when it was taken; a live source always
            # will. Absent, now is the honest answer for a replay.
            observed_at=(
                datetime.fromisoformat(observed) if isinstance(observed, str) else datetime.now(UTC)
            ),
        )


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None
