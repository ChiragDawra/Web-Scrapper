"""`normalize(raw_marketplace_response) -> CanonicalProduct` — `SERVICE_INTERFACES.md` §1.

§1 names exactly one method, and says why: "`normalize()` is the sole place
marketplace-specific parsing lives — every downstream service consumes only
`CanonicalProduct`". This module is that boundary in code. A connector subclass
may hold as much HTML, JSON and marketplace lore as it needs; nothing above
`normalize()`'s return type is allowed to know any of it.

`fetch_raw()` is declared here too, and is *not* from §1 — §1 describes the
connector as a "source of ingestion, runs on a schedule/poll" but leaves the
read path unspecified, so the abstract method fixes only the shape the poll loop
needs (an iterable of opaque raw items) and no transport. Sprint 2 Task 2.3
implements Amazon's against recorded fixtures; whether the live one is an
official API, a data provider or an HTML fetch is an open decision recorded in
`INPUTS_NEEDED.md` item 1.

Errors: `ERROR_CODES.md` `CONN_*`. `ParseFailedError` carries the registry entry
rather than a string, so a caller reads `severity`/`retryable` off the contract
instead of guessing. §1: "On `CONN_PARSE_FAILED`, logs and skips the item; does
not emit a partial/malformed `LISTING_DISCOVERED`" — raising is how an item says
"skip me", and the skipping itself is the poll loop's job (Task 2.5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, ClassVar

from libs.canonical_models import CanonicalProduct
from libs.enums import MarketplaceCode
from libs.error_codes import ErrorCode
from libs.error_codes.error_codes import (
    CONN_AUTH_FAILED,
    CONN_CAPTCHA,
    CONN_LISTING_NOT_FOUND,
    CONN_PARSE_FAILED,
    CONN_RATE_LIMITED,
    CONN_TIMEOUT,
)

__all__ = [
    "AuthFailedError",
    "CaptchaError",
    "ConnectorError",
    "ConnectorInterface",
    "ConnectorTimeoutError",
    "ListingNotFoundError",
    "ParseFailedError",
    "RateLimitedError",
]


class ConnectorError(Exception):
    """A `CONN_*` failure. `error` is the `ERROR_CODES.md` row, never an ad hoc string."""

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


class ParseFailedError(ConnectorError):
    """Raised by `normalize()` when the raw item cannot yield a complete `CanonicalProduct`.

    Raised, not returned as a partial product: §1 forbids emitting a
    partial/malformed listing, and a half-populated return value is exactly how
    one gets emitted by accident three call frames later.
    """

    error = CONN_PARSE_FAILED


class RateLimitedError(ConnectorError):
    error = CONN_RATE_LIMITED


class AuthFailedError(ConnectorError):
    error = CONN_AUTH_FAILED


class ListingNotFoundError(ConnectorError):
    error = CONN_LISTING_NOT_FOUND


class ConnectorTimeoutError(ConnectorError):
    """Not named `TimeoutError`: that name is a builtin, and an `OSError` subclass
    raised by socket reads. A connector does network IO, so shadowing it would make
    `except TimeoutError` in this package silently stop catching real socket timeouts.
    """

    error = CONN_TIMEOUT


class CaptchaError(ConnectorError):
    error = CONN_CAPTCHA


class ConnectorInterface(ABC):
    """One deployable per marketplace (`SERVICE_INTERFACES.md` §1). Owns no tables."""

    #: Which marketplace this connector reads. Set on the subclass; every
    #: `CanonicalProduct` it returns must carry the same value, since the Deal
    #: Engine keys `listings` off `(marketplace, external_listing_id)`.
    marketplace: ClassVar[MarketplaceCode]

    def __new__(cls, *args: Any, **kwargs: Any) -> ConnectorInterface:
        """Fail on construction when a subclass forgot `marketplace`.

        In `__new__` rather than `__init_subclass__` because `ABCMeta` populates
        `__abstractmethods__` *after* `__init_subclass__` runs, so a check there
        cannot tell a half-finished abstract base from a real connector. Every
        subclass reaches `__new__` whether or not it defines `__init__`.
        """
        if getattr(cls, "marketplace", None) is None:
            raise TypeError(f"{cls.__name__} must set `marketplace: ClassVar[MarketplaceCode]`")
        return super().__new__(cls)

    @abstractmethod
    def fetch_raw(self) -> Iterable[Any]:
        """Yield raw, unparsed marketplace items — one per candidate listing.

        Opaque by design: `dict` for an API connector, `str` of HTML for a
        scraping one. Only `normalize()` is allowed to look inside.
        """

    @abstractmethod
    def normalize(self, raw_marketplace_response: Any) -> CanonicalProduct:
        """`SERVICE_INTERFACES.md` §1, verbatim signature.

        Raises `ParseFailedError` (`CONN_PARSE_FAILED`) when the item is
        unusable. Returns a fully valid `CanonicalProduct` or raises; there is
        no third outcome.
        """
